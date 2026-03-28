#!/usr/bin/env python3
"""
AI Artifakte — Agent B2: Pre-Market Scan
==========================================
Eigenstaendiger Agent fuer den Pre-Market Scan nach Ollis Methodik.
Erkennt die 5 Setup-Typen und kombiniert sie mit der Persistenzmatrix.

Setup-Hierarchie (nach Olli):
  1. Shakeouts (UC, MAUR) — Bestes CRV
  2. Kontraktion unter Widerstand — Ideal fuer Berufstaetige
  3. Keilausbruch — Drittbestes, hoehere Einstiegskosten
  4. Failed Breakdown — Opportunistisch

Aufruf:
  python3 agent_premarket_scan.py                          # Standard
  python3 agent_premarket_scan.py --date 2026-03-27        # Bestimmtes Datum
  python3 agent_premarket_scan.py --db /pfad/zur/db        # Andere DB
  python3 agent_premarket_scan.py --json                   # JSON exportieren
  python3 agent_premarket_scan.py --top 30                 # Top N anzeigen
"""

import sqlite3
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


# ==============================================================
# KONFIGURATION
# ==============================================================
# Liquiditaetsfilter (2-von-3 Regel)
SCREEN_MIN_PRICE = 20
SCREEN_MIN_VOLUME = 500_000
SCREEN_MIN_DOLLAR_VOL = 10_000_000
LIQUIDITY_TOLERANCE = 0.30

# Scoring (11 Kriterien)
SCORE_THRESHOLDS = {11: 8, 10: 7, 9: 7}
MIN_SCORE_TOP = 8

SCORE_NEAR_HIGH_PCT = 25
SCORE_REV_GROWTH_HIGH = 50
SCORE_REV_GROWTH_MED = 20
SCORE_EARN_GROWTH_MIN = 20
SCORE_TECH_SECTORS = ['Technology', 'Communication Services', 'Financial Services']
SCORE_MIN_PERF_3M = 0

# Setup-Erkennung
UC_LOOKBACK = 5              # Tage zurueck fuer Undercut-Erkennung
INSIDE_CANDLE_TOLERANCE = 0.001  # 0.1% Toleranz fuer IC-Erkennung
KONTRAKTION_MIN_DAYS = 2     # Min. Tage enger werdend
EMA_BOUNCE_PCT = 1.5         # Max % Abstand zum MA fuer Bounce
BULL_SNORT_REL_VOL = 3.0     # Ollis Bull-Snort-Schwelle
BULL_SNORT_MIN_GAIN = 3.0    # Min. Tagesgewinn %

# Setup-Gewichtung fuer Ranking
SETUP_WEIGHTS = {
    'UC': 5,           # Undercut — Ollis #1
    'MAUR': 5,         # MA Undercut & Rally — gleichwertig mit UC
    'UC+MAUR': 7,      # Kombination — STAERKSTES Signal
    'KONTRAKTION': 4,  # Kontraktion unter Widerstand
    'INSIDE': 3,       # Inside Candle (Teil der Kontraktion)
    'DOUBLE_INSIDE': 5,  # Double Inside — Ollis Lieblings-Pre-Market-Kauf
    'KEIL': 2,         # Keilausbruch
    'FAILED_BD': 4,    # Failed Breakdown
    'BULL_SNORT': 3,   # Bull Snort (Volumen-Spike)
    'EMA_BOUNCE': 2,   # EMA-Bounce
}

DEFAULT_TOP_N = 25
LOOKBACK_DAYS = 25  # Tage historische Daten fuer Setup-Erkennung

# DB-Suchpfade
DEFAULT_DB_PATHS = [
    Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path.home() / 'Documents' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path(__file__).resolve().parent.parent / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
]


def score_threshold(max_possible):
    return SCORE_THRESHOLDS.get(max_possible, MIN_SCORE_TOP)


def liquidity_check(price, avg_vol):
    if price is None or avg_vol is None:
        return False
    dv = price * avg_vol
    p_ok = price >= SCREEN_MIN_PRICE
    v_ok = avg_vol >= SCREEN_MIN_VOLUME
    dv_ok = dv >= SCREEN_MIN_DOLLAR_VOL
    strict = sum([p_ok, v_ok, dv_ok])
    if strict >= 3:
        return True
    if strict == 2:
        tol = LIQUIDITY_TOLERANCE
        if not p_ok and price >= SCREEN_MIN_PRICE * (1 - tol):
            return True
        if not v_ok and avg_vol >= SCREEN_MIN_VOLUME * (1 - tol):
            return True
        if not dv_ok and dv >= SCREEN_MIN_DOLLAR_VOL * (1 - tol):
            return True
    return False


