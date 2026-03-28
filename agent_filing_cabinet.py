#!/usr/bin/env python3
"""
AI Artifakte — SEC Filing Cabinet
===================================
Generiert eine interaktive HTML-Seite mit dem kompletten SEC-Ticker-Universum.
Zeigt den Filterweg (Trichter) und Filing-Status (10-Q/10-K) pro Ticker.

USAGE:
  python3 agent_filing_cabinet.py                    # Standard
  python3 agent_filing_cabinet.py --output /tmp       # Anderes Verzeichnis
  python3 agent_filing_cabinet.py --no-sec-db         # Ohne SEC Filing DB

Dann: filing_cabinet.html im Browser oeffnen
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path

from calc_weighted_growth import calc_weighted_growth, calc_market_cap_sec

# ==============================================================
# KONFIGURATION
# ==============================================================
# FAATMAN + NVDA (Mega-Caps, immer sichtbar)
# FAATMAN + NVDA: Reihenfolge: F-A-A-T-M-A-N = META, AAPL, AMZN, TSLA, MSFT, GOOGL, NFLX + NVDA
FAATMAN_NVDA = ['META', 'AAPL', 'AMZN', 'TSLA', 'MSFT', 'GOOGL', 'NFLX', 'NVDA']

# SIC → Sektor-Mapping (392 SIC Descriptions → ~15 Sektoren)
SIC_SECTOR_MAP = {
    'Technology': [
        'Prepackaged Software', 'Computer Programming', 'Computer Processing',
        'Computer Integrated Systems', 'Computer Peripheral Equipment',
        'Electronic Computers', 'Computer Storage Devices', 'Computer Communications',
        'Computer Terminals', 'Computer Rental & Leasing', 'Information Retrieval',
        'Data Processing', 'Software', 'IT ', 'Technology',
    ],
    'Semiconductors': [
        'Semiconductor', 'Printed Circuit',
    ],
    'Healthcare': [
        'Pharmaceutical', 'Biological Products', 'Surgical', 'Medical',
        'Electromedical', 'Dental', 'Health Services', 'Hospital',
        'Diagnostic', 'Orthopedic', 'Nursing', 'In Vitro',
    ],
    'Biotech': [
        'Biotechnology', 'Medicinal', 'Pharmaceutical Preparations',
    ],
    'Finance': [
        'Bank', 'National Commercial', 'State Commercial', 'Savings Institution',
        'Finance', 'Investment', 'Insurance', 'Commodity Contracts', 'Security',
        'Loan Brokers', 'Short-Term Business Credit', 'Functions Related',
        'Real Estate Investment', 'Blank Checks', 'Trust',
    ],
    'Energy': [
        'Crude Petroleum', 'Natural Gas', 'Petroleum Refining', 'Oil',
        'Pipeline', 'Electric Services', 'Gas & Electric', 'Coal',
        'Energy', 'Solar',
    ],
    'Retail': [
        'Retail', 'Eating Places', 'Catalog & Mail-Order', 'Department Store',
        'Grocery', 'Variety Store', 'Drug Store', 'Apparel & Accessory',
    ],
    'Industrial': [
        'Industrial Machinery', 'General Industrial', 'Metalworking',
        'Special Industry Machinery', 'Farm Machinery', 'Construction',
        'Electrical Machinery', 'Motor Vehicle', 'Aircraft', 'Aerospace',
        'Defense', 'Ship Building', 'Railroad',
    ],
    'Telecom': [
        'Telephone', 'Radio', 'Television', 'Cable', 'Wireless',
        'Communication', 'Broadcast',
    ],
    'Consumer': [
        'Household', 'Soap', 'Perfume', 'Footwear', 'Apparel',
        'Food', 'Beverage', 'Tobacco', 'Consumer',
    ],
    'Materials': [
        'Gold', 'Silver', 'Metal Mining', 'Mining', 'Chemical',
        'Steel', 'Iron', 'Aluminum', 'Copper', 'Lumber',
        'Paper', 'Glass', 'Cement', 'Plastics',
    ],
    'Real Estate': [
        'Real Estate', 'Operators of Apartment',
    ],
    'Transportation': [
        'Air Transportation', 'Deep Sea', 'Trucking', 'Services-Misc',
        'Transportation', 'Freight', 'Courier', 'Arrangement Of',
    ],
    'Education': [
        'Educational',
    ],
    'Services': [],  # Auffang-Sektor
}


def sic_to_sector(sic_desc):
    """Ordne eine SIC-Beschreibung einem Sektor zu."""
    if not sic_desc:
        return 'Other'
    for sector, keywords in SIC_SECTOR_MAP.items():
        for kw in keywords:
            if kw.lower() in sic_desc.lower():
                return sector
    # Fallback: "Services-..." → Services
    if sic_desc.startswith('Services-'):
        return 'Services'
    return 'Other'
SCRIPT_DIR = Path(__file__).resolve().parent

DB_SEARCH_PATHS = [
    Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path.home() / 'Documents' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    SCRIPT_DIR.parent / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
]

SEC_DB_SEARCH_PATHS = [
    Path.home() / 'Documents' / 'SEC filing' / 'sec_data.db',
    SCRIPT_DIR.parent / 'SEC filing' / 'sec_data.db',
]

# Quartale fuer Filing-Status (letzten 8)
DISPLAY_QUARTERS = [
    '2024-Q1', '2024-Q2', '2024-Q3', '2024-Q4',
    '2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4',
]


# ==============================================================
# DB-VERBINDUNG
# ==============================================================
def find_db(paths):
    for p in paths:
        if p.exists():
            return p
    return None


def connect_ro(db_path):
    db_str = str(db_path)
    for uri_suffix in ['?mode=ro', '?mode=ro&immutable=1', '']:
        try:
            if uri_suffix:
                con = sqlite3.connect(f"file:{db_str}{uri_suffix}", uri=True, timeout=10)
            else:
                con = sqlite3.connect(db_str, timeout=10)
                con.execute("PRAGMA query_only = ON")
            con.execute("SELECT 1")
            con.row_factory = sqlite3.Row
            return con
        except sqlite3.OperationalError:
            continue
    return None


# ==============================================================
# DATEN SAMMELN
# ==============================================================
def load_trichter(ft_con, sec_con):
    """Berechne den Trichter: SEC gesamt → Universum → aktiv."""
    cur = ft_con.cursor()

    trichter = {}

    # SEC DB Zahlen
    if sec_con:
        sc = sec_con.cursor()
        # SEC company_tickers.json: 10.447 Eintraege (verifiziert 28.03.2026)
        # Enthaelt Duplikate durch Aktienklassen (z.B. BRK-A/BRK-B = gleiche Firma, 2 Eintraege)
        trichter['sec_registriert'] = 10447
        # Unsere DB (dedupliziert nach CIK → ein Eintrag pro Firma)
        trichter['sec_db'] = sc.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        trichter['sec_duplikate'] = trichter['sec_registriert'] - trichter['sec_db']
        # Mit XBRL-Finanzdaten (maschinenlesbare 10-Q/10-K)
        trichter['sec_has_facts'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1"
        ).fetchone()[0]
        trichter['sec_no_facts'] = trichter['sec_db'] - trichter['sec_has_facts']
        # Aufschluesselung der 5.732 nach Boerse
        trichter['facts_nasdaq'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange = 'Nasdaq'"
        ).fetchone()[0]
        trichter['facts_nyse'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange = 'NYSE'"
        ).fetchone()[0]
        trichter['facts_otc'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange = 'OTC'"
        ).fetchone()[0]
        trichter['facts_cboe'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange = 'CBOE'"
        ).fetchone()[0]
        trichter['facts_no_exch'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange IS NULL"
        ).fetchone()[0]
        trichter['facts_listed'] = trichter['facts_nasdaq'] + trichter['facts_nyse']
        trichter['facts_excluded'] = trichter['sec_has_facts'] - trichter['facts_listed']
    else:
        trichter['sec_db'] = 0
        trichter['sec_registriert'] = 0
        trichter['sec_has_facts'] = 0
        trichter['sec_no_facts'] = 0
        trichter['facts_listed'] = 0
        trichter['facts_excluded'] = 0

    # Trading DB Zahlen
    trichter['stammdaten'] = cur.execute("SELECT COUNT(*) FROM t_std_stammdaten").fetchone()[0]

    # fin_type Verteilung
    fin_types = {}
    for r in cur.execute("SELECT std_fin_type, COUNT(*) FROM t_std_stammdaten GROUP BY std_fin_type ORDER BY COUNT(*) DESC"):
        fin_types[r[0] or 'NULL'] = r[1]
    trichter['fin_types'] = fin_types

    trichter['warrants'] = fin_types.get('warrant', 0)
    trichter['no_data'] = fin_types.get('no_data', 0)
    trichter['no_sec'] = fin_types.get('no_sec', 0)
    trichter['tbd'] = fin_types.get('tbd', 0)
    trichter['tradeable'] = trichter['stammdaten'] - trichter['warrants'] - trichter['no_data'] - trichter['no_sec'] - trichter['tbd']

    # Exchange
    exchanges = {}
    for r in cur.execute("SELECT std_exchange, COUNT(*) FROM t_std_stammdaten GROUP BY std_exchange ORDER BY COUNT(*) DESC"):
        exchanges[r[0] or 'NULL'] = r[1]
    trichter['exchanges'] = exchanges

    # --- SEC-Fundamentaldaten-Trichter (nur SEC-Quellen) ---
    # Ticker mit Revenue + Net Income (2025+, kein 'd' Qualifier)
    trichter['rev_net'] = cur.execute("""
        SELECT COUNT(DISTINCT f.fin_sym)
        FROM t_fin_financials f
        JOIN t_qtr_perioden q ON f.fin_qtr = q.qtr_quarter
        WHERE q.qtr_kategorie = 1
        AND f.fin_qtr_net IS NOT NULL AND f.fin_qtr_net != 0
        AND f.fin_qlf_qtr_net != 'd'
        AND f.fin_qtr_rev IS NOT NULL AND f.fin_qtr_rev != 0
        AND f.fin_qlf_qtr_rev != 'd'
    """).fetchone()[0]

    # Davon mit SEC Market-Cap-Daten (Public Float aus 10-K ODER Shares Outstanding SEC DEI)
    trichter['rev_net_mktcap'] = cur.execute("""
        SELECT COUNT(DISTINCT f.fin_sym)
        FROM t_fin_financials f
        JOIN t_qtr_perioden q ON f.fin_qtr = q.qtr_quarter
        WHERE q.qtr_kategorie = 1
        AND f.fin_qtr_net IS NOT NULL AND f.fin_qtr_net != 0
        AND f.fin_qlf_qtr_net != 'd'
        AND f.fin_qtr_rev IS NOT NULL AND f.fin_qtr_rev != 0
        AND f.fin_qlf_qtr_rev != 'd'
        AND f.fin_sym IN (
            SELECT DISTINCT fin_sym FROM t_fin_financials
            WHERE (fin_ann_public_float IS NOT NULL AND fin_ann_public_float > 0)
               OR (fin_qtr_shr_sec IS NOT NULL AND fin_qtr_shr_sec > 0)
        )
    """).fetchone()[0]
    trichter['rev_net_no_mktcap'] = trichter['rev_net'] - trichter['rev_net_mktcap']

    # Daily Screen (Vorfilter: Preis >= $5, avg_vol >= 200K)
    trichter['daily_screen'] = cur.execute("SELECT COUNT(DISTINCT ticker) FROM daily_screen").fetchone()[0]
    trichter['daily_screen_last'] = cur.execute("SELECT MAX(datum) FROM daily_screen").fetchone()[0]

    # Daily Screen Ticker am letzten Tag (= aktuelles Universum nach Vorfilter)
    last_date = trichter['daily_screen_last']
    trichter['daily_screen_today'] = cur.execute(
        "SELECT COUNT(DISTINCT ticker) FROM daily_screen WHERE datum = ?", (last_date,)
    ).fetchone()[0]

    # Schnittmenge: 3.801 die auch im Daily Screen sind
    trichter['screened_with_fundamentals'] = cur.execute("""
        SELECT COUNT(DISTINCT f.fin_sym)
        FROM t_fin_financials f
        JOIN t_qtr_perioden q ON f.fin_qtr = q.qtr_quarter
        WHERE q.qtr_kategorie = 1
        AND f.fin_qtr_net IS NOT NULL AND f.fin_qtr_net != 0
        AND f.fin_qlf_qtr_net != 'd'
        AND f.fin_qtr_rev IS NOT NULL AND f.fin_qtr_rev != 0
        AND f.fin_qlf_qtr_rev != 'd'
        AND f.fin_sym IN (
            SELECT DISTINCT fin_sym FROM t_fin_financials
            WHERE (fin_ann_public_float IS NOT NULL AND fin_ann_public_float > 0)
               OR (fin_qtr_shr_sec IS NOT NULL AND fin_qtr_shr_sec > 0)
        )
        AND f.fin_sym IN (
            SELECT DISTINCT ticker FROM daily_screen WHERE datum = ?
        )
    """, (last_date,)).fetchone()[0]
    trichter['vorfilter_verlust'] = trichter['rev_net_mktcap'] - trichter['screened_with_fundamentals']

    # Finanzdaten-Abdeckung
    trichter['fin_tickers'] = cur.execute("SELECT COUNT(DISTINCT fin_sym) FROM t_fin_financials").fetchone()[0]

    return trichter


def load_ticker_data(ft_con, sec_con):
    """Lade nur die Ticker im aktiven Daily Screen (nach Vorfilter $5/200K Vol).
    Markiert Ticker mit vollstaendigen Fundamentaldaten (Rev + Net + MktCap)."""
    cur = ft_con.cursor()

    # Aktives Universum: nur Ticker im Daily Screen am letzten Datum
    last_date = cur.execute("SELECT MAX(datum) FROM daily_screen").fetchone()[0]
    screen_syms = set(r[0] for r in cur.execute(
        "SELECT DISTINCT ticker FROM daily_screen WHERE datum = ?", (last_date,)
    ))

    # Ticker mit Rev + Net + SEC MktCap (die 2.086)
    fundamentals_syms = set(r[0] for r in cur.execute("""
        SELECT DISTINCT f.fin_sym
        FROM t_fin_financials f
        JOIN t_qtr_perioden q ON f.fin_qtr = q.qtr_quarter
        WHERE q.qtr_kategorie = 1
        AND f.fin_qtr_net IS NOT NULL AND f.fin_qtr_net != 0
        AND f.fin_qlf_qtr_net != 'd'
        AND f.fin_qtr_rev IS NOT NULL AND f.fin_qtr_rev != 0
        AND f.fin_qlf_qtr_rev != 'd'
        AND f.fin_sym IN (
            SELECT DISTINCT fin_sym FROM t_fin_financials
            WHERE (fin_ann_public_float IS NOT NULL AND fin_ann_public_float > 0)
               OR (fin_qtr_shr_sec IS NOT NULL AND fin_qtr_shr_sec > 0)
        )
    """))

    # Stammdaten nur fuer aktive Ticker
    tickers = {}
    for r in cur.execute("""
        SELECT std_sym, std_name, std_exchange, std_fin_type, std_fiscal_year_end
        FROM t_std_stammdaten
        WHERE std_sym IN ({})
        ORDER BY std_sym
    """.format(','.join(f"'{s}'" for s in screen_syms))):
        tickers[r[0]] = {
            'sym': r[0],
            'name': r[1] or '',
            'exchange': r[2] or '',
            'fin_type': r[3] or '',
            'fye': r[4] or '',
            'quarters': {},
            'has_fundamentals': r[0] in fundamentals_syms,
        }

    # Filing-Status pro Quartal (nur aktive Ticker)
    for r in cur.execute("""
        SELECT fin_sym, fin_qtr, fin_qlf_qtr_rev, fin_filed_10q, fin_filed_10k
        FROM t_fin_financials
        WHERE fin_qtr IN ({qtrs})
        AND fin_sym IN ({syms})
    """.format(
        qtrs=','.join(f"'{q}'" for q in DISPLAY_QUARTERS),
        syms=','.join(f"'{s}'" for s in screen_syms),
    )):
        sym = r[0]
        if sym in tickers:
            tickers[sym]['quarters'][r[1]] = {
                'qlf': r[2] or 'd',
                'has_10q': bool(r[3]),
                'has_10k': bool(r[4]),
            }

    # SEC DB: zusaetzliche Info (category, SIC) + Sektor-Zuordnung
    if sec_con:
        sc = sec_con.cursor()
        for r in sc.execute("SELECT ticker, category, sic_desc, has_facts FROM companies WHERE ticker IS NOT NULL"):
            if r[0] in tickers:
                cat = (r[1] or '').split('<br>')[0].strip()
                tickers[r[0]]['sec_category'] = cat
                tickers[r[0]]['sec_industry'] = r[2] or ''
                tickers[r[0]]['sec_has_facts'] = bool(r[3])
                tickers[r[0]]['sector'] = sic_to_sector(r[2])

    # SMA50/SMA200 + Golden Cross + Abst. 52W-Hoch + Perf 3M aus Daily Screen
    for r in cur.execute("""
        SELECT ticker, ueber_sma50, ueber_sma200, golden_cross, abst_hoch, perf_3m
        FROM daily_screen WHERE datum = ?
    """, (last_date,)):
        if r[0] in tickers:
            tickers[r[0]]['sma50'] = int(r[1]) if r[1] is not None else 0
            tickers[r[0]]['sma200'] = int(r[2]) if r[2] is not None else 0
            tickers[r[0]]['gc'] = int(r[3]) if r[3] is not None else 0
            tickers[r[0]]['near_high'] = 1 if (r[4] is not None and abs(r[4]) <= 25) else 0
            tickers[r[0]]['perf3m_pos'] = 1 if (r[5] is not None and r[5] > 0) else 0

    # FAATMAN + NVDA: sicherstellen dass Daten da sind (auch wenn nicht im Screening)
    for sym in FAATMAN_NVDA:
        if sym not in tickers:
            # Stammdaten laden
            sr = cur.execute("SELECT std_name, std_exchange FROM t_std_stammdaten WHERE std_sym=?", (sym,)).fetchone()
            if sr:
                tickers[sym] = {
                    'sym': sym, 'name': sr[0] or '', 'exchange': sr[1] or '',
                    'fin_type': '', 'fye': '', 'quarters': {},
                    'has_fundamentals': False, 'is_faatman': True,
                }
        if sym in tickers:
            tickers[sym]['is_faatman'] = True

    # --- Market Cap + gewichtetes YoY-Wachstum berechnen ---
    # Verwendet calc_weighted_growth Modul (wiederverwendbar fuer andere Skripte)
    for sym in list(tickers.keys()):
        t = tickers[sym]

        # Aktueller Kurs aus Daily Screen
        kurs_row = cur.execute(
            "SELECT kurs FROM daily_screen WHERE ticker=? AND datum=?", (sym, last_date)
        ).fetchone()
        kurs = kurs_row[0] if kurs_row and kurs_row[0] else 0
        t['kurs'] = kurs

        # Market Cap (SEC-Daten: Shares Outstanding oder Public Float)
        t['mktcap'] = calc_market_cap_sec(cur, sym, kurs)

        # Gewichtetes YoY-Wachstum (juengste 2 echte 10-Q)
        t['rev_w'], t['net_w'] = calc_weighted_growth(cur, sym)

    return tickers


def build_factsheet_data(cur, tickers, overview_syms):
    """Baue kompakte Factsheet-Daten fuer alle OV-Ticker."""
    if not overview_syms:
        return {}

    syms_sql = ','.join(f"'{s}'" for s in overview_syms)

    # Alle Quartalsdaten laden (inkl. Vorjahr fuer YoY)
    qtr_data = {}
    for r in cur.execute(f"""
        SELECT fin_sym, fin_qtr, fin_qtr_rev, fin_qtr_net
        FROM t_fin_financials
        WHERE fin_sym IN ({syms_sql})
        AND fin_qlf_qtr_rev != 'd' AND fin_qlf_qtr_net != 'd'
        AND fin_qtr_rev IS NOT NULL AND fin_qtr_net IS NOT NULL
    """):
        sym, qtr, rev, net = r
        if sym not in qtr_data:
            qtr_data[sym] = {}
        qtr_data[sym][qtr] = (rev, net)

    # Naechster Earnings-Termin
    today_str = cur.execute("SELECT MAX(datum) FROM daily_screen").fetchone()[0]
    earnings = {}
    try:
        for r in cur.execute(f"""
            SELECT ticker, MIN(earnings_date)
            FROM t_sym_edt_earningsdate
            WHERE ticker IN ({syms_sql}) AND earnings_date >= ?
            GROUP BY ticker
        """, (today_str,)):
            earnings[r[0]] = r[1]
    except Exception:
        pass

    # Letzte 4 aktive Quartale
    active_qtrs = [r[0] for r in cur.execute("""
        SELECT qtr_quarter FROM t_qtr_perioden
        WHERE qtr_kategorie = 1
        ORDER BY qtr_quarter DESC LIMIT 4
    """)]

    def yoy_qtr(q):
        return f"{int(q[:4])-1}{q[4:]}"

    fs = {}
    for sym in overview_syms:
        t = tickers.get(sym, {})
        qtrs = qtr_data.get(sym, {})
        q_list = []
        for q in active_qtrs:
            if q in qtrs:
                rev, net = qtrs[q]
                prev = qtrs.get(yoy_qtr(q))
                ry = round((rev / prev[0] - 1) * 100, 1) if prev and prev[0] else None
                ny = None
                if prev and prev[1]:
                    ny = 999 if (prev[1] < 0 and net > 0) else round((net / prev[1] - 1) * 100, 1)
                q_list.append([q, round(rev / 1e6, 1), round(net / 1e6, 1), ry, ny])

        fs[sym] = {
            'n': t.get('name', '')[:50],
            'x': t.get('exchange', ''),
            's': t.get('sector', 'Other'),
            'si': t.get('sec_industry', ''),
            'cat': t.get('sec_category', ''),
            'fy': t.get('fye', ''),
            'mc': round(t.get('mktcap', 0) / 1e9, 1),
            'p': round(t.get('kurs', 0), 2),
            's5': t.get('sma50', 0),
            's2': t.get('sma200', 0),
            'rw': t.get('rev_w'),
            'nw': t.get('net_w'),
            'ne': earnings.get(sym, ''),
            'q': q_list,
        }

    return fs


# ==============================================================
# HTML GENERIEREN
# ==============================================================
def generate_html(trichter, tickers, output_path, ft_con=None):
    """Generiere die Filing Cabinet HTML-Seite."""

    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    total = len(tickers)

    # --- Ticker-Listen aufbauen ---
    # Uebersicht: nur $1B+ MktCap mit Rev>=20% und Net>=20%
    overview_list = []
    # Vollstaendige Liste: alle Daily-Screen-Ticker (fuer Detail-Tab)
    detail_list = []
    # Alle Sektoren sammeln
    sector_set = set()

    overview_syms = set()  # Track welche Ticker in der Overview sind

    for sym in sorted(tickers.keys()):
        t = tickers[sym]
        # Filing-Status als kompaktes Array
        qdata = []
        for q in DISPLAY_QUARTERS:
            qi = t['quarters'].get(q, {'qlf': 'd', 'has_10q': False, 'has_10k': False})
            qdata.append([qi['qlf'], qi['has_10q'], qi['has_10k']])

        mktcap_b = round(t.get('mktcap', 0) / 1e9, 1) if t.get('mktcap', 0) > 0 else 0
        rev_w = t.get('rev_w')
        net_w = t.get('net_w')
        kurs = round(t.get('kurs', 0), 2)
        sector = t.get('sector', 'Other')
        sma50 = t.get('sma50', 0)
        sma200 = t.get('sma200', 0)
        if sector:
            sector_set.add(sector)

        detail_list.append([
            t['sym'], t['name'][:40], t['exchange'], t['fin_type'], t['fye'],
            qdata, 1 if t.get('has_fundamentals') else 0,
        ])

        # Uebersicht: Vorfilter $500M MktCap, 10% Rev, 10% Net (Slider defaults: $1B/20%/20%)
        # OV format: [sym, name, exchange, mktcap_B, rev_w%, net_w%, kurs, sector, sma50, sma200, gc, near_high, perf3m_pos]
        gc = t.get('gc', 0)
        near_high = t.get('near_high', 0)
        perf3m_pos = t.get('perf3m_pos', 0)
        if (t.get('mktcap', 0) >= 500_000_000
            and rev_w is not None and rev_w >= 10
            and net_w is not None and net_w >= 10):
            overview_list.append([
                t['sym'], t['name'][:40], t['exchange'],
                mktcap_b, rev_w, net_w, kurs, sector, sma50, sma200,
                gc, near_high, perf3m_pos,
            ])
            overview_syms.add(sym)

    # FAATMAN+NVDA: nur Symbole (Auswahl-Box, kein Daten-Block mehr)

    # Uebersicht: sortiert nach Net Income Wachstum absteigend
    overview_list.sort(key=lambda x: x[5], reverse=True)
    ticker_list = detail_list  # fuer Kompatibilitaet

    # Factsheet-Daten fuer alle OV-Ticker
    fs_data = build_factsheet_data(ft_con.cursor(), tickers, overview_syms) if ft_con else {}

    # Sektor-Liste sortiert + HTML-Items vorab generieren (Name + Checkbox-Box)
    sectors_sorted = sorted(sector_set)
    seg_items_html = ''.join(
        '<div class="seg-item" onclick="segClick(\'{s}\')" data-seg="{s}">'
        '<div class="seg-label">{s}</div>'
        '<div class="seg-box included"></div>'
        '</div>'.format(s=s)
        for s in sectors_sorted
    )

    # FAATMAN Chips: einfache Checkboxen mit Kuerzel
    faatman_chips = ''.join(
        '<label style="display:inline-flex;align-items:center;gap:2px;cursor:pointer;color:var(--green2);">'
        '<input type="checkbox" onchange="lvTrdToggle(\'{s}\')" '
        'style="cursor:pointer;accent-color:var(--green);margin:0;" data-faatman="{s}">'
        '{s}</label>'.format(s=s)
        for s in FAATMAN_NVDA
    )

    # Trichter-Erweiterung: Vorfilter $500M/10%/10%, Standard-Anzeige $1B/20%/20%
    trichter['mktcap_500m'] = sum(1 for r in overview_list)  # OV ist bereits >= $500M/10%/10%
    trichter['mktcap_1b'] = sum(1 for r in overview_list if r[3] >= 1.0)
    # growth_candidates = Standard-Filter ($1B, Rev>=20%, Net>=20%) fuer Trichter-Anzeige
    trichter['growth_candidates'] = sum(
        1 for r in overview_list if r[3] >= 1.0 and r[4] >= 20 and r[5] >= 20
    )
    trichter['ov_total'] = len(overview_list)  # Vorfilter: $500M + 10%/10%

    # Dynamische Filter-Optionen aus aktuellem Universum
    active_types = sorted(set(t['fin_type'] for t in tickers.values() if t['fin_type']))
    type_options = '\n    '.join(f'<option value="{ft}">{ft}</option>' for ft in active_types)

    # Trichter-Zahlen
    tr = trichter

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Artifakte — SEC Filing Cabinet</title>
<style>
:root {{
  --bg: #0f0f1a; --surface: #1a1a2e; --surface2: #16213e;
  --text: #e8e8f0; --dim: #636e72; --accent: #e94560;
  --green: #00b894; --green2: #00cec9; --yellow: #ffeaa7;
  --orange: #fdcb6e; --red: #d63031; --blue: #74b9ff;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  background: var(--bg); color: var(--text);
  max-width: 1200px; margin: 0 auto; padding: 10px 16px;
  font-size: 12px;
}}
h1 {{ color: var(--accent); font-size: 16px; margin-bottom: 1px; }}
.subtitle {{ color: var(--dim); font-size: 9px; margin-bottom: 8px; }}

/* ===== TRICHTER ===== */
.funnel {{
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 6px; padding: 4px 10px; margin-bottom: 6px;
  max-height: 45vh; overflow-y: auto;
}}
.funnel-title {{ color: var(--accent); font-size: 10px; font-weight: bold; margin-bottom: 2px; }}
.funnel-steps {{
  display: flex; align-items: center; gap: 0; flex-wrap: wrap;
  justify-content: center;
}}
.funnel-step {{
  text-align: center; padding: 1px 6px; position: relative;
  min-width: 70px;
}}
.funnel-step .fn {{ font-size: 13px; font-weight: bold; color: var(--green2); }}
.funnel-step .fl {{ font-size: 7px; color: var(--dim); margin-top: 0; }}
.funnel-arrow {{ color: var(--dim); font-size: 12px; padding: 0 1px; }}
.funnel-removed {{ color: var(--red); font-size: 7px; }}

/* Stats */
.stats {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
.stat {{
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 5px; padding: 5px 10px; flex: 1; min-width: 120px;
}}
.stat .sv {{ font-size: 14px; font-weight: bold; color: var(--green2); }}
.stat .sl {{ font-size: 8px; color: var(--dim); margin-top: 1px; }}

/* ===== FILTER ===== */
.filter-bar {{
  display: flex; gap: 6px; align-items: center; margin-bottom: 6px;
  flex-wrap: wrap;
}}
.filter-bar input {{
  font-family: inherit; font-size: 11px; padding: 4px 8px;
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 4px; width: 180px;
}}
.filter-bar input:focus {{ border-color: var(--accent); outline: none; }}
.filter-bar select {{
  font-family: inherit; font-size: 10px; padding: 4px 6px;
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 4px;
}}
.filter-count {{ color: var(--dim); font-size: 10px; margin-left: auto; }}

/* Letter bar */
.letter-bar {{ display: flex; gap: 2px; flex-wrap: wrap; margin-bottom: 6px; }}
.letter-btn {{
  font-family: inherit; font-size: 10px; font-weight: bold;
  width: 22px; height: 22px; display: flex; align-items: center;
  justify-content: center; border-radius: 3px; border: 1px solid #2d3436;
  background: var(--surface); color: var(--dim); cursor: pointer;
}}
.letter-btn:hover {{ background: var(--surface2); color: var(--text); }}
.letter-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* ===== TABLE ===== */
.table-wrap {{
  overflow-x: auto; background: var(--surface);
  border: 1px solid #2d3436; border-radius: 8px;
}}
table {{
  width: 100%; border-collapse: collapse; font-size: 11px;
}}
thead th {{
  background: var(--surface2); color: var(--dim); font-size: 10px;
  padding: 6px 8px; text-align: left; position: sticky; top: 0;
  border-bottom: 1px solid #2d3436; white-space: nowrap;
  cursor: pointer; user-select: none;
}}
thead th:hover {{ color: var(--text); }}
thead th.sorted {{ color: var(--accent); }}
tbody tr {{ border-bottom: 1px solid #111; }}
tbody tr:hover {{ background: rgba(233,69,96,0.05); }}
td {{ padding: 4px 8px; white-space: nowrap; }}
td.sym {{ color: var(--accent); font-weight: bold; }}
td.name {{ color: var(--text); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }}
td.exch {{ color: var(--blue); }}
td.ftype {{ color: var(--dim); }}
td.fye {{ color: var(--dim); text-align: center; }}

/* Filing dots */
.q {{ display: inline-block; width: 14px; text-align: center; font-size: 10px; }}
.q.ok {{ color: var(--green); }}
.q.csec {{ color: var(--orange); }}
.q.miss {{ color: var(--red); }}
.q.k {{ font-weight: bold; }}

/* Quarter header groups */
th.qg {{ text-align: center; padding: 4px 2px; font-size: 9px; min-width: 32px; }}

/* Tabs */
.tabs {{ display: flex; gap: 0; margin-bottom: 4px; }}
.tab-btn {{
  font-family: inherit; font-size: 10px; font-weight: bold;
  padding: 4px 14px; border: 1px solid #2d3436; background: var(--surface);
  color: var(--dim); cursor: pointer; border-bottom: none;
  border-radius: 5px 5px 0 0;
}}
.tab-btn.active {{ background: var(--surface2); color: var(--green2); border-color: var(--green2); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}

/* Overview table */
.ov-wrap {{ max-height: 78vh; overflow-y: auto; background: var(--surface); border: 1px solid #2d3436; border-radius: 6px; }}
.ov-wrap table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
.ov-wrap thead th {{
  background: var(--surface2); color: var(--dim); font-size: 10px;
  padding: 5px 8px; text-align: left; position: sticky; top: 0;
  border-bottom: 1px solid #2d3436; cursor: pointer; user-select: none; white-space: nowrap;
}}
.ov-wrap thead th:hover {{ color: var(--text); }}
.ov-wrap thead th.sorted {{ color: var(--accent); }}
.ov-wrap tbody tr {{ border-bottom: 1px solid #111; }}
.ov-wrap tbody tr:hover {{ background: rgba(233,69,96,0.05); }}
.ov-wrap td {{ padding: 3px 8px; white-space: nowrap; }}
td.pos {{ color: var(--green); }}
td.neg {{ color: var(--red); }}
td.mc {{ color: var(--blue); text-align: right; }}
td.pct {{ text-align: right; }}
td.sec {{ color: var(--dim); font-size: 10px; }}
td.sma {{ text-align: center; font-size: 10px; }}
td.sma.above {{ color: var(--green); }}
td.sma.below {{ color: var(--red); }}

/* Segment Filter Bar — 2 Zeilen: Name oben, Checkbox unten */
.seg-bar {{
  display: flex; flex-wrap: nowrap; gap: 1px; margin-bottom: 4px;
  padding: 2px 4px; background: var(--surface); border: 1px solid #2d3436;
  border-radius: 5px; align-items: center; overflow-x: auto;
}}
.seg-item {{
  display: flex; flex-direction: row; align-items: center; gap: 1px;
  cursor: pointer; padding: 1px 2px; flex-shrink: 0;
}}
.seg-item .seg-label {{
  font-size: 7px; color: var(--dim); white-space: nowrap;
  transition: color 0.15s;
}}
.seg-item:hover .seg-label {{ color: var(--text); }}
.seg-item .seg-box {{
  width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0;
  border: 1px solid #2d3436; transition: background 0.15s, border-color 0.15s;
}}
.seg-item .seg-box.included {{
  background: var(--green); border-color: var(--green);
}}
.seg-item .seg-box.excluded {{
  background: var(--red); border-color: var(--red);
}}
/* Leere Segmente (0 Ticker in Overview) ausgrauen */
.seg-item.empty {{
  opacity: 0.55; cursor: default;
}}
.seg-item.empty .seg-box {{
  background: #2d3436 !important; border-color: #2d3436 !important;
}}
/* Slider Filter Bar */
.slider-bar {{
  display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 4px;
  padding: 3px 8px; background: var(--surface); border: 1px solid #2d3436;
  border-radius: 5px; align-items: center;
}}
.slider-group {{
  display: flex; align-items: center; gap: 4px;
}}
.slider-group label {{
  font-size: 9px; color: var(--dim); white-space: nowrap; min-width: 55px;
}}
.slider-group input[type="range"] {{
  width: 120px; height: 4px; accent-color: var(--green2);
  cursor: pointer;
}}
.slider-group .sv {{
  font-size: 10px; color: var(--green2); font-weight: bold;
  min-width: 45px; text-align: right;
}}

/* CSV Download Button */
.csv-btn {{
  font-family: inherit; font-size: 9px; padding: 3px 10px;
  border-radius: 3px; border: 1px solid var(--green2);
  background: var(--surface2); color: var(--green2); cursor: pointer;
  margin-left: 6px;
}}
.csv-btn:hover {{ background: var(--green2); color: #000; }}
/* "Alle" Button: Sonderstellung */
.seg-item.all-item .seg-label {{
  font-weight: bold; color: var(--green2);
}}
.seg-item.all-item .seg-box.included {{
  background: var(--green2); border-color: var(--green2);
}}

/* FACTSHEET MODAL */
.fs-overlay {{
  display:none; position:fixed; top:0; left:0; width:100%; height:100%;
  background:rgba(0,0,0,0.75); z-index:9000; justify-content:center; align-items:center;
}}
.fs-overlay.open {{ display:flex; }}
.fs-card {{
  background:var(--surface); border:1px solid #2d3436; border-radius:8px;
  width:560px; max-width:95vw; max-height:90vh; overflow-y:auto;
  padding:20px 24px; position:relative; box-shadow:0 8px 32px rgba(0,0,0,0.5);
}}
.fs-close {{
  position:absolute; top:8px; right:12px; font-size:18px; color:var(--dim);
  cursor:pointer; background:none; border:none; font-family:inherit;
}}
.fs-close:hover {{ color:var(--green); }}
.fs-head {{ display:flex; align-items:center; gap:14px; margin-bottom:14px; }}
.fs-icon {{
  width:48px; height:48px; border-radius:8px; display:flex;
  align-items:center; justify-content:center; font-size:20px;
  font-weight:bold; color:#fff; flex-shrink:0;
}}
.fs-title {{ font-size:16px; font-weight:bold; color:var(--green); }}
.fs-subtitle {{ font-size:11px; color:var(--dim); margin-top:2px; }}
.fs-metrics {{
  display:grid; grid-template-columns:repeat(4, 1fr); gap:8px;
  margin:12px 0; padding:10px; background:var(--surface2); border-radius:6px;
}}
.fs-metric {{ text-align:center; }}
.fs-metric .label {{ font-size:9px; color:var(--dim); text-transform:uppercase; }}
.fs-metric .value {{ font-size:14px; font-weight:bold; color:var(--green2); margin-top:2px; }}
.fs-info {{
  font-size:11px; color:var(--dim); margin:8px 0;
  display:flex; flex-wrap:wrap; gap:4px 16px;
}}
.fs-growth {{
  display:flex; gap:20px; margin:12px 0; padding:8px 12px;
  background:var(--surface2); border-radius:6px; border-left:3px solid var(--green);
}}
.fs-growth .item {{ text-align:center; flex:1; }}
.fs-growth .label {{ font-size:9px; color:var(--dim); }}
.fs-growth .value {{ font-size:18px; font-weight:bold; margin-top:2px; }}
.fs-growth .value.pos {{ color:var(--green); }}
.fs-growth .value.neg {{ color:var(--accent); }}
.fs-qtable {{ width:100%; border-collapse:collapse; font-size:11px; margin-top:10px; }}
.fs-qtable th {{
  text-align:right; padding:4px 8px; border-bottom:1px solid #2d3436;
  font-size:9px; color:var(--dim); text-transform:uppercase;
}}
.fs-qtable th:first-child {{ text-align:left; }}
.fs-qtable td {{ padding:4px 8px; text-align:right; border-bottom:1px solid #1a1a2e; }}
.fs-qtable td:first-child {{ text-align:left; color:var(--green2); }}
.fs-qtable .yoy {{ font-size:10px; }}
.fs-qtable .yoy.pos {{ color:var(--green); }}
.fs-qtable .yoy.neg {{ color:var(--accent); }}
.fs-sym-link {{ cursor:pointer; color:var(--green); }}
.fs-sym-link:hover {{ text-decoration:underline; }}

/* SMA filter pills */
.sma-pill {{
  font-family: inherit; font-size: 9px; padding: 2px 7px;
  border-radius: 3px; border: 1px solid #2d3436;
  background: var(--surface2); color: var(--dim); cursor: pointer;
}}
.sma-pill.active {{ background: var(--green); color: #000; border-color: var(--green); }}


/* Footer */
.footer {{ margin-top: 8px; text-align: center; color: var(--dim); font-size: 9px; }}

/* Responsive */
@media (max-width: 800px) {{
  .funnel-steps {{ flex-direction: column; gap: 4px; }}
  .funnel-arrow {{ transform: rotate(90deg); }}
}}
</style>
</head>
<body>

<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;">
  <h1 style="margin:0;"><a href="index.html" style="color:var(--accent);text-decoration:none;" title="Zurueck zum Dashboard">&larr;</a> SEC Filing Cabinet</h1>
  <div class="footer" style="margin:0;text-align:right;">
    AI Artifakte — SEC Filing Cabinet v2.0 | {tr.get('growth_candidates', '?'):,} Kandidaten aus {total:,} (Daily Screen {tr.get('daily_screen_last', '?')}) | Generiert: {now}
  </div>
</div>

<!-- TRICHTER -->
<div class="funnel">
  <!-- Zeile 1: SEC → Boerse → Daily Screen (kompakt) -->
  <div class="funnel-steps">
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_registriert', '?'):,}</div>
      <div class="fl">SEC reg.</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_db', '?'):,}</div>
      <div class="fl">dedupl.</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_has_facts', '?'):,}</div>
      <div class="fl">XBRL</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('facts_listed', '?'):,}</div>
      <div class="fl">NQ+NYSE</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('rev_net', '?'):,}</div>
      <div class="fl">Rev+Net</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('rev_net_mktcap', '?'):,}</div>
      <div class="fl">+MktCap</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('screened_with_fundamentals', '?'):,}</div>
      <div class="fl">Price&gt;$5, Vol&gt;200K/d</div>
    </div>
  </div>
  <!-- Zeile 2: Vorfilter → Kandidaten -->
  <div class="funnel-steps" style="margin-top: 1px;">
    <div class="funnel-step" style="opacity:0.5">
      <div class="fn">{tr.get('screened_with_fundamentals', '?'):,}</div>
      <div class="fl">Price&gt;$5, Vol&gt;200K/d</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('mktcap_500m', '?'):,}</div>
      <div class="fl">$500M / 10% / 10%</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step" style="border:1px solid var(--green2);border-radius:4px;padding:1px 8px;">
      <div class="fn" style="color:var(--green);">{tr.get('growth_candidates', '?'):,}</div>
      <div class="fl">$1B / Rev 20% / Net 20%</div>
    </div>
  </div>
</div>

<!-- TABS -->
<div class="tabs">
  <div class="tab-btn active" onclick="switchTab('overview')">Uebersicht ({tr.get('growth_candidates', '?'):,})</div>
  <div class="tab-btn" onclick="switchTab('detail')">Filing Detail ({total:,})</div>
</div>

<!-- TAB 1: UEBERSICHT -->
<div class="tab-content active" id="tab-overview">

<!-- Segment-Filter: Name oben, Checkbox unten. Gruen=dabei, Rot=ausgeschlossen -->
<div class="seg-bar" id="segBar">
  <div class="seg-item all-item" onclick="segClickAll()" data-seg="*">
    <div class="seg-label">Alle</div>
    <div class="seg-box included"></div>
  </div>
  {seg_items_html}
</div>

<!-- Slider-Filter: MktCap, Rev%, Net% -->
<div class="slider-bar">
  <div class="slider-group">
    <label>MktCap &ge;</label>
    <input type="range" id="slMktCap" min="500" max="1200" value="1000" step="50"
           oninput="sliderChange()" title="Minimum Market Cap ($500M–$1.2B)">
    <input type="number" id="slMktCapInput" min="0" max="99999" value="1000" step="50"
           oninput="mktCapInputChange()" title="MktCap in Mio USD eingeben"
           style="width:55px;font-family:inherit;font-size:10px;padding:2px 4px;
           background:var(--surface2);color:var(--green2);border:1px solid #2d3436;
           border-radius:3px;text-align:right;">
    <span style="font-size:9px;color:var(--dim);">M</span>
  </div>
  <div class="slider-group">
    <label>Rev% &ge;</label>
    <input type="range" id="slRev" min="10" max="100" value="20" step="1"
           oninput="sliderChange()" title="Minimum Revenue Growth YoY (Vorfilter: 10%)">
    <span class="sv" id="slRevVal">20%</span>
  </div>
  <div class="slider-group">
    <label>Net% &ge;</label>
    <input type="range" id="slNet" min="10" max="100" value="20" step="1"
           oninput="sliderChange()" title="Minimum Net Income Growth YoY (Vorfilter: 10%)">
    <span class="sv" id="slNetVal">20%</span>
  </div>
</div>

<div class="filter-bar">
  <input type="text" id="ovSearch" placeholder="Ticker suchen..." oninput="ovFilter()" style="width:140px;">
  <div class="sma-pill" onclick="smaToggle(this,'sma50')" title="Nur Ticker ueber SMA50">&#9650;SMA50</div>
  <div class="sma-pill" onclick="smaToggle(this,'sma200')" title="Nur Ticker ueber SMA200">&#9650;SMA200</div>
  <div class="sma-pill" onclick="smaToggle(this,'gc')" title="Golden Cross: SMA50 &gt; SMA200 (95% Toleranz)">&#10010;GC</div>
  <div class="sma-pill" onclick="smaToggle(this,'nearHi')" title="Innerhalb 25% vom 52-Wochen-Hoch">&#9733;52W</div>
  <div class="sma-pill" onclick="smaToggle(this,'perf3m')" title="3-Monats-Performance &gt; 0%">&#8679;3M</div>
  <span class="filter-count" id="ovCount">{len(overview_list)} Ticker</span>
  <button class="csv-btn" onclick="ovDownloadCSV()" title="Angezeigte Ticker als CSV herunterladen">&#11015; CSV</button>
  <button class="csv-btn" style="border-color:var(--accent);color:var(--accent);" onclick="ovExportLiveTrading()" title="Nur angehakte Ticker als live_watchlist.txt exportieren" id="btnLvTrd">&#9654; Live Trading</button>
</div>

<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;
  margin:2px 0 4px;padding:3px 8px;background:var(--surface2);border-radius:4px;font-size:10px;">
  <span style="color:var(--dim);">FAATMAN+NVDA im Live Trading Download ber&uuml;cksichtigen:</span>
  {faatman_chips}
  <span style="margin-left:auto;color:var(--green2);cursor:pointer;font-size:9px;text-decoration:underline;"
    onclick="faatmanSelectAll()">Alle</span>
</div>

<div class="ov-wrap">
<table>
<thead><tr>
  <th style="text-align:center;cursor:pointer;font-size:9px;" onclick="lvTrdToggleAll()" title="Klick = alle ab-/anwaehlen">Lv Trd</th>
  <th onclick="ovSort(0)">Ticker</th>
  <th onclick="ovSort(1)">Name</th>
  <th onclick="ovSort(7)">Sektor</th>
  <th onclick="ovSort(3)" style="text-align:right">MktCap $B</th>
  <th onclick="ovSort(4)" style="text-align:right">Rev% YoY</th>
  <th onclick="ovSort(5)" style="text-align:right" class="sorted">Net% YoY ▼</th>
  <th onclick="ovSort(6)" style="text-align:right">Kurs $</th>
  <th onclick="ovSort(8)" style="text-align:center" title="Ueber SMA50">50</th>
  <th onclick="ovSort(9)" style="text-align:center" title="Ueber SMA200">200</th>
</tr></thead>
<tbody id="ovBody"></tbody>
</table>
</div>

</div>

<!-- TAB 2: FILING DETAIL -->
<div class="tab-content" id="tab-detail">
<div class="letter-bar" id="letterBar"></div>
<div class="filter-bar">
  <input type="text" id="search" placeholder="Ticker oder Name suchen..." oninput="applyFilter()">
  <select id="filterExch" onchange="applyFilter()">
    <option value="">Alle Boersen</option>
    <option value="NASDAQ">NASDAQ</option>
    <option value="NYSE">NYSE</option>
    <option value="AMEX">AMEX</option>
  </select>
  <select id="filterType" onchange="applyFilter()">
    <option value="">Alle Typen</option>
    {type_options}
  </select>
  <select id="filterFiling" onchange="applyFilter()">
    <option value="">Alle Filing-Status</option>
    <option value="complete">10-Q komplett (alle 8 Qtrs)</option>
    <option value="partial">10-Q teilweise</option>
    <option value="missing">Keine 10-Q</option>
    <option value="has_csec">Hat c-sec Quartale</option>
  </select>
  <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;font-size:10px;color:var(--green2);">
    <input type="checkbox" id="filterFundamentals" onchange="applyFilter()" checked style="accent-color:#00ff88;width:13px;height:13px;">
    Fundamentaldaten ({tr.get('screened_with_fundamentals', 0):,})
  </label>
  <span class="filter-count" id="filterCount"></span>
</div>
<div class="table-wrap" style="max-height: 78vh; overflow-y: auto;">
<table>
<thead>
<tr>
  <th onclick="sortTable(0)" id="th0">Ticker</th>
  <th onclick="sortTable(1)" id="th1">Name</th>
  <th onclick="sortTable(2)" id="th2">Boerse</th>
  <th onclick="sortTable(3)" id="th3">Typ</th>
  <th onclick="sortTable(4)" id="th4">FYE</th>
  <th class="qg" colspan="2">Q1 24</th>
  <th class="qg" colspan="2">Q2 24</th>
  <th class="qg" colspan="2">Q3 24</th>
  <th class="qg" colspan="2">Q4 24</th>
  <th class="qg" colspan="2">Q1 25</th>
  <th class="qg" colspan="2">Q2 25</th>
  <th class="qg" colspan="2">Q3 25</th>
  <th class="qg" colspan="2">Q4 25</th>
</tr>
<tr>
  <th></th><th></th><th></th><th></th><th></th>
  {"".join('<th class="qg" title="10-Q">Q</th><th class="qg" title="10-K">K</th>' for _ in DISPLAY_QUARTERS)}
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
</div>
</div><!-- /tab-detail -->


<script>
const QTRS = {json.dumps(DISPLAY_QUARTERS)};
const DATA = {json.dumps(ticker_list, separators=(',', ':'))};
// DATA format: [sym, name, exchange, fin_type, fye, [[qlf,has10q,has10k], ...x8], has_fundamentals]

// === OVERVIEW DATA ===
const OV = {json.dumps(overview_list, separators=(',', ':'))};
// OV format: [sym, name, exchange, mktcap_B, rev_w%, net_w%, kurs, sector, sma50, sma200]

const FAATMAN_LIST = {json.dumps([s for s in FAATMAN_NVDA])};

// === FACTSHEET DATA ===
const FS = {json.dumps(fs_data, separators=(',', ':'))};

// === SEGMENT + SMA FILTER STATE ===
// excludedSegments: Set von Sektoren die AUSGESCHLOSSEN sind (rot)
// Leer = alle sind dabei (gruen)
let excludedSegments = new Set();
let smaFilter50 = false;
let smaFilter200 = false;
let gcFilter = false;
let nearHiFilter = false;
let perf3mFilter = false;

let activeLetter = '';
let sortCol = 0;
let sortAsc = true;
let filtered = DATA.slice();

// Letter bar
const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
const letterBar = document.getElementById('letterBar');
const allBtn = document.createElement('div');
allBtn.className = 'letter-btn active';
allBtn.textContent = '*';
allBtn.onclick = () => {{ activeLetter = ''; applyFilter(); updateLetterBtns(); }};
letterBar.appendChild(allBtn);
letters.forEach(l => {{
  const btn = document.createElement('div');
  btn.className = 'letter-btn';
  btn.textContent = l;
  btn.onclick = () => {{ activeLetter = l; applyFilter(); updateLetterBtns(); }};
  letterBar.appendChild(btn);
}});

function updateLetterBtns() {{
  document.querySelectorAll('.letter-btn').forEach(b => {{
    b.classList.toggle('active',
      (b.textContent === '*' && !activeLetter) ||
      (b.textContent === activeLetter));
  }});
}}

function applyFilter() {{
  const search = document.getElementById('search').value.toUpperCase();
  const exch = document.getElementById('filterExch').value;
  const ftype = document.getElementById('filterType').value;
  const filing = document.getElementById('filterFiling').value;
  const onlyFund = document.getElementById('filterFundamentals').checked;

  filtered = DATA.filter(r => {{
    // r[6] = has_fundamentals (0/1)
    if (onlyFund && !r[6]) return false;
    if (activeLetter && !r[0].startsWith(activeLetter)) return false;
    if (search && !r[0].includes(search) && !r[1].toUpperCase().includes(search)) return false;
    if (exch && r[2] !== exch) return false;
    if (ftype && r[3] !== ftype) return false;
    if (filing) {{
      const qs = r[5];
      const has10q = qs.filter(q => q[1]).length;
      const hasCSec = qs.filter(q => q[0] === 'c-sec').length;
      if (filing === 'complete' && has10q < 8) return false;
      if (filing === 'partial' && (has10q === 0 || has10q >= 8)) return false;
      if (filing === 'missing' && has10q > 0) return false;
      if (filing === 'has_csec' && hasCSec === 0) return false;
    }}
    return true;
  }});

  sortFiltered();
  render();
}}

function sortTable(col) {{
  if (sortCol === col) sortAsc = !sortAsc;
  else {{ sortCol = col; sortAsc = true; }}
  document.querySelectorAll('thead th').forEach(th => th.classList.remove('sorted'));
  const thEl = document.getElementById('th' + col);
  if (thEl) thEl.classList.add('sorted');
  sortFiltered();
  render();
}}

function sortFiltered() {{
  filtered.sort((a, b) => {{
    let va = a[sortCol] || '', vb = b[sortCol] || '';
    if (typeof va === 'string') va = va.toUpperCase();
    if (typeof vb === 'string') vb = vb.toUpperCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  }});
}}

function qdot(qlf, has10q, has10k) {{
  // 10-Q Status
  let qHtml = '';
  if (has10q) {{
    qHtml = qlf === 'c-sec'
      ? '<span class="q csec" title="c-sec (berechnet)">◆</span>'
      : '<span class="q ok" title="10-Q geladen">●</span>';
  }} else {{
    qHtml = '<span class="q miss" title="fehlt">○</span>';
  }}
  // 10-K Status
  let kHtml = has10k
    ? '<span class="q ok k" title="10-K geladen">K</span>'
    : '<span class="q miss" title="kein 10-K"> </span>';
  return qHtml + kHtml;
}}

function render() {{
  const tbody = document.getElementById('tbody');
  const maxRows = 500;
  const showing = filtered.slice(0, maxRows);

  document.getElementById('filterCount').textContent =
    filtered.length + ' von ' + DATA.length + ' Ticker' +
    (filtered.length > maxRows ? ' (zeige erste ' + maxRows + ')' : '');

  let html = '';
  for (const r of showing) {{
    html += '<tr>';
    html += '<td class="sym">' + r[0] + '</td>';
    html += '<td class="name">' + r[1] + '</td>';
    html += '<td class="exch">' + r[2] + '</td>';
    html += '<td class="ftype">' + r[3] + '</td>';
    html += '<td class="fye">' + r[4] + '</td>';
    for (const q of r[5]) {{
      html += '<td style="text-align:center;padding:2px;">' + qdot(q[0], q[1], q[2]) + '</td>';
    }}
    html += '</tr>';
  }}
  tbody.innerHTML = html;
}}

// Initial (Detail-Tab)
sortFiltered();
render();

// === TAB SWITCHING ===
function switchTab(tab) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  event.target.classList.add('active');
}}

// === SEGMENT FILTER (Ausschluss-Logik) ===
// Alle Segment-Items im DOM
function updateSegBoxes() {{
  // Alle Segment-Checkboxen aktualisieren
  document.querySelectorAll('.seg-item').forEach(item => {{
    const seg = item.dataset.seg;
    const box = item.querySelector('.seg-box');
    if (seg === '*') {{
      // "Alle"-Box: gruen wenn nichts ausgeschlossen, rot wenn alles ausgeschlossen
      const allSegs = document.querySelectorAll('.seg-item:not(.all-item)');
      const allExcluded = excludedSegments.size >= allSegs.length;
      box.className = 'seg-box ' + (allExcluded ? 'excluded' : 'included');
    }} else {{
      box.className = 'seg-box ' + (excludedSegments.has(seg) ? 'excluded' : 'included');
    }}
  }});
}}

function segClick(sector) {{
  // Leere Segmente ignorieren (kein Toggle)
  const item = document.querySelector('.seg-item[data-seg="' + sector + '"]');
  if (item && item.classList.contains('empty')) return;
  // Einzelnes Segment toggeln: gruen → rot (ausschliessen) oder rot → gruen (einschliessen)
  if (excludedSegments.has(sector)) {{
    excludedSegments.delete(sector);
  }} else {{
    excludedSegments.add(sector);
  }}
  updateSegBoxes();
  ovFilter();
}}

function segClickAll() {{
  // "Alle"-Button: Wenn alle dabei (gruen) → alle ausschliessen (rot)
  // Wenn mindestens eins ausgeschlossen → alle wieder einschliessen (gruen)
  const allSegs = document.querySelectorAll('.seg-item:not(.all-item)');
  if (excludedSegments.size === 0) {{
    // Alle sind gruen → alle auf rot
    allSegs.forEach(item => excludedSegments.add(item.dataset.seg));
  }} else {{
    // Mindestens eins rot → alle auf gruen
    excludedSegments.clear();
  }}
  updateSegBoxes();
  ovFilter();
}}

// === SMA FILTER ===
function smaToggle(btn, which) {{
  if (which === 'sma50') {{ smaFilter50 = !smaFilter50; btn.classList.toggle('active'); }}
  if (which === 'sma200') {{ smaFilter200 = !smaFilter200; btn.classList.toggle('active'); }}
  if (which === 'gc') {{ gcFilter = !gcFilter; btn.classList.toggle('active'); }}
  if (which === 'nearHi') {{ nearHiFilter = !nearHiFilter; btn.classList.toggle('active'); }}
  if (which === 'perf3m') {{ perf3mFilter = !perf3mFilter; btn.classList.toggle('active'); }}
  ovFilter();
}}

// === SLIDER FILTER ===
let slMktCapMin = 1.0;   // Default: $1B
let slRevMin = 20;        // Default: 20%
let slNetMin = 20;        // Default: 20%

function sliderChange() {{
  // Slider: $500M–$1200M in $50M Schritten, Wert = Mio USD
  const mcMio = parseInt(document.getElementById('slMktCap').value);
  slMktCapMin = mcMio / 1000;  // in $B fuer OV-Vergleich
  // Input-Feld synchronisieren
  document.getElementById('slMktCapInput').value = mcMio;

  slRevMin = parseInt(document.getElementById('slRev').value);
  document.getElementById('slRevVal').textContent = slRevMin + '%';

  slNetMin = parseInt(document.getElementById('slNet').value);
  document.getElementById('slNetVal').textContent = slNetMin + '%';

  ovFilter();
}}

function mktCapInputChange() {{
  // Eingabefeld: beliebiger Mio-Wert, Slider folgt (geclampt auf Slider-Range)
  const mcMio = parseInt(document.getElementById('slMktCapInput').value) || 0;
  slMktCapMin = mcMio / 1000;  // in $B
  // Slider synchronisieren (geclampt auf 500–1200)
  const slider = document.getElementById('slMktCap');
  slider.value = Math.max(500, Math.min(1200, mcMio));
  ovFilter();
}}

// === OVERVIEW TABLE ===
let ovFiltered = OV.slice();
let ovSortCol = 5;  // Default: Net% absteigend
let ovSortAsc = false;

function ovSort(col) {{
  if (ovSortCol === col) ovSortAsc = !ovSortAsc;
  else {{ ovSortCol = col; ovSortAsc = (col === 0 || col === 1 || col === 2 || col === 7); }}
  ovDoSort();
  ovRender();
}}

function ovDoSort() {{
  ovFiltered.sort((a, b) => {{
    let va = a[ovSortCol], vb = b[ovSortCol];
    if (typeof va === 'string') {{ va = va.toUpperCase(); vb = (vb||'').toUpperCase(); }}
    if (va < vb) return ovSortAsc ? -1 : 1;
    if (va > vb) return ovSortAsc ? 1 : -1;
    return 0;
  }});
}}

function ovFilter() {{
  const q = document.getElementById('ovSearch').value.toUpperCase();
  ovFiltered = OV.filter(r => {{
    // r: [sym, name, exchange, mktcap_B, rev_w%, net_w%, kurs, sector, sma50, sma200, gc, nearHi, perf3m]
    if (r[3] < slMktCapMin) return false;      // MktCap Slider
    if (r[4] < slRevMin) return false;          // Rev% Slider
    if (r[5] < slNetMin) return false;          // Net% Slider
    if (q && !r[0].includes(q) && !r[1].toUpperCase().includes(q)) return false;
    if (excludedSegments.has(r[7])) return false;  // Ausgeschlossene Segmente
    if (smaFilter50 && !r[8]) return false;
    if (smaFilter200 && !r[9]) return false;
    if (gcFilter && !r[10]) return false;       // Golden Cross
    if (nearHiFilter && !r[11]) return false;   // Nahe 52W-Hoch
    if (perf3mFilter && !r[12]) return false;   // 3M Perf > 0%
    return true;
  }});
  ovDoSort();
  ovRender();
  updateSegCounts();  // Segment-Counts nach jedem Filter-Wechsel neu berechnen
}}

// Live Trading Auswahl: Default ALLE aus — nur manuell einschalten
const FAATMAN_SYMS = new Set(FAATMAN_LIST);
let lvTrdSelected = new Set();  // Start: nichts ausgewaehlt
let lvTrdAllOn = false;

function lvTrdToggle(sym) {{
  if (lvTrdSelected.has(sym)) {{ lvTrdSelected.delete(sym); }}
  else {{ lvTrdSelected.add(sym); }}
  lvTrdUpdateCount();
}}

function faatmanSelectAll() {{
  // Toggle: wenn alle an → alle aus, sonst alle an
  let allOn = true;
  FAATMAN_SYMS.forEach(s => {{ if (!lvTrdSelected.has(s)) allOn = false; }});
  if (allOn) {{
    FAATMAN_SYMS.forEach(s => lvTrdSelected.delete(s));
    document.querySelectorAll('[data-faatman]').forEach(cb => {{ cb.checked = false; }});
  }} else {{
    FAATMAN_SYMS.forEach(s => lvTrdSelected.add(s));
    document.querySelectorAll('[data-faatman]').forEach(cb => {{ cb.checked = true; }});
  }}
  lvTrdUpdateCount();
}}

function lvTrdUpdateCount() {{
  const ovSel = ovFiltered.filter(r => lvTrdSelected.has(r[0])).length;
  let faSel = 0;
  FAATMAN_SYMS.forEach(s => {{ if (lvTrdSelected.has(s)) faSel++; }});
  document.getElementById('btnLvTrd').innerHTML = '&#9654; Live Trading (' + (ovSel + faSel) + ')';
}}

function lvTrdToggleAll() {{
  // Merke FAATMAN-Auswahl (unabhaengig vom Toggle)
  const faatmanKept = [];
  FAATMAN_SYMS.forEach(s => {{ if (lvTrdSelected.has(s)) faatmanKept.push(s); }});
  if (lvTrdAllOn) {{
    lvTrdSelected.clear();
    lvTrdAllOn = false;
  }} else {{
    for (const r of ovFiltered) {{ lvTrdSelected.add(r[0]); }}
    lvTrdAllOn = true;
  }}
  // FAATMAN-Auswahl wiederherstellen
  for (const s of faatmanKept) {{ lvTrdSelected.add(s); }}
  ovRender();
}}

function ovRowHtml(r) {{
  const revCls = r[4] >= 50 ? 'pos' : (r[4] >= 20 ? '' : 'neg');
  const netCls = r[5] >= 50 ? 'pos' : (r[5] >= 20 ? '' : 'neg');
  const s50 = r[8] ? '<td class="sma above">▲</td>' : '<td class="sma below">▼</td>';
  const s200 = r[9] ? '<td class="sma above">▲</td>' : '<td class="sma below">▼</td>';
  const chk = lvTrdSelected.has(r[0]) ? 'checked' : '';
  let h = '<tr>';
  h += '<td style="text-align:center;padding:0 2px;"><input type="checkbox" ' + chk
     + ' onchange="lvTrdToggle(\\\'' + r[0] + '\\\')" style="cursor:pointer;accent-color:var(--green);"></td>';
  h += '<td class="sym"><span class="fs-sym-link" onclick="showFS(\\\'' + r[0] + '\\\')">' + r[0] + '</span></td>';
  h += '<td class="name">' + r[1] + '</td>';
  h += '<td class="sec">' + (r[7]||'') + '</td>';
  h += '<td class="mc">$' + r[3].toFixed(1) + 'B</td>';
  h += '<td class="pct ' + revCls + '">' + (r[4]>=0?'+':'') + r[4].toFixed(0) + '%</td>';
  h += '<td class="pct ' + netCls + '">' + (r[5]>=0?'+':'') + r[5].toFixed(0) + '%</td>';
  h += '<td style="text-align:right">$' + r[6].toFixed(2) + '</td>';
  h += s50 + s200;
  h += '</tr>';
  return h;
}}

function ovRender() {{
  const tbody = document.getElementById('ovBody');
  document.getElementById('ovCount').textContent = ovFiltered.length + ' Ticker';
  let html = '';
  for (const r of ovFiltered) {{ html += ovRowHtml(r); }}
  tbody.innerHTML = html;
  lvTrdUpdateCount();
}}


// === SEGMENT COUNTS: leere Segmente ausgrauen ===
function updateSegCounts() {{
  // Zaehle Ticker pro Sektor — nach Slider + SMA + Suche, aber OHNE Segment-Filter
  const q = document.getElementById('ovSearch').value.toUpperCase();
  const counts = {{}};
  OV.filter(r => {{
    if (r[3] < slMktCapMin) return false;
    if (r[4] < slRevMin) return false;
    if (r[5] < slNetMin) return false;
    if (smaFilter50 && !r[8]) return false;
    if (smaFilter200 && !r[9]) return false;
    if (gcFilter && !r[10]) return false;
    if (nearHiFilter && !r[11]) return false;
    if (perf3mFilter && !r[12]) return false;
    if (q && !r[0].includes(q) && !r[1].toUpperCase().includes(q)) return false;
    return true;
  }}).forEach(r => {{ counts[r[7]] = (counts[r[7]] || 0) + 1; }});
  document.querySelectorAll('.seg-item:not(.all-item)').forEach(item => {{
    const seg = item.dataset.seg;
    const cnt = counts[seg] || 0;
    if (cnt === 0) {{
      item.classList.add('empty');
      item.title = seg + ': 0 Ticker';
    }} else {{
      item.classList.remove('empty');
      item.title = seg + ': ' + cnt + ' Ticker';
    }}
    // Anzahl unter den Label schreiben
    const label = item.querySelector('.seg-label');
    label.textContent = seg + (cnt > 0 ? ' (' + cnt + ')' : '');
  }});
}}

// === CSV DOWNLOAD ===
function ovDownloadCSV() {{
  // Header
  let csv = 'Ticker,Name,Boerse,Sektor,MktCap_B,Rev_YoY,Net_YoY,Kurs,SMA50,SMA200\\n';
  for (const r of ovFiltered) {{
    csv += r[0] + ',"' + r[1] + '",' + r[2] + ',' + (r[7]||'') + ','
         + r[3].toFixed(1) + ',' + r[4].toFixed(1) + ',' + r[5].toFixed(1) + ','
         + r[6].toFixed(2) + ',' + (r[8]?'Ja':'Nein') + ',' + (r[9]?'Ja':'Nein') + '\\n';
  }}
  const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'wachstumskandidaten_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
  URL.revokeObjectURL(url);
}}

// === LIVE TRADING EXPORT (angehakte OV-Ticker + angehakte FAATMAN) ===
function ovExportLiveTrading() {{
  const ovSyns = ovFiltered.filter(r => lvTrdSelected.has(r[0])).map(r => r[0]);
  const faSyns = [];
  FAATMAN_SYMS.forEach(s => {{ if (lvTrdSelected.has(s)) faSyns.push(s); }});
  // Zusammenfuegen, Duplikate entfernen (FAATMAN hinten anhaengen)
  const seen = new Set(ovSyns);
  const all = [...ovSyns];
  for (const s of faSyns) {{ if (!seen.has(s)) {{ all.push(s); seen.add(s); }} }}
  if (all.length === 0) {{ alert('Keine Ticker ausgewaehlt — bitte Lv Trd Checkboxen setzen.'); return; }}
  const tickers = all.join('\\n');
  const blob = new Blob([tickers + '\\n'], {{ type: 'text/plain;charset=utf-8;' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'live_watchlist_' + all.length + '.txt';
  a.click();
  URL.revokeObjectURL(url);
}}

// Initial: Slider-Defaults anwenden + Render
sliderChange();  // Setzt slMktCapMin/slRevMin/slNetMin und ruft ovFilter() auf

updateSegCounts();
// === FACTSHEET MODAL ===
const SECTOR_COLORS = {{
  'Technology':'#00b4d8','Semiconductors':'#7209b7','Healthcare':'#e63946',
  'Biotech':'#ff6b6b','Finance':'#2a9d8f','Energy':'#f77f00','Retail':'#e9c46a',
  'Industrial':'#457b9d','Consumer':'#a8dadc','Materials':'#6b705c',
  'Real Estate':'#b5838d','Transportation':'#264653','Telecom':'#3a86a8',
  'Education':'#bc6c25','Services':'#606c38','Other':'#555'
}};

function showFS(sym) {{
  const f = FS[sym];
  if (!f) return;
  const col = SECTOR_COLORS[f.s] || '#555';
  const initials = sym.slice(0, 2);
  const sma5 = f.s5 ? '<span style="color:var(--green)">&#9650;</span>' : '<span style="color:var(--accent)">&#9660;</span>';
  const sma2 = f.s2 ? '<span style="color:var(--green)">&#9650;</span>' : '<span style="color:var(--accent)">&#9660;</span>';
  const rwCls = (f.rw||0) >= 0 ? 'pos' : 'neg';
  const nwCls = (f.nw||0) >= 0 ? 'pos' : 'neg';
  const rwTxt = f.rw != null ? ((f.rw>=0?'+':'') + f.rw.toFixed(1) + '%') : '—';
  const nwTxt = f.nw != null ? ((f.nw>=0?'+':'') + f.nw.toFixed(1) + '%') : '—';

  let qRows = '';
  if (f.q && f.q.length) {{
    for (const r of f.q) {{
      const ryC = r[3] != null ? (r[3] >= 0 ? 'pos' : 'neg') : '';
      const nyC = r[4] != null ? (r[4] >= 0 ? 'pos' : 'neg') : '';
      const ryT = r[3] != null ? ((r[3]>=0?'+':'') + r[3].toFixed(1) + '%') : '—';
      const nyT = r[4] != null ? ((r[4]>=0?'+':'') + r[4].toFixed(1) + '%') : '—';
      qRows += '<tr><td>' + r[0] + '</td>'
        + '<td>$' + r[1].toLocaleString('en',{{minimumFractionDigits:1}}) + 'M</td>'
        + '<td class="yoy ' + ryC + '">' + ryT + '</td>'
        + '<td>$' + r[2].toLocaleString('en',{{minimumFractionDigits:1}}) + 'M</td>'
        + '<td class="yoy ' + nyC + '">' + nyT + '</td></tr>';
    }}
  }} else {{
    qRows = '<tr><td colspan="5" style="text-align:center;color:var(--dim)">Keine Quartalsdaten</td></tr>';
  }}

  document.getElementById('fsContent').innerHTML = ''
    + '<div class="fs-head">'
    + '  <div class="fs-icon" style="background:' + col + ';">' + initials + '</div>'
    + '  <div>'
    + '    <div class="fs-title">' + sym + ' &mdash; ' + f.n + '</div>'
    + '    <div class="fs-subtitle">' + f.x + ' &bull; ' + f.s + (f.si ? ' &bull; ' + f.si : '') + '</div>'
    + '  </div>'
    + '</div>'
    + '<div class="fs-metrics">'
    + '  <div class="fs-metric"><div class="label">MktCap</div><div class="value">$' + f.mc + 'B</div></div>'
    + '  <div class="fs-metric"><div class="label">Kurs</div><div class="value">$' + f.p.toFixed(2) + '</div></div>'
    + '  <div class="fs-metric"><div class="label">SMA50</div><div class="value">' + sma5 + '</div></div>'
    + '  <div class="fs-metric"><div class="label">SMA200</div><div class="value">' + sma2 + '</div></div>'
    + '</div>'
    + '<div class="fs-info">'
    + (f.fy ? '<span>FYE: ' + f.fy + '</span>' : '')
    + (f.ne ? '<span>N&auml;chste Earnings: <b style="color:var(--green2)">' + f.ne + '</b></span>' : '')
    + (f.cat ? '<span>SEC: ' + f.cat + '</span>' : '')
    + '</div>'
    + '<div class="fs-growth">'
    + '  <div class="item"><div class="label">Revenue Growth (gew.)</div><div class="value ' + rwCls + '">' + rwTxt + '</div></div>'
    + '  <div class="item"><div class="label">Net Income Growth (gew.)</div><div class="value ' + nwCls + '">' + nwTxt + '</div></div>'
    + '</div>'
    + '<div style="font-size:9px;color:var(--dim);margin:6px 0 2px;">QUARTALSZAHLEN (YoY)</div>'
    + '<table class="fs-qtable"><thead><tr>'
    + '<th>Quartal</th><th>Revenue</th><th>YoY</th><th>Net Income</th><th>YoY</th>'
    + '</tr></thead><tbody>' + qRows + '</tbody></table>';

  document.getElementById('fsOverlay').classList.add('open');
}}

function closeFS() {{
  document.getElementById('fsOverlay').classList.remove('open');
}}

// Escape + Klick ausserhalb schliesst Modal
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeFS(); }});
document.getElementById('fsOverlay').addEventListener('click', e => {{
  if (e.target.id === 'fsOverlay') closeFS();
}});

</script>

<!-- Factsheet Modal -->
<div class="fs-overlay" id="fsOverlay">
  <div class="fs-card">
    <button class="fs-close" onclick="closeFS()">&times;</button>
    <div id="fsContent"></div>
  </div>
</div>

</body>
</html>"""

    out_file = output_path / 'filing_cabinet.html'
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(html)

    return out_file


