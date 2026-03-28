#!/usr/bin/env python3
"""
AI Artifakte — Agent B3: TWS-Excel-Bridge
===========================================
Verbindet Claude-Scan mit Interactive Brokers TWS und erzeugt
ein Excel-Sheet mit Stop-Buy/Stop-Sell Orders zur Pruefung.

Ablauf:
  1. Laedt Kandidaten aus Pre-Market Scan (JSON) + Persistenzmatrix (JSON)
  2. Verbindet sich mit TWS (ib_async), holt 1Y Daily + 2D 5min Bars
  3. Berechnet exakte Entry/Stop-Levels nach Ollis Methodik
  4. Schreibt alles in ein professionelles Excel-Sheet zur Pruefung

USAGE:
  python3 agent_tws_excel.py                    # Standard (TWS Paper 7497)
  python3 agent_tws_excel.py --live              # TWS Live (Port 7496)
  python3 agent_tws_excel.py --dry-run           # Ohne TWS, nutzt DB-Daten
  python3 agent_tws_excel.py --risk 100          # 100 EUR max Risiko
  python3 agent_tws_excel.py --top 15            # Top 15 Kandidaten

VORAUSSETZUNGEN:
  - TWS oder IB Gateway laeuft (ausser --dry-run)
  - pip install ib_async openpyxl pandas
  - Pre-Market Scan vorher ausfuehren (premarket_scan.json)
"""

import argparse
import asyncio
import json
import sys
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERROR: pip install pandas numpy")
    sys.exit(1)

try:
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment, Border,
                                  Side, numbers)
    from openpyxl.utils import get_column_letter
except ImportError:
    print("ERROR: pip install openpyxl")
    sys.exit(1)


# ==============================================================
# KONFIGURATION
# ==============================================================
TWS_HOST = '127.0.0.1'
CLIENT_ID = 11  # Eigene ID, nicht kollidieren mit Scanner (10)
ACCOUNT = 'U7793506'

# Risiko
DEFAULT_MAX_RISK_EUR = 50
EUR_USD_RATE = 1.08

# Ports
PORTS = {
    'paper': [7497, 4002],
    'live': [7496, 4001],
}

# Golden Cross Toleranz
GOLDEN_CROSS_TOLERANCE = 0.95

# Pfade
SCRIPT_DIR = Path(__file__).resolve().parent
SCAN_JSON = SCRIPT_DIR / 'premarket_scan.json'
PERSIST_JSON = SCRIPT_DIR / 'persistenzmatrix.json'

# DB-Suchpfade (fuer Dry-Run)
DEFAULT_DB_PATHS = [
    Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path.home() / 'Documents' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    SCRIPT_DIR.parent / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
]


# ==============================================================
# HILFSFUNKTIONEN
# ==============================================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(period).mean()

def position_size(entry, stop, max_risk_usd):
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0
    return max(1, int(max_risk_usd / risk_per_share))


# ==============================================================
# DATEN LADEN
# ==============================================================
def load_scan_candidates():
    if not SCAN_JSON.exists():
        print(f"  [B3] WARN: {SCAN_JSON} not found — using persistenz matrix")
        return []
    with open(SCAN_JSON) as f:
        data = json.load(f)
    return data.get('candidates', [])

def load_persistenz():
    if not PERSIST_JSON.exists():
        return {}
    with open(PERSIST_JSON) as f:
        data = json.load(f)
    return data.get('tickers', {})

def build_watchlist(scan, persistenz, top_n=25):
    """Baue Watchlist: Scan-Kandidaten + Top-Persistenz."""
    tickers = []
    seen = set()

    # 1. Scan-Kandidaten (haben aktive Setups)
    for c in scan[:top_n]:
        t = c['ticker']
        if t not in seen:
            tickers.append({
                'ticker': t,
                'source': 'SCAN',
                'scan_setups': c.get('setups', []),
                'scan_score': c.get('score'),
                'scan_max': c.get('score_max'),
            })
            seen.add(t)

    # 2. Top-Persistenz die noch nicht im Scan sind
    if persistenz:
        sorted_pers = sorted(persistenz.items(),
                             key=lambda x: x[1].get('avg_score', 0), reverse=True)
        for t, pd in sorted_pers:
            if t not in seen and pd.get('avg_score', 0) >= 8.0 and pd.get('persistence_pct', 0) >= 70:
                tickers.append({
                    'ticker': t,
                    'source': 'PERSISTENZ',
                    'scan_setups': [],
                    'scan_score': pd.get('current_score'),
                    'scan_max': pd.get('current_max'),
                })
                seen.add(t)
                if len(tickers) >= top_n:
                    break

    return tickers