# ==============================================================
# DB-VERBINDUNG
# ==============================================================
def find_database(explicit_path=None):
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"DB nicht gefunden: {explicit_path}")
    for p in DEFAULT_DB_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError("feiertag_trading.db nicht gefunden.")


def connect_db(db_path):
    db_str = str(db_path)
    for uri_suffix in ['?mode=ro', '?mode=ro&immutable=1', '']:
        try:
            if uri_suffix:
                con = sqlite3.connect(f"file:{db_str}{uri_suffix}", uri=True, timeout=10)
            else:
                con = sqlite3.connect(db_str, timeout=10)
                con.execute("PRAGMA query_only = ON")
            con.execute("SELECT 1")
            return con
        except sqlite3.OperationalError:
            continue
    raise ConnectionError(f"DB-Verbindung fehlgeschlagen: {db_str}")


# ==============================================================
# DATEN LADEN
# ==============================================================
def load_trading_days(con, end_date, num_days):
    rows = con.execute(
        "SELECT DISTINCT datum FROM daily_screen WHERE datum <= ? ORDER BY datum DESC LIMIT ?",
        (end_date, num_days)
    ).fetchall()
    dates = [r[0] for r in rows]
    dates.reverse()
    return dates


def load_raw_data(con, dates):
    if not dates:
        return {}
    ph = ','.join('?' * len(dates))
    rows = con.execute(f"""
        SELECT ticker, datum, kurs, perf_1d, perf_3m,
               abst_hoch, sma50, sma200, golden_cross, phase2,
               ueber_sma50, ueber_sma200, avg_vol, rel_vol
        FROM daily_screen
        WHERE datum IN ({ph})
        ORDER BY ticker, datum
    """, dates).fetchall()

    data = {}
    for r in rows:
        ticker = r[0]
        if ticker not in data:
            data[ticker] = {}
        data[ticker][r[1]] = {
            'kurs': r[2], 'perf_1d': r[3], 'perf_3m': r[4],
            'abst_hoch': r[5], 'sma50': r[6], 'sma200': r[7],
            'golden_cross': r[8], 'phase2': r[9],
            'ueber_sma50': r[10], 'ueber_sma200': r[11],
            'avg_vol': r[12], 'rel_vol': r[13],
        }
    return data


def load_fundamentals(con):
    try:
        rows = con.execute("""
            SELECT sym,
                   MAX(CASE WHEN rev_wachstum != 0 THEN rev_wachstum END) AS rev_g,
                   MAX(CASE WHEN net_wachstum != 0 THEN net_wachstum END) AS earn_g
            FROM v_fin_perf_001
            WHERE status = 'reported'
            GROUP BY sym
        """).fetchall()
        return {r[0]: {'rev_growth': r[1], 'earn_growth': r[2]} for r in rows}
    except Exception:
        return {}