# ==============================================================
# HAUPTPROGRAMM
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='AI Artifakte — SEC Filing Cabinet Generator')
    parser.add_argument('--output', type=str, default=None, help='Ausgabeverzeichnis')
    parser.add_argument('--no-sec-db', action='store_true', help='Ohne SEC Filing DB')
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else SCRIPT_DIR

    print("[FC] === SEC Filing Cabinet Generator ===")

    # Trading DB
    ft_path = find_db(DB_SEARCH_PATHS)
    if not ft_path:
        print("[FC] FEHLER: feiertag_trading.db nicht gefunden!")
        sys.exit(1)
    ft_con = connect_ro(ft_path)
    if not ft_con:
        print(f"[FC] FEHLER: DB-Verbindung zu {ft_path}")
        sys.exit(1)
    print(f"[FC] Trading-DB: {ft_path}")

    # SEC DB
    sec_con = None
    if not args.no_sec_db:
        sec_path = find_db(SEC_DB_SEARCH_PATHS)
        if sec_path:
            sec_con = connect_ro(sec_path)
            print(f"[FC] SEC-DB: {sec_path}")
        else:
            print("[FC] HINWEIS: SEC Filing DB nicht gefunden, Trichter ohne SEC-Daten")

    # Daten laden
    print("[FC] Lade Trichter-Daten...")
    trichter = load_trichter(ft_con, sec_con)
    print(f"[FC] Stammdaten: {trichter['stammdaten']:,} | Rev+Net+MktCap: {trichter.get('rev_net_mktcap', '?'):,} | Daily Screen: {trichter.get('screened_with_fundamentals', '?'):,}")

    print("[FC] Lade Ticker-Daten + Filing-Status...")
    tickers = load_ticker_data(ft_con, sec_con)
    print(f"[FC] {len(tickers):,} Ticker geladen")

    # HTML generieren
    print("[FC] Generiere HTML...")
    out_file = generate_html(trichter, tickers, output_path, ft_con=ft_con)
    print(f"[FC] Fertig: {out_file}")
    print(f"[FC] === Filing Cabinet generiert ===")

    ft_con.close()
    if sec_con:
        sec_con.close()


if __name__ == '__main__':
    main()