# ==============================================================
# TWS VERBINDUNG + DATEN
# ==============================================================
async def connect_tws(mode='paper'):
    try:
        from ib_async import IB
    except ImportError:
        print("ERROR: pip install ib_async")
        return None

    ib = IB()
    ports = PORTS.get(mode, PORTS['paper'])
    for p in ports:
        try:
            await ib.connectAsync(TWS_HOST, p, clientId=CLIENT_ID)
            names = {7497: 'TWS Paper', 7496: 'TWS Live', 4002: 'GW Paper', 4001: 'GW Live'}
            print(f'  [B3] TWS connected: {names.get(p, f"Port {p}")}')
            return ib
        except Exception:
            continue
    return None


async def get_daily_bars(ib, symbol, days='1 Y'):
    from ib_async import Stock, util
    contract = Stock(symbol, 'SMART', 'USD')
    try:
        await ib.qualifyContractsAsync(contract)
        bars = await ib.reqHistoricalDataAsync(
            contract, endDateTime='', durationStr=days,
            barSizeSetting='1 day', whatToShow='TRADES',
            useRTH=True, formatDate=1)
        return util.df(bars) if bars else None
    except Exception:
        return None


def analyze_ticker_tws(df_daily, symbol, max_risk_usd):
    """Analysiert Tageschart via TWS-Daten, generiert Orders."""
    if df_daily is None or len(df_daily) < 200:
        return []

    orders = []

    # MAs
    df_daily['ema5'] = calc_ema(df_daily['close'], 5)
    df_daily['ema10'] = calc_ema(df_daily['close'], 10)
    df_daily['ema20'] = calc_ema(df_daily['close'], 20)
    df_daily['sma50'] = calc_sma(df_daily['close'], 50)
    df_daily['ema65'] = calc_ema(df_daily['close'], 65)
    df_daily['sma200'] = calc_sma(df_daily['close'], 200)
    df_daily['vol_avg'] = calc_sma(df_daily['volume'], 20)

    last = df_daily.iloc[-1]
    prev = df_daily.iloc[-2]
    price = float(last['close'])

    # Phase-2 Check
    phase2 = (price > last['sma200'] and
              last['sma50'] >= GOLDEN_CROSS_TOLERANCE * last['sma200'] and
              last['sma200'] > df_daily['sma200'].iloc[-20])
    if not phase2:
        return []

    # Schluessel-Levels
    high_20d = float(df_daily['high'].tail(20).max())
    low_20d = float(df_daily['low'].tail(20).min())
    low_5d = float(df_daily['low'].tail(5).min())
    high_5d = float(df_daily['high'].tail(5).max())

    # Swing-Lows (fuer UC)
    swing_lows = []
    lows = df_daily['low'].tail(40)
    for i in range(2, len(lows)-2):
        if (lows.iloc[i] <= lows.iloc[i-1] and lows.iloc[i] <= lows.iloc[i-2] and
                lows.iloc[i] <= lows.iloc[i+1] and lows.iloc[i] <= lows.iloc[i+2]):
            swing_lows.append(round(float(lows.iloc[i]), 2))

    # SETUP 1: UC Stop-Buy
    for sl in swing_lows:
        dist = (price - sl) / price * 100
        if 0 < dist < 5:
            entry = round(sl + 0.05, 2)
            stop = round(sl - (price * 0.005), 2)
            shares = position_size(entry, stop, max_risk_usd)
            if shares > 0:
                risk = round(abs(entry - stop) * shares, 2)
                orders.append({
                    'type': 'STOP-BUY', 'setup': 'UC',
                    'symbol': symbol, 'shares': shares,
                    'entry': entry, 'stop': stop,
                    'risk_usd': risk,
                    'reason': f'UC: Swing-Low {sl:.2f} — Buy Rueckeroberung',
                    'priority': 1,
                })

    # SETUP 2: MAUR Stop-Buy
    for ma_name, ma_val in [('EMA20', last['ema20']), ('SMA50', last['sma50']), ('EMA65', last['ema65'])]:
        mv = round(float(ma_val), 2)
        dist = (price - mv) / price * 100
        if -2 < dist < 3:
            entry = round(mv + 0.10, 2)
            stop = round(mv - (price * 0.008), 2)
            shares = position_size(entry, stop, max_risk_usd)
            if shares > 0:
                risk = round(abs(entry - stop) * shares, 2)
                orders.append({
                    'type': 'STOP-BUY', 'setup': 'MAUR',
                    'symbol': symbol, 'shares': shares,
                    'entry': entry, 'stop': stop,
                    'risk_usd': risk,
                    'reason': f'MAUR: {ma_name}={mv:.2f} — Buy Rueckeroberung',
                    'priority': 2,
                })

    # SETUP 3: KONTRAKTION (Inside Candle)
    if len(df_daily) >= 3:
        is_inside = (last['high'] < prev['high'] and last['low'] > prev['low'])
        vol_dry = (last['volume'] < float(last['vol_avg']) * 0.6
                   if pd.notna(last['vol_avg']) and last['vol_avg'] > 0 else False)
        if is_inside:
            entry = round(float(last['high']) + 0.05, 2)
            stop = round(float(last['low']) - 0.05, 2)
            shares = position_size(entry, stop, max_risk_usd)
            if shares > 0:
                risk = round(abs(entry - stop) * shares, 2)
                qual = 'IC+VolTrocken' if vol_dry else 'IC'
                orders.append({
                    'type': 'STOP-BUY', 'setup': 'KONTRAKTION',
                    'symbol': symbol, 'shares': shares,
                    'entry': entry, 'stop': stop,
                    'risk_usd': risk,
                    'reason': f'{qual}: Buy ueber {float(last["high"]):.2f}',
                    'priority': 2,
                })

    # SETUP 4: KEILAUSBRUCH
    resistance = round(high_20d, 2)
    dist_resist = (price - resistance) / price * 100
    if -3 < dist_resist < 0:
        entry = round(resistance + 0.10, 2)
        stop = round(low_5d - 0.10, 2)
        shares = position_size(entry, stop, max_risk_usd)
        if shares > 0:
            risk = round(abs(entry - stop) * shares, 2)
            orders.append({
                'type': 'STOP-BUY', 'setup': 'KEIL',
                'symbol': symbol, 'shares': shares,
                'entry': entry, 'stop': stop,
                'risk_usd': risk,
                'reason': f'KEIL: Widerstand {resistance:.2f} — Buy Ausbruch',
                'priority': 3,
            })

    # STOP-SELL Warnungen
    ema20_val = float(last['ema20'])
    sma50_val = float(last['sma50'])

    if price < ema20_val * 1.02:
        sell_stop = round(ema20_val - (price * 0.005), 2)
        orders.append({
            'type': 'STOP-SELL', 'setup': 'WARNUNG',
            'symbol': symbol, 'shares': 0,
            'entry': price, 'stop': sell_stop,
            'risk_usd': 0,
            'reason': f'Nahe EMA20 ({ema20_val:.2f})! Stop-Sell setzen',
            'priority': 4,
        })

    if price < sma50_val * 1.02:
        sell_stop = round(sma50_val - (price * 0.005), 2)
        orders.append({
            'type': 'STOP-SELL', 'setup': 'ALARM',
            'symbol': symbol, 'shares': 0,
            'entry': price, 'stop': sell_stop,
            'risk_usd': 0,
            'reason': f'ALARM: Nahe SMA50 ({sma50_val:.2f})! Sofort raus wenn verloren',
            'priority': 5,
        })

    return orders