def load_sectors(con):
    try:
        rows = con.execute(
            "SELECT std_sym, std_sector FROM t_std_stammdaten WHERE std_sector IS NOT NULL AND std_sector != ''"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def load_earnings_dates(con, from_date, to_date):
    """Lade kommende Earnings-Termine."""
    try:
        rows = con.execute("""
            SELECT ticker, earnings_date FROM t_sym_edt_earningsdate
            WHERE earnings_date BETWEEN ? AND ?
        """, (from_date, to_date)).fetchall()
        result = {}
        for r in rows:
            result[r[0]] = r[1]
        return result
    except Exception:
        return {}


# ==============================================================
# SCORING (identisch mit Agent B1)
# ==============================================================
def score_ticker(raw, fundamentals, sectors, ticker):
    kurs = raw.get('kurs')
    avg_vol = raw.get('avg_vol')
    if not liquidity_check(kurs, avg_vol):
        return None, None

    score = 0
    score_max = 11

    if raw.get('phase2'):
        score += 2
    if raw.get('golden_cross'):
        score += 1

    abst = raw.get('abst_hoch')
    if abst is not None and abs(abst) <= SCORE_NEAR_HIGH_PCT:
        score += 1

    if raw.get('phase2'):
        score += 1
    elif abst is not None and abst > -50:
        score += 1

    fund = fundamentals.get(ticker, {})
    rev_g = fund.get('rev_growth')
    if rev_g is not None:
        rev_pct = rev_g * 100
        if rev_pct >= SCORE_REV_GROWTH_HIGH:
            score += 2
        elif rev_pct >= SCORE_REV_GROWTH_MED:
            score += 1
    else:
        score_max -= 2

    earn_g = fund.get('earn_growth')
    if earn_g is not None:
        if earn_g * 100 >= SCORE_EARN_GROWTH_MIN:
            score += 1
    else:
        score_max -= 1

    score += 1  # K09: Keine Dividende (TODO)

    sector = sectors.get(ticker, '')
    if sector in SCORE_TECH_SECTORS:
        score += 1

    p3m = raw.get('perf_3m')
    if p3m is not None and p3m > SCORE_MIN_PERF_3M:
        score += 1

    return score, score_max


# ==============================================================
# SETUP-ERKENNUNG
# ==============================================================
def detect_setups(ticker, days_data, dates, fundamentals, sectors):
    """Erkenne alle aktiven Setups fuer einen Ticker.

    Gibt Liste von Setup-Dicts zurueck, sortiert nach Prioritaet.
    """
    if len(dates) < 5:
        return []

    setups = []
    recent_dates = dates[-UC_LOOKBACK:]
    latest_date = dates[-1]
    latest = days_data.get(latest_date)
    if not latest:
        return []

    kurs = latest.get('kurs')
    if kurs is None:
        return []

    # Vorfilter: Liquiditaet
    if not liquidity_check(kurs, latest.get('avg_vol')):
        return []

    # Score berechnen
    s, mx = score_ticker(latest, fundamentals, sectors, ticker)
    if s is None:
        return []

    # Nur qualifizierte Ticker (Score >= Schwelle)
    if s < score_threshold(mx):
        # Auch knapp darunter noch mit aufnehmen fuer Setup-Erkennung
        if s < score_threshold(mx) - 1:
            return []

    # --- Hilfsdaten aufbereiten ---
    prices = []  # [(date, kurs, perf_1d, sma50, sma200, phase2, rel_vol, avg_vol)]
    for d in dates:
        dd = days_data.get(d)
        if dd and dd.get('kurs') is not None:
            prices.append({
                'date': d,
                'kurs': dd['kurs'],
                'perf_1d': dd.get('perf_1d', 0) or 0,
                'sma50': dd.get('sma50'),
                'sma200': dd.get('sma200'),
                'phase2': dd.get('phase2', 0),
                'golden_cross': dd.get('golden_cross', 0),
                'abst_hoch': dd.get('abst_hoch'),
                'rel_vol': dd.get('rel_vol', 1) or 1,
                'avg_vol': dd.get('avg_vol', 0) or 0,
            })

    if len(prices) < 5:
        return []

    # Letzte 2-3 Tage fuer Setup-Erkennung
    p = prices  # Kurzname
    last = p[-1]
    prev = p[-2] if len(p) >= 2 else None
    prev2 = p[-3] if len(p) >= 3 else None

    # === SETUP 1: Undercut (UC) ===
    # Pruefe ob in den letzten Tagen ein markantes Tief unterschritten
    # und dann zurueckerobert wurde
    if len(p) >= 8:
        # Finde lokale Tiefs in den letzten 10-20 Tagen
        lookback = min(20, len(p) - 3)
        for i in range(len(p) - lookback, len(p) - 2):
            if i < 1:
                continue
            # Lokales Tief: tiefer als Vorgaenger und Nachfolger
            if p[i]['kurs'] < p[i-1]['kurs'] and p[i]['kurs'] < p[i+1]['kurs']:
                low_level = p[i]['kurs']
                # Wurde in den letzten 3 Tagen unterschritten?
                for j in range(max(len(p)-4, i+1), len(p)):
                    if p[j]['kurs'] < low_level * 0.995:  # Undercut mit 0.5% Toleranz
                        # Zurueckerobert am letzten oder vorletzten Tag?
                        if last['kurs'] > low_level:
                            risk_pct = round((last['kurs'] - p[j]['kurs']) / last['kurs'] * 100, 1)
                            setups.append({
                                'type': 'UC',
                                'weight': SETUP_WEIGHTS['UC'],
                                'desc': f'UC {low_level:.2f} (Tief {p[i]["date"][5:]})',
                                'risk_pct': risk_pct,
                                'ref_date': p[j]['date'],
                            })
                        break

    # === SETUP 2: MAUR (MA Undercut & Rally) ===
    if prev and last.get('sma50') and last.get('sma200'):
        for ma_name, ma_key in [('EMA20', 'sma50'), ('SMA50', 'sma50'), ('SMA200', 'sma200')]:
            ma_val = last.get(ma_key)
            if ma_val is None or ma_val == 0:
                continue
            prev_ma = prev.get(ma_key)
            if prev_ma is None:
                continue

            # Gestern unter MA geschlossen, heute darueber
            if prev['kurs'] < prev_ma and last['kurs'] > ma_val:
                # Nur im Aufwaertstrend (Phase2 oder Golden Cross)
                if last.get('phase2') or last.get('golden_cross'):
                    risk_pct = round(abs(last['kurs'] - prev['kurs']) / last['kurs'] * 100, 1)
                    weight = SETUP_WEIGHTS['MAUR']
                    # Kombination UC+MAUR ist staerker
                    if any(s['type'] == 'UC' for s in setups):
                        weight = SETUP_WEIGHTS['UC+MAUR']
                        setups.append({
                            'type': 'UC+MAUR',
                            'weight': weight,
                            'desc': f'UC+MAUR am {ma_name}',
                            'risk_pct': risk_pct,
                        })
                    else:
                        setups.append({
                            'type': 'MAUR',
                            'weight': weight,
                            'desc': f'MAUR am {ma_name}',
                            'risk_pct': risk_pct,
                        })
                    break  # Nur staerkstes MAUR-Signal

    # === SETUP 3: Kontraktion unter Widerstand / Inside Candles ===
    if prev:
        # Inside Candle: Range von heute komplett innerhalb gestern
        # (nutze perf_1d als Proxy fuer Range-Enge)
        last_range = abs(last['perf_1d']) if last['perf_1d'] else 0
        prev_range = abs(prev['perf_1d']) if prev['perf_1d'] else 0

        # Engere Definition: Kurs nah am Vortag (wenig Bewegung)
        if last_range < 1.5 and prev_range > last_range:
            # Kontraktion: letzte 2-3 Tage werden enger
            is_contracting = True
            if prev2:
                prev2_range = abs(prev2['perf_1d']) if prev2['perf_1d'] else 0
                if prev_range > prev2_range:  # Nicht wirklich enger werdend
                    is_contracting = False

            # Nahe an einem Widerstand (52W-Hoch)?
            abst_hoch = last.get('abst_hoch')
            near_resistance = abst_hoch is not None and abs(abst_hoch) < 15

            if is_contracting and near_resistance:
                setups.append({
                    'type': 'KONTRAKTION',
                    'weight': SETUP_WEIGHTS['KONTRAKTION'],
                    'desc': f'Kontraktion nahe Hoch ({abst_hoch:.0f}%)',
                    'risk_pct': round(last_range + 0.5, 1),
                })

        # Inside Candle explizit
        if last_range < 1.0 and prev_range >= 1.0:
            setups.append({
                'type': 'INSIDE',
                'weight': SETUP_WEIGHTS['INSIDE'],
                'desc': f'Inside Candle ({last_range:.1f}% Range)',
                'risk_pct': round(last_range + 0.3, 1),
            })

            # Double Inside?
            if prev2 and prev_range < 1.5:
                prev2_range = abs(prev2['perf_1d']) if prev2['perf_1d'] else 0
                if prev2_range > prev_range:
                    setups.append({
                        'type': 'DOUBLE_INSIDE',
                        'weight': SETUP_WEIGHTS['DOUBLE_INSIDE'],
                        'desc': 'Double Inside — Ollis Lieblings-Pre-Market-Kauf!',
                        'risk_pct': round(last_range + 0.2, 1),
                    })

    # === SETUP 4: Keilausbruch ===
    # Kurs bricht aus enger Range nach oben aus
    if prev and prev2 and last['perf_1d'] and last['perf_1d'] > 1.5:
        prev_range = abs(prev['perf_1d']) if prev['perf_1d'] else 99
        prev2_range = abs(prev2['perf_1d']) if prev2['perf_1d'] else 99
        # Vortage waren eng, heute Ausbruch
        if prev_range < 1.5 and prev2_range < 2.0:
            if last.get('phase2') or last.get('golden_cross'):
                setups.append({
                    'type': 'KEIL',
                    'weight': SETUP_WEIGHTS['KEIL'],
                    'desc': f'Keilausbruch +{last["perf_1d"]:.1f}%',
                    'risk_pct': round(last['perf_1d'] + 0.5, 1),
                })

    # === SETUP 5: Failed Breakdown ===
    # Starker Abverkauf wird sofort aufgekauft
    if prev and prev2:
        if prev['perf_1d'] and prev['perf_1d'] < -2.0:
            # Gestern stark gefallen
            if last['perf_1d'] and last['perf_1d'] > 1.5:
                # Heute stark erholt
                if last.get('phase2') or last.get('golden_cross'):
                    setups.append({
                        'type': 'FAILED_BD',
                        'weight': SETUP_WEIGHTS['FAILED_BD'],
                        'desc': f'Failed Breakdown ({prev["perf_1d"]:.1f}% to +{last["perf_1d"]:.1f}%)',
                        'risk_pct': round(abs(prev['perf_1d']), 1),
                    })

    # === BULL SNORT ===
    if last['rel_vol'] and last['rel_vol'] >= BULL_SNORT_REL_VOL:
        if last['perf_1d'] and last['perf_1d'] >= BULL_SNORT_MIN_GAIN:
            setups.append({
                'type': 'BULL_SNORT',
                'weight': SETUP_WEIGHTS['BULL_SNORT'],
                'desc': f'Bull Snort! +{last["perf_1d"]:.1f}% bei {last["rel_vol"]:.1f}x Vol',
                'risk_pct': round(last['perf_1d'] * 0.5, 1),
            })

    # === EMA-BOUNCE ===
    # Kurs nah am SMA50 oder SMA200, mit Phase2/GC aktiv
    if last.get('sma50') and last['sma50'] > 0:
        dist_sma50 = abs(last['kurs'] - last['sma50']) / last['sma50'] * 100
        if dist_sma50 < EMA_BOUNCE_PCT and last.get('phase2'):
            setups.append({
                'type': 'EMA_BOUNCE',
                'weight': SETUP_WEIGHTS['EMA_BOUNCE'],
                'desc': f'SMA50 Bounce ({dist_sma50:.1f}% entfernt)',
                'risk_pct': round(dist_sma50 + 1.0, 1),
            })

    return setups


# ==============================================================
# SCAN-RANKING
# ==============================================================
def rank_candidates(candidates, persistenz_data=None):
    """Ranke Kandidaten nach Setup-Qualitaet + Persistenz."""
    for c in candidates:
        # Setup-Score: Summe der Setup-Gewichte
        setup_score = sum(s['weight'] for s in c['setups'])
        # Bestes einzelnes Setup
        best_setup = max(c['setups'], key=lambda s: s['weight'])
        c['best_setup'] = best_setup
        c['setup_score'] = setup_score
        c['num_setups'] = len(c['setups'])

        # Persistenz-Bonus
        pers_bonus = 0
        if persistenz_data and c['ticker'] in persistenz_data:
            pd = persistenz_data[c['ticker']]
            pers_bonus = pd.get('avg_score', 0) * 2 + pd.get('persistence_pct', 0) * 0.1

        # Gesamtranking: 50% Setup-Qualitaet + 30% Score + 20% Persistenz
        score_ratio = c['score'] / max(c['score_max'], 1) * 10
        c['rank'] = round(setup_score * 0.50 + score_ratio * 0.30 + pers_bonus * 0.20, 1)

    candidates.sort(key=lambda c: -c['rank'])
    return candidates


# ==============================================================
# HTML-REPORT
# ==============================================================
def generate_html(candidates, scan_date, next_trading_day, dates_used, persistenz_data=None, earnings_soon=None):
    """Generiere interaktiven HTML-Report."""

    setup_colors = {
        'UC': '#e94560', 'MAUR': '#e94560', 'UC+MAUR': '#ff6348',
        'KONTRAKTION': '#ffeaa7', 'INSIDE': '#fdcb6e', 'DOUBLE_INSIDE': '#f9ca24',
        'KEIL': '#74b9ff', 'FAILED_BD': '#a29bfe', 'BULL_SNORT': '#ff7979',
        'EMA_BOUNCE': '#7bed9f',
    }

    setup_emojis = {
        'UC': 'down', 'MAUR': 'recycle', 'UC+MAUR': 'fire',
        'KONTRAKTION': 'square', 'INSIDE': 'package', 'DOUBLE_INSIDE': 'packages',
        'KEIL': 'wedge', 'FAILED_BD': 'boom', 'BULL_SNORT': 'bull',
        'EMA_BOUNCE': 'rewind',
    }

    html = []
    html.append('<!DOCTYPE html>')
    html.append('<html lang="de"><head><meta charset="utf-8">')
    html.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    html.append(f'<title>Pre-Market Scan — {next_trading_day}</title>')
    html.append("""<style>
:root {
  --bg: #0f0f1a; --surface: #1a1a2e; --surface2: #16213e;
  --text: #e8e8f0; --dim: #636e72; --accent: #e94560;
  --green: #00b894; --green2: #00cec9; --yellow: #ffeaa7;
  --orange: #fdcb6e; --red: #d63031; --blue: #74b9ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  background: var(--bg); color: var(--text);
  padding: 20px; font-size: 12px; line-height: 1.5;
  max-width: 1200px; margin: 0 auto;
}
h1 { color: var(--accent); font-size: 20px; margin-bottom: 4px; }
h2 { color: var(--blue); font-size: 15px; margin: 20px 0 10px; border-bottom: 1px solid #333; padding-bottom: 4px; }
.meta { color: var(--dim); margin-bottom: 16px; font-size: 11px; }
.stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.stat-card {
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 6px; padding: 10px 14px; min-width: 110px;
}
.stat-card .label { color: var(--dim); font-size: 10px; text-transform: uppercase; }
.stat-card .value { font-size: 22px; font-weight: bold; color: var(--green); }
.legend { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.legend-item {
  display: flex; align-items: center; gap: 4px; font-size: 11px;
}
.legend-dot {
  width: 10px; height: 10px; border-radius: 2px; display: inline-block;
}
.candidate {
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 8px; padding: 14px 18px; margin-bottom: 10px;
  transition: border-color 0.2s;
}
.candidate:hover { border-color: var(--accent); }
.candidate-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.ticker-name {
  font-size: 16px; font-weight: bold; color: var(--blue);
}
.score-badge {
  background: var(--green); color: #000; font-weight: bold;
  padding: 2px 8px; border-radius: 4px; font-size: 12px;
}
.score-badge.mid { background: var(--green2); }
.score-badge.low { background: var(--orange); }
.candidate-meta {
  display: flex; gap: 16px; flex-wrap: wrap; font-size: 11px;
  color: var(--dim); margin-bottom: 8px;
}
.candidate-meta span { white-space: nowrap; }
.setups { display: flex; gap: 6px; flex-wrap: wrap; }
.setup-tag {
  display: inline-block; padding: 3px 8px; border-radius: 4px;
  font-size: 10px; font-weight: bold; color: #000;
}
.setup-desc { font-size: 11px; color: var(--text); margin-top: 6px; line-height: 1.6; }
.risk-label { color: var(--orange); font-size: 10px; }
.earnings-warn {
  background: #5e1a1a; color: #ff7675; padding: 2px 6px;
  border-radius: 3px; font-size: 10px; font-weight: bold;
}
.pers-info { color: var(--green2); font-size: 10px; }
.rank-badge {
  background: var(--surface2); color: var(--accent);
  font-size: 11px; font-weight: bold; padding: 2px 6px;
  border-radius: 3px; margin-right: 8px;
}
.filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.filters label { color: var(--dim); font-size: 11px; }
.filters select, .filters input {
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 4px; padding: 4px 8px; font-size: 11px; font-family: inherit;
}
.hidden { display: none; }
</style></head><body>""")

    html.append(f'<h1>Pre-Market Scan — Monday {next_trading_day}</h1>')
    html.append(f'<div class="meta">Base data: {scan_date} (last trading day) | {len(dates_used)} days analyzed | {len(candidates)} candidates | Agent B2 v1.0</div>')

    # Stats
    n_total = len(candidates)
    n_uc = sum(1 for c in candidates if any(s['type'] in ('UC', 'UC+MAUR', 'MAUR') for s in c['setups']))
    n_kontr = sum(1 for c in candidates if any(s['type'] in ('KONTRAKTION', 'INSIDE', 'DOUBLE_INSIDE') for s in c['setups']))
    n_p2 = sum(1 for c in candidates if c.get('phase2'))
    avg_score = round(sum(c['score'] for c in candidates) / n_total, 1) if n_total else 0

    html.append('<div class="stats">')
    html.append(f'<div class="stat-card"><div class="label">Candidates</div><div class="value">{n_total}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">UC/MAUR</div><div class="value" style="color:var(--accent)">{n_uc}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">Contraction</div><div class="value" style="color:var(--yellow)">{n_kontr}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">Phase 2</div><div class="value">{n_p2}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">Avg Score</div><div class="value">{avg_score}</div></div>')
    html.append('</div>')

    # Legende
    html.append('<div class="legend">')
    for stype, color in sorted(setup_colors.items(), key=lambda x: -SETUP_WEIGHTS.get(x[0], 0)):
        html.append(f'<div class="legend-item"><span class="legend-dot" style="background:{color}"></span>{stype} (Wt {SETUP_WEIGHTS.get(stype, 0)})</div>')
    html.append('</div>')

    # Filter
    html.append('''<div class="filters">
      <label>Filter:</label>
      <select id="filterSetup" onchange="applyFilter()">
        <option value="all">All Setups</option>
        <option value="UC">UC / MAUR</option>
        <option value="KONTR">Contraction / Inside</option>
        <option value="KEIL">Wedge / Breakout</option>
      </select>
      <input type="text" id="filterTicker" placeholder="Ticker..." oninput="applyFilter()" style="width:100px;">
    </div>''')

    # Kandidaten
    html.append('<div id="candidates">')

    for idx, c in enumerate(candidates):
        setup_types = ','.join(s['type'] for s in c['setups'])
        setup_cat = 'UC' if any(t in setup_types for t in ['UC', 'MAUR']) else ('KONTR' if any(t in setup_types for t in ['KONTRAKTION', 'INSIDE', 'DOUBLE_INSIDE']) else 'KEIL')

        score_cls = '' if c['score'] >= 9 else ('mid' if c['score'] >= 8 else 'low')

        # Persistenz-Info
        pers_str = ''
        if persistenz_data and c['ticker'] in persistenz_data:
            pd = persistenz_data[c['ticker']]
            pers_str = f'<span class="pers-info">P:{pd.get("persistence_pct", 0)}% | Avg:{pd.get("avg_score", 0):.1f}</span>'

        # Earnings-Warnung
        earn_str = ''
        if earnings_soon and c['ticker'] in earnings_soon:
            earn_str = f'<span class="earnings-warn">EARNINGS {earnings_soon[c["ticker"]]}</span>'

        html.append(f'<div class="candidate" data-setup="{setup_cat}" data-ticker="{c["ticker"]}">')
        html.append(f'<div class="candidate-header">')
        html.append(f'<div><span class="rank-badge">#{idx+1}</span><span class="ticker-name">{c["ticker"]}</span> {earn_str}</div>')
        html.append(f'<span class="score-badge {score_cls}">{c["score"]}/{c["score_max"]}</span>')
        html.append('</div>')

        # Meta
        phase_str = 'Phase2' if c.get('phase2') else ('GC' if c.get('golden_cross') else '-')
        kurs_str = f'${c["kurs"]:.2f}' if c.get('kurs') else '-'
        abst_str = f'{c["abst_hoch"]:.0f}%' if c.get('abst_hoch') is not None else '-'
        sector = c.get('sector', '-')

        html.append(f'<div class="candidate-meta">')
        html.append(f'<span>Price: {kurs_str}</span>')
        html.append(f'<span>v52High: {abst_str}</span>')
        html.append(f'<span>{phase_str}</span>')
        html.append(f'<span>{sector}</span>')
        html.append(f'<span>{c["num_setups"]} Setups</span>')
        html.append(f'{pers_str}')
        html.append('</div>')

        # Setups
        html.append('<div class="setups">')
        for s in sorted(c['setups'], key=lambda x: -x['weight']):
            color = setup_colors.get(s['type'], '#555')
            html.append(f'<span class="setup-tag" style="background:{color}">{s["type"]}</span>')
        html.append('</div>')

        # Setup-Beschreibungen
        html.append('<div class="setup-desc">')
        for s in sorted(c['setups'], key=lambda x: -x['weight']):
            risk = f' <span class="risk-label">Risk: ~{s["risk_pct"]}%</span>' if s.get('risk_pct') else ''
            html.append(f'<b>{s["type"]}:</b> {s["desc"]}{risk}<br>')
        html.append('</div>')
        html.append('</div>')

    html.append('</div>')

    # JavaScript Filter
    html.append("""<script>
function applyFilter() {
  const setup = document.getElementById('filterSetup').value;
  const search = document.getElementById('filterTicker').value.toUpperCase();
  document.querySelectorAll('.candidate').forEach(c => {
    let show = true;
    if (setup !== 'all' && c.dataset.setup !== setup) show = false;
    if (search && !c.dataset.ticker.includes(search)) show = false;
    c.style.display = show ? '' : 'none';
  });
}
</script>""")

    html.append(f'<div class="meta" style="margin-top:16px;">AI Artifakte — Agent B2 Pre-Market Scan v1.0 | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    html.append('</body></html>')
    return '\n'.join(html)


# ==============================================================
# HAUPTPROGRAMM
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='AI Artifakte — Agent B2: Pre-Market Scan')
    parser.add_argument('--date', default=None, help='Enddatum (letzter Handelstag)')
    parser.add_argument('--db', help='Pfad zur feiertag_trading.db')
    parser.add_argument('--output', help='Output-Verzeichnis')
    parser.add_argument('--json', action='store_true', help='JSON exportieren')
    parser.add_argument('--top', type=int, default=DEFAULT_TOP_N, help='Top N Kandidaten')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    def log(msg):
        if not args.quiet:
            print(f"  [B2] {msg}", flush=True)

    log("=== Pre-Market Scan started ===")

    # DB verbinden
    try:
        db_path = find_database(args.db)
        log(f"DB: {db_path}")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        con = connect_db(db_path)
        log("DB connection OK")
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Datum bestimmen
    if args.date:
        scan_date = args.date
    else:
        # Letzter verfuegbarer Handelstag
        row = con.execute("SELECT MAX(datum) FROM daily_screen").fetchone()
        scan_date = row[0] if row and row[0] else date.today().isoformat()

    # Naechster Handelstag
    sd = datetime.strptime(scan_date, '%Y-%m-%d').date()
    next_day = sd + timedelta(days=1)
    while next_day.weekday() >= 5:  # Wochenende ueberspringen
        next_day += timedelta(days=1)

    log(f"Base date: {scan_date} | Next trading day: {next_day}")

    # Daten laden
    dates = load_trading_days(con, scan_date, LOOKBACK_DAYS)
    if not dates:
        log("ERROR: No data")
        sys.exit(1)
    log(f"Period: {dates[0]} to {dates[-1]} ({len(dates)} days)")

    log("Loading raw data...")
    raw_data = load_raw_data(con, dates)
    log(f"Raw data: {len(raw_data)} tickers")

    log("Loading fundamentals...")
    fundamentals = load_fundamentals(con)
    log(f"Fundamentals: {len(fundamentals)} tickers")

    log("Loading sectors...")
    sectors = load_sectors(con)
    log(f"Sectors: {len(sectors)} tickers")

    # Earnings-Termine naechste 5 Tage
    earn_from = next_day.isoformat()
    earn_to = (next_day + timedelta(days=5)).isoformat()
    earnings_soon = load_earnings_dates(con, earn_from, earn_to)
    log(f"Earnings next week: {len(earnings_soon)} tickers")

    con.close()

    # Persistenzmatrix laden (falls vorhanden)
    persistenz_data = {}
    json_path = Path(__file__).resolve().parent / 'persistenzmatrix.json'
    if json_path.exists():
        try:
            with open(json_path) as f:
                pj = json.load(f)
            persistenz_data = pj.get('tickers', {})
            log(f"Persistenz matrix loaded: {len(persistenz_data)} tickers")
        except Exception:
            log("WARN: Persistenz matrix not loadable")

    # Setup-Erkennung
    log("Scanning setups...")
    candidates = []
    for ticker, t_data in raw_data.items():
        setups = detect_setups(ticker, t_data, dates, fundamentals, sectors)
        if not setups:
            continue

        latest = t_data.get(dates[-1])
        if not latest:
            continue

        s, mx = score_ticker(latest, fundamentals, sectors, ticker)
        if s is None:
            continue

        candidates.append({
            'ticker': ticker,
            'setups': setups,
            'score': s,
            'score_max': mx,
            'kurs': latest.get('kurs'),
            'phase2': latest.get('phase2'),
            'golden_cross': latest.get('golden_cross'),
            'abst_hoch': latest.get('abst_hoch'),
            'perf_1d': latest.get('perf_1d'),
            'perf_3m': latest.get('perf_3m'),
            'rel_vol': latest.get('rel_vol'),
            'sector': sectors.get(ticker, ''),
        })

    log(f"Candidates with setups: {len(candidates)}")

    # Ranking
    candidates = rank_candidates(candidates, persistenz_data)

    # Top N
    top = candidates[:args.top]
    log(f"Top {len(top)} candidates:")

    # Konsolen-Output
    for i, c in enumerate(top[:10]):
        setup_str = ' + '.join(s['type'] for s in sorted(c['setups'], key=lambda x: -x['weight']))
        pers_str = ''
        if c['ticker'] in persistenz_data:
            pd = persistenz_data[c['ticker']]
            pers_str = f" | P:{pd.get('persistence_pct', 0)}% Avg:{pd.get('avg_score', 0):.1f}"
        log(f"  #{i+1} {c['ticker']:6s} {c['score']}/{c['score_max']} | {setup_str}{pers_str}")

    # Output generieren
    out_dir = Path(args.output) if args.output else Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)

    html_content = generate_html(top, scan_date, next_day.isoformat(), dates, persistenz_data, earnings_soon)
    html_path = out_dir / 'premarket_scan.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    log(f"HTML: {html_path}")

    if args.json:
        json_out = {
            'generated': datetime.now().isoformat(),
            'scan_date': scan_date,
            'next_trading_day': next_day.isoformat(),
            'num_candidates': len(top),
            'candidates': []
        }
        for c in top:
            json_out['candidates'].append({
                'ticker': c['ticker'],
                'rank': c['rank'],
                'score': c['score'],
                'score_max': c['score_max'],
                'kurs': c['kurs'],
                'phase2': bool(c.get('phase2')),
                'sector': c.get('sector', ''),
                'setups': [{'type': s['type'], 'desc': s['desc'], 'risk_pct': s.get('risk_pct')} for s in c['setups']],
                'persistenz': persistenz_data.get(c['ticker'], {}),
            })
        json_path = out_dir / 'premarket_scan.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_out, f, indent=2, ensure_ascii=False)
        log(f"JSON: {json_path}")

    log("=== Pre-Market Scan finished ===")
    return {'html_path': str(html_path), 'num_candidates': len(top)}


if __name__ == '__main__':
    main()