# ==============================================================
# DRY-RUN (ohne TWS, aus DB)
# ==============================================================
def analyze_ticker_db(ticker, db_data, dates, max_risk_usd):
    """Dry-Run Analyse aus daily_screen Daten."""
    t_data = db_data.get(ticker, {})
    if not t_data:
        return []

    orders = []
    latest = t_data.get(dates[-1])
    prev = t_data.get(dates[-2]) if len(dates) >= 2 else None
    if not latest or not prev:
        return []

    price = latest.get('kurs')
    if not price or price < 20:
        return []

    phase2 = latest.get('phase2', 0)
    sma50 = latest.get('sma50')
    sma200 = latest.get('sma200')

    if not phase2:
        return []

    # Vereinfachte Level-Erkennung aus den letzten Tagen
    recent_lows = []
    recent_highs = []
    for d in dates[-20:]:
        dd = t_data.get(d)
        if dd and dd.get('kurs'):
            recent_lows.append(dd['kurs'] * (1 + (dd.get('perf_1d', 0) or 0) / 100 * -0.5))
            recent_highs.append(dd['kurs'])

    if not recent_lows:
        return []

    low_20d = min(recent_lows)
    high_20d = max(recent_highs)
    low_5d = min(recent_lows[-5:]) if len(recent_lows) >= 5 else low_20d

    # UC: Kurs nahe an Tief
    dist_low = (price - low_20d) / price * 100
    if 0 < dist_low < 5:
        entry = round(low_20d + 0.05, 2)
        stop = round(low_20d - (price * 0.005), 2)
        shares = position_size(entry, stop, max_risk_usd)
        if shares > 0:
            risk = round(abs(entry - stop) * shares, 2)
            orders.append({
                'type': 'STOP-BUY', 'setup': 'UC',
                'symbol': ticker, 'shares': shares,
                'entry': entry, 'stop': stop,
                'risk_usd': risk,
                'reason': f'UC: Low {low_20d:.2f} — Buy Rueckeroberung',
                'priority': 1,
            })

    # MAUR: Nahe SMA50
    if sma50 and sma50 > 0:
        dist_sma = (price - sma50) / price * 100
        if -2 < dist_sma < 3:
            entry = round(sma50 + 0.10, 2)
            stop = round(sma50 - (price * 0.008), 2)
            shares = position_size(entry, stop, max_risk_usd)
            if shares > 0:
                risk = round(abs(entry - stop) * shares, 2)
                orders.append({
                    'type': 'STOP-BUY', 'setup': 'MAUR',
                    'symbol': ticker, 'shares': shares,
                    'entry': entry, 'stop': stop,
                    'risk_usd': risk,
                    'reason': f'MAUR: SMA50={sma50:.2f} — Buy Rueckeroberung',
                    'priority': 2,
                })

    # Inside Candle (vereinfacht via perf_1d)
    last_range = abs(latest.get('perf_1d', 0) or 0)
    prev_range = abs(prev.get('perf_1d', 0) or 0)
    if last_range < 1.0 and prev_range > last_range:
        entry = round(price * 1.005, 2)
        stop = round(price * 0.99, 2)
        shares = position_size(entry, stop, max_risk_usd)
        if shares > 0:
            risk = round(abs(entry - stop) * shares, 2)
            orders.append({
                'type': 'STOP-BUY', 'setup': 'KONTRAKTION',
                'symbol': ticker, 'shares': shares,
                'entry': entry, 'stop': stop,
                'risk_usd': risk,
                'reason': f'Inside Candle ({last_range:.1f}% Range) — Buy ueber {price:.2f}',
                'priority': 2,
            })

    # Keilausbruch: Nahe am Hoch
    abst_hoch = latest.get('abst_hoch')
    if abst_hoch is not None and -5 < abst_hoch < 0:
        entry = round(high_20d + 0.10, 2)
        stop = round(low_5d - 0.10, 2)
        shares = position_size(entry, stop, max_risk_usd)
        if shares > 0:
            risk = round(abs(entry - stop) * shares, 2)
            orders.append({
                'type': 'STOP-BUY', 'setup': 'KEIL',
                'symbol': ticker, 'shares': shares,
                'entry': entry, 'stop': stop,
                'risk_usd': risk,
                'reason': f'KEIL: Hoch {high_20d:.2f} ({abst_hoch:.0f}%) — Buy Ausbruch',
                'priority': 3,
            })

    # Stop-Sell Warnungen
    if sma50 and price < sma50 * 1.02:
        orders.append({
            'type': 'STOP-SELL', 'setup': 'WARNUNG',
            'symbol': ticker, 'shares': 0,
            'entry': price, 'stop': round(sma50 * 0.995, 2),
            'risk_usd': 0,
            'reason': f'Nahe SMA50 ({sma50:.2f})! Stop-Sell setzen',
            'priority': 4,
        })

    return orders


# ==============================================================
# EXCEL-ERSTELLUNG
# ==============================================================
def create_excel(all_orders, watchlist, persistenz, scan_date, next_day, max_risk_eur, output_path):
    """Erstelle professionelles Trading-Excel."""
    wb = Workbook()

    # === Farben & Styles ===
    DARK_BG = PatternFill('solid', fgColor='0F0F1A')
    HEADER_BG = PatternFill('solid', fgColor='1A1A2E')
    BUY_BG = PatternFill('solid', fgColor='0D3B2E')
    SELL_BG = PatternFill('solid', fgColor='3B0D0D')
    WARN_BG = PatternFill('solid', fgColor='3B2E0D')
    WHITE_FONT = Font(name='Arial', color='E8E8F0', size=10)
    HEADER_FONT = Font(name='Arial', color='E94560', size=10, bold=True)
    TICKER_FONT = Font(name='Arial', color='74B9FF', size=11, bold=True)
    BUY_FONT = Font(name='Arial', color='00B894', size=10, bold=True)
    SELL_FONT = Font(name='Arial', color='D63031', size=10, bold=True)
    MONEY_FONT = Font(name='Arial', color='FFEAA7', size=10)
    DIM_FONT = Font(name='Arial', color='636E72', size=9)
    TITLE_FONT = Font(name='Arial', color='E94560', size=14, bold=True)
    THIN_BORDER = Border(
        bottom=Side(style='thin', color='333333'),
        right=Side(style='thin', color='222222'),
    )
    CENTER = Alignment(horizontal='center', vertical='center')
    LEFT = Alignment(horizontal='left', vertical='center')

    # =========================================================
    # SHEET 1: ORDERS (Hauptblatt)
    # =========================================================
    ws = wb.active
    ws.title = 'Orders Monday'
    ws.sheet_properties.tabColor = 'E94560'

    # Spaltenbreiten
    col_widths = {'A': 4, 'B': 12, 'C': 8, 'D': 10, 'E': 8,
                  'F': 10, 'G': 10, 'H': 10, 'I': 10, 'J': 8,
                  'K': 45, 'L': 6, 'M': 6, 'N': 8}
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    # Titel
    ws.merge_cells('A1:K1')
    ws['A1'] = f'TRADING ORDERS — Monday {next_day}'
    ws['A1'].font = TITLE_FONT
    ws['A1'].fill = DARK_BG

    ws.merge_cells('A2:K2')
    ws['A2'] = f'Base data: {scan_date} | Max Risk: {max_risk_eur} EUR | Account: {ACCOUNT} | transmit=False'
    ws['A2'].font = DIM_FONT
    ws['A2'].fill = DARK_BG

    # Header Zeile 4
    headers = ['#', 'Ticker', 'Type', 'Setup', 'Shares', 'Entry $', 'Stop $',
               'Risk $', 'Risk EUR', 'Prio', 'Reason', 'P%', 'Avg', 'OK?']
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_BG
        cell.alignment = CENTER
        cell.border = THIN_BORDER

    # Freeze
    ws.freeze_panes = 'A5'

    # Orders einfuegen
    row = 5
    buy_orders = [o for o in all_orders if o['type'] == 'STOP-BUY']
    sell_orders = [o for o in all_orders if o['type'] == 'STOP-SELL']
    buy_orders.sort(key=lambda o: o.get('priority', 99))

    for idx, o in enumerate(buy_orders, 1):
        bg = BUY_BG
        t_font = BUY_FONT

        # Persistenz-Info
        pd_info = persistenz.get(o['symbol'], {})
        pers_pct = pd_info.get('persistence_pct', '')
        avg_score = pd_info.get('avg_score', '')

        ws.cell(row=row, column=1, value=idx).font = WHITE_FONT
        ws.cell(row=row, column=2, value=o['symbol']).font = TICKER_FONT
        ws.cell(row=row, column=3, value=o['type']).font = t_font
        ws.cell(row=row, column=4, value=o['setup']).font = WHITE_FONT
        ws.cell(row=row, column=5, value=o['shares']).font = WHITE_FONT
        ws.cell(row=row, column=6, value=o['entry']).font = MONEY_FONT
        ws.cell(row=row, column=6).number_format = '$#,##0.00'
        ws.cell(row=row, column=7, value=o['stop']).font = MONEY_FONT
        ws.cell(row=row, column=7).number_format = '$#,##0.00'
        ws.cell(row=row, column=8, value=o['risk_usd']).font = MONEY_FONT
        ws.cell(row=row, column=8).number_format = '$#,##0.00'
        # Risk EUR = Formel
        ws.cell(row=row, column=9).value = f'=H{row}/{EUR_USD_RATE}'
        ws.cell(row=row, column=9).font = MONEY_FONT
        ws.cell(row=row, column=9).number_format = 'EUR#,##0.00'
        ws.cell(row=row, column=10, value=o.get('priority', '-')).font = DIM_FONT
        ws.cell(row=row, column=11, value=o['reason']).font = WHITE_FONT
        ws.cell(row=row, column=12, value=pers_pct).font = DIM_FONT
        if avg_score:
            ws.cell(row=row, column=13, value=avg_score).font = DIM_FONT
        ws.cell(row=row, column=14, value='').font = WHITE_FONT  # OK? Spalte zum Abhaken

        for c in range(1, 15):
            ws.cell(row=row, column=c).fill = bg
            ws.cell(row=row, column=c).alignment = CENTER if c != 11 else LEFT
            ws.cell(row=row, column=c).border = THIN_BORDER

        row += 1

    # Trennzeile
    if sell_orders:
        row += 1
        ws.merge_cells(f'A{row}:K{row}')
        ws.cell(row=row, column=1, value='STOP-SELL WARNINGS').font = Font(name='Arial', color='D63031', size=10, bold=True)
        ws.cell(row=row, column=1).fill = HEADER_BG
        row += 1

        for idx, o in enumerate(sell_orders, 1):
            ws.cell(row=row, column=1, value=idx).font = WHITE_FONT
            ws.cell(row=row, column=2, value=o['symbol']).font = TICKER_FONT
            ws.cell(row=row, column=3, value=o['type']).font = SELL_FONT
            ws.cell(row=row, column=4, value=o['setup']).font = WHITE_FONT
            ws.cell(row=row, column=7, value=o['stop']).font = MONEY_FONT
            ws.cell(row=row, column=7).number_format = '$#,##0.00'
            ws.cell(row=row, column=11, value=o['reason']).font = WHITE_FONT

            for c in range(1, 15):
                ws.cell(row=row, column=c).fill = SELL_BG if o['setup'] == 'ALARM' else WARN_BG
                ws.cell(row=row, column=c).alignment = CENTER if c != 11 else LEFT
                ws.cell(row=row, column=c).border = THIN_BORDER
            row += 1

    # Zusammenfassung unten
    row += 2
    ws.cell(row=row, column=1, value='SUMMARY').font = HEADER_FONT
    ws.cell(row=row, column=1).fill = DARK_BG
    row += 1
    ws.cell(row=row, column=1, value='Stop-Buy Orders:').font = WHITE_FONT
    ws.cell(row=row, column=2, value=len(buy_orders)).font = BUY_FONT
    row += 1
    ws.cell(row=row, column=1, value='Stop-Sell Warnings:').font = WHITE_FONT
    ws.cell(row=row, column=2, value=len(sell_orders)).font = SELL_FONT
    row += 1
    ws.cell(row=row, column=1, value='Total Risk (Buy):').font = WHITE_FONT
    total_risk = sum(o['risk_usd'] for o in buy_orders)
    ws.cell(row=row, column=2, value=f'${total_risk:.2f}').font = MONEY_FONT
    row += 1
    ws.cell(row=row, column=1, value='Generated:').font = DIM_FONT
    ws.cell(row=row, column=2, value=datetime.now().strftime('%Y-%m-%d %H:%M')).font = DIM_FONT

    # =========================================================
    # SHEET 2: WATCHLIST (Persistenz + Score)
    # =========================================================
    ws2 = wb.create_sheet('Watchlist')
    ws2.sheet_properties.tabColor = '74B9FF'

    wl_headers = ['Ticker', 'Source', 'Score', 'Persistenz%', 'Avg Score',
                  'Trend', 'Streak', 'Price', 'v52High%', 'Setups']
    for col_idx, h in enumerate(wl_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_BG
        cell.alignment = CENTER
        cell.border = THIN_BORDER

    ws2.freeze_panes = 'A2'

    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
        ws2.column_dimensions[col].width = 12
    ws2.column_dimensions['J'].width = 30

    for idx, w in enumerate(watchlist, 2):
        t = w['ticker']
        pd_info = persistenz.get(t, {})

        ws2.cell(row=idx, column=1, value=t).font = TICKER_FONT
        ws2.cell(row=idx, column=2, value=w['source']).font = DIM_FONT
        ws2.cell(row=idx, column=3, value=w.get('scan_score', pd_info.get('current_score', ''))).font = WHITE_FONT
        ws2.cell(row=idx, column=4, value=pd_info.get('persistence_pct', '')).font = WHITE_FONT
        ws2.cell(row=idx, column=5, value=pd_info.get('avg_score', '')).font = WHITE_FONT
        ws2.cell(row=idx, column=6, value=pd_info.get('trend', '')).font = WHITE_FONT
        ws2.cell(row=idx, column=7, value=pd_info.get('streak', '')).font = WHITE_FONT
        ws2.cell(row=idx, column=8, value=pd_info.get('current_kurs', '')).font = MONEY_FONT
        ws2.cell(row=idx, column=9, value=pd_info.get('abst_hoch', '')).font = DIM_FONT

        setup_str = ', '.join(s.get('type', '') for s in w.get('scan_setups', []))
        ws2.cell(row=idx, column=10, value=setup_str).font = WHITE_FONT

        for c in range(1, 11):
            ws2.cell(row=idx, column=c).fill = DARK_BG
            ws2.cell(row=idx, column=c).border = THIN_BORDER
            ws2.cell(row=idx, column=c).alignment = CENTER

    # =========================================================
    # SHEET 3: RULES (Ollis Methodik Kurzreferenz)
    # =========================================================
    ws3 = wb.create_sheet('Rules')
    ws3.sheet_properties.tabColor = 'FFEAA7'
    ws3.column_dimensions['A'].width = 20
    ws3.column_dimensions['B'].width = 60

    rules = [
        ('SETUP-HIERARCHY', ''),
        ('#1 UC (Undercut)', 'Swing-Low unterschritten + zurueckerobert. BESTES CRV.'),
        ('#2 MAUR', 'MA unterschritten + Rally zurueck. Gleichwertig mit UC.'),
        ('#3 Contraction', 'Inside Candle + Vol trocken unter Widerstand. Evening buy!'),
        ('#4 Wedge Breakout', 'Ausbruch ueber Widerstand. Groesserer Stop.'),
        ('#5 Failed Breakdown', 'Short-Signal schlaegt fehl — starkes Long.'),
        ('', ''),
        ('RISK RULES', ''),
        ('Max Risk', f'{max_risk_eur} EUR pro Trade'),
        ('transmit', 'IMMER False! Nur manuell freigeben.'),
        ('Account', ACCOUNT),
        ('Position Size', 'Risk / (Entry - Stop) = Shares'),
        ('', ''),
        ('STOP RULES', ''),
        ('UC Stop', 'Unter dem Undercut-Tief'),
        ('MAUR Stop', '0.8% unter MA'),
        ('IC Stop', 'Unter Inside Candle Low'),
        ('Wedge Stop', 'Unter letztem 5-Tage-Tief'),
        ('', ''),
        ('WARNING SIGNS', ''),
        ('EMA20 Near', 'Stop-Sell vorbereiten wenn < 2% ueber EMA20'),
        ('SMA50 Loss', 'SOFORT raus! Unter fallendem SMA50 passiert nichts Gutes.'),
    ]

    for idx, (key, val) in enumerate(rules, 1):
        ws3.cell(row=idx, column=1, value=key).font = HEADER_FONT if not val else WHITE_FONT
        ws3.cell(row=idx, column=2, value=val).font = WHITE_FONT
        ws3.cell(row=idx, column=1).fill = DARK_BG
        ws3.cell(row=idx, column=2).fill = DARK_BG

    wb.save(output_path)
    return output_path


# ==============================================================
# HAUPTPROGRAMM
# ==============================================================
async def main_async():
    parser = argparse.ArgumentParser(description='AI Artifakte — Agent B3: TWS-Excel-Bridge')
    parser.add_argument('--live', action='store_true', help='TWS Live (Port 7496)')
    parser.add_argument('--dry-run', action='store_true', help='Ohne TWS, nutzt DB-Daten')
    parser.add_argument('--risk', type=int, default=DEFAULT_MAX_RISK_EUR, help='Max Risiko EUR')
    parser.add_argument('--top', type=int, default=25, help='Top N Kandidaten')
    parser.add_argument('--output', help='Output-Pfad fuer Excel')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    max_risk_usd = args.risk * EUR_USD_RATE

    def log(msg):
        if not args.quiet:
            print(f"  [B3] {msg}", flush=True)

    log("=== TWS-Excel-Bridge started ===")
    log(f"Mode: {'DRY-RUN' if args.dry_run else ('LIVE' if args.live else 'PAPER')}")
    log(f"Max Risk: {args.risk} EUR / {max_risk_usd:.0f} USD")

    # Scan + Persistenz laden
    scan = load_scan_candidates()
    log(f"Scan candidates: {len(scan)}")

    persistenz = load_persistenz()
    log(f"Persistenz tickers: {len(persistenz)}")

    watchlist = build_watchlist(scan, persistenz, args.top)
    log(f"Watchlist: {len(watchlist)} tickers")

    # Letztes Datum ermitteln
    scan_date = date.today().isoformat()
    if scan:
        # Aus Scan-JSON
        scan_json_path = SCAN_JSON
        if scan_json_path.exists():
            with open(scan_json_path) as f:
                sj = json.load(f)
            scan_date = sj.get('scan_date', scan_date)

    sd = datetime.strptime(scan_date, '%Y-%m-%d').date()
    next_day = sd + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)

    log(f"Scan date: {scan_date} | Next trading day: {next_day}")

    all_orders = []

    if args.dry_run:
        # Dry-Run: Nutze DB-Daten
        log("DRY-RUN: Loading data from DB...")
        db_path = None
        for p in DEFAULT_DB_PATHS:
            if p.exists():
                db_path = p
                break
        if not db_path:
            log("ERROR: DB not found")
            sys.exit(1)

        db_str = str(db_path)
        for uri_suffix in ['?mode=ro', '?mode=ro&immutable=1', '']:
            try:
                if uri_suffix:
                    con = sqlite3.connect(f"file:{db_str}{uri_suffix}", uri=True, timeout=10)
                else:
                    con = sqlite3.connect(db_str, timeout=10)
                    con.execute("PRAGMA query_only = ON")
                con.execute("SELECT 1")
                break
            except:
                continue
        else:
            log("ERROR: DB connection failed")
            sys.exit(1)

        # Lade Handelstage
        rows = con.execute(
            "SELECT DISTINCT datum FROM daily_screen WHERE datum <= ? ORDER BY datum DESC LIMIT 25",
            (scan_date,)
        ).fetchall()
        dates = [r[0] for r in rows]
        dates.reverse()

        # Lade Rohdaten
        ph = ','.join('?' * len(dates))
        rows = con.execute(f"""
            SELECT ticker, datum, kurs, perf_1d, perf_3m,
                   abst_hoch, sma50, sma200, golden_cross, phase2,
                   avg_vol, rel_vol
            FROM daily_screen WHERE datum IN ({ph})
        """, dates).fetchall()
        con.close()

        db_data = {}
        for r in rows:
            if r[0] not in db_data:
                db_data[r[0]] = {}
            db_data[r[0]][r[1]] = {
                'kurs': r[2], 'perf_1d': r[3], 'perf_3m': r[4],
                'abst_hoch': r[5], 'sma50': r[6], 'sma200': r[7],
                'golden_cross': r[8], 'phase2': r[9],
                'avg_vol': r[10], 'rel_vol': r[11],
            }

        for w in watchlist:
            orders = analyze_ticker_db(w['ticker'], db_data, dates, max_risk_usd)
            all_orders.extend(orders)
            if orders:
                log(f"  {w['ticker']:6s} — {len(orders)} Orders")

    else:
        # TWS-Modus
        mode = 'live' if args.live else 'paper'
        ib = await connect_tws(mode)
        if not ib:
            log("ERROR: No TWS connection! Use --dry-run for offline mode.")
            sys.exit(1)

        for w in watchlist:
            df = await get_daily_bars(ib, w['ticker'])
            if df is not None:
                orders = analyze_ticker_tws(df, w['ticker'], max_risk_usd)
                all_orders.extend(orders)
                if orders:
                    log(f"  {w['ticker']:6s} — {len(orders)} Orders")
            await asyncio.sleep(0.4)  # IB Pacing

        ib.disconnect()

    buy_count = sum(1 for o in all_orders if o['type'] == 'STOP-BUY')
    sell_count = sum(1 for o in all_orders if o['type'] == 'STOP-SELL')
    log(f"Total: {buy_count} Stop-Buy + {sell_count} Stop-Sell")

    # Excel erstellen
    out_path = args.output or str(SCRIPT_DIR / f'trading_orders_{next_day}.xlsx')
    create_excel(all_orders, watchlist, persistenz, scan_date, next_day, args.risk, out_path)
    log(f"Excel: {out_path}")
    log("=== TWS-Excel-Bridge finished ===")

    return {'excel_path': out_path, 'buy_orders': buy_count, 'sell_orders': sell_count}


def main():
    return asyncio.run(main_async())


if __name__ == '__main__':
    main()
