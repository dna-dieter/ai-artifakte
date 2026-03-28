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

# ==============================================================
# KONFIGURATION
# ==============================================================
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
        trichter['sec_gesamt'] = sc.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        trichter['sec_exchange'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE exchange IS NOT NULL"
        ).fetchone()[0]
        trichter['sec_otc'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE exchange = 'OTC'"
        ).fetchone()[0]
        trichter['sec_listed'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE exchange IS NOT NULL AND exchange != 'OTC'"
        ).fetchone()[0]
        trichter['sec_facts'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1"
        ).fetchone()[0]
        trichter['sec_listed_facts'] = sc.execute(
            "SELECT COUNT(*) FROM companies WHERE has_facts = 1 AND exchange IS NOT NULL AND exchange != 'OTC'"
        ).fetchone()[0]
    else:
        trichter['sec_gesamt'] = 0

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

    # Daily Screen
    trichter['daily_screen'] = cur.execute("SELECT COUNT(DISTINCT ticker) FROM daily_screen").fetchone()[0]
    trichter['daily_screen_last'] = cur.execute("SELECT MAX(datum) FROM daily_screen").fetchone()[0]

    # Finanzdaten-Abdeckung
    trichter['fin_tickers'] = cur.execute("SELECT COUNT(DISTINCT fin_sym) FROM t_fin_financials").fetchone()[0]

    return trichter


def load_ticker_data(ft_con, sec_con):
    """Lade alle Ticker mit Filing-Status."""
    cur = ft_con.cursor()

    # Stammdaten
    tickers = {}
    for r in cur.execute("""
        SELECT std_sym, std_name, std_exchange, std_fin_type, std_fiscal_year_end
        FROM t_std_stammdaten
        ORDER BY std_sym
    """):
        tickers[r[0]] = {
            'sym': r[0],
            'name': r[1] or '',
            'exchange': r[2] or '',
            'fin_type': r[3] or '',
            'fye': r[4] or '',
            'quarters': {},
        }

    # Filing-Status pro Quartal
    for r in cur.execute("""
        SELECT fin_sym, fin_qtr, fin_qlf_qtr_rev, fin_filed_10q, fin_filed_10k
        FROM t_fin_financials
        WHERE fin_qtr IN ({})
    """.format(','.join(f"'{q}'" for q in DISPLAY_QUARTERS))):
        sym = r[0]
        if sym in tickers:
            tickers[sym]['quarters'][r[1]] = {
                'qlf': r[2] or 'd',
                'has_10q': bool(r[3]),
                'has_10k': bool(r[4]),
            }

    # SEC DB: zusaetzliche Info (category, SIC)
    if sec_con:
        sc = sec_con.cursor()
        for r in sc.execute("SELECT ticker, category, sic_desc, has_facts FROM companies WHERE ticker IS NOT NULL"):
            if r[0] in tickers:
                cat = (r[1] or '').split('<br>')[0].strip()
                tickers[r[0]]['sec_category'] = cat
                tickers[r[0]]['sec_industry'] = r[2] or ''
                tickers[r[0]]['sec_has_facts'] = bool(r[3])

    return tickers


# ==============================================================
# HTML GENERIEREN
# ==============================================================
def generate_html(trichter, tickers, output_path):
    """Generiere die Filing Cabinet HTML-Seite."""

    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    total = len(tickers)

    # Sortierte Ticker-Liste als JSON fuer JS
    ticker_list = []
    for sym in sorted(tickers.keys()):
        t = tickers[sym]
        # Filing-Status als kompaktes Array: [qlf, has_10q, has_10k] pro Quartal
        qdata = []
        for q in DISPLAY_QUARTERS:
            qi = t['quarters'].get(q, {'qlf': 'd', 'has_10q': False, 'has_10k': False})
            qdata.append([qi['qlf'], qi['has_10q'], qi['has_10k']])

        ticker_list.append([
            t['sym'],
            t['name'][:40],
            t['exchange'],
            t['fin_type'],
            t['fye'],
            qdata,
        ])

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
  max-width: 1200px; margin: 0 auto; padding: 16px;
  font-size: 12px;
}}
h1 {{ color: var(--accent); font-size: 20px; margin-bottom: 2px; }}
.subtitle {{ color: var(--dim); font-size: 10px; margin-bottom: 16px; }}

/* ===== TRICHTER ===== */
.funnel {{
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 8px; padding: 16px; margin-bottom: 16px;
}}
.funnel-title {{ color: var(--accent); font-size: 13px; font-weight: bold; margin-bottom: 10px; }}
.funnel-steps {{
  display: flex; align-items: center; gap: 0; flex-wrap: wrap;
  justify-content: center;
}}
.funnel-step {{
  text-align: center; padding: 8px 12px; position: relative;
  min-width: 100px;
}}
.funnel-step .fn {{ font-size: 20px; font-weight: bold; color: var(--green2); }}
.funnel-step .fl {{ font-size: 9px; color: var(--dim); margin-top: 2px; }}
.funnel-arrow {{ color: var(--dim); font-size: 18px; padding: 0 2px; }}
.funnel-removed {{ color: var(--red); font-size: 9px; }}

/* Stats */
.stats {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }}
.stat {{
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 6px; padding: 10px 14px; flex: 1; min-width: 140px;
}}
.stat .sv {{ font-size: 18px; font-weight: bold; color: var(--green2); }}
.stat .sl {{ font-size: 9px; color: var(--dim); margin-top: 2px; }}

/* ===== FILTER ===== */
.filter-bar {{
  display: flex; gap: 8px; align-items: center; margin-bottom: 12px;
  flex-wrap: wrap;
}}
.filter-bar input {{
  font-family: inherit; font-size: 12px; padding: 6px 10px;
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 5px; width: 200px;
}}
.filter-bar input:focus {{ border-color: var(--accent); outline: none; }}
.filter-bar select {{
  font-family: inherit; font-size: 11px; padding: 5px 8px;
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 5px;
}}
.filter-count {{ color: var(--dim); font-size: 11px; margin-left: auto; }}

/* Letter bar */
.letter-bar {{ display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 10px; }}
.letter-btn {{
  font-family: inherit; font-size: 11px; font-weight: bold;
  width: 26px; height: 26px; display: flex; align-items: center;
  justify-content: center; border-radius: 4px; border: 1px solid #2d3436;
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

/* Footer */
.footer {{ margin-top: 16px; text-align: center; color: var(--dim); font-size: 10px; }}

/* Responsive */
@media (max-width: 800px) {{
  .funnel-steps {{ flex-direction: column; gap: 4px; }}
  .funnel-arrow {{ transform: rotate(90deg); }}
}}
</style>
</head>
<body>

<h1>SEC Filing Cabinet</h1>
<div class="subtitle">
  AI Artifakte — Datengrundlage &amp; Transparenz | Stand: {now} | DB: {tr.get('daily_screen_last', '?')}
</div>

<!-- TRICHTER -->
<div class="funnel">
  <div class="funnel-title">Ticker-Universum: Von der SEC-Registrierung zum aktiven Screening</div>
  <div class="funnel-steps">
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_gesamt', '?'):,}</div>
      <div class="fl">SEC registriert</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_exchange', '?'):,}</div>
      <div class="fl">mit Boerse</div>
      <div class="funnel-removed">−{tr.get('sec_gesamt', 0) - tr.get('sec_exchange', 0):,} ohne Boerse</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_listed', '?'):,}</div>
      <div class="fl">NYSE/NASDAQ/AMEX</div>
      <div class="funnel-removed">−{tr.get('sec_otc', 0):,} OTC</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('sec_listed_facts', '?'):,}</div>
      <div class="fl">mit SEC-Facts</div>
      <div class="funnel-removed">−{tr.get('sec_listed', 0) - tr.get('sec_listed_facts', 0):,} ohne Facts</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('stammdaten', '?'):,}</div>
      <div class="fl">Trading-DB</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('tradeable', '?'):,}</div>
      <div class="fl">analysierbar</div>
      <div class="funnel-removed">−{tr['warrants']} Warrants, −{tr['no_data']} noData, −{tr['no_sec']} noSEC</div>
    </div>
    <div class="funnel-arrow">→</div>
    <div class="funnel-step">
      <div class="fn">{tr.get('daily_screen', '?'):,}</div>
      <div class="fl">Daily Screen</div>
    </div>
  </div>
</div>

<!-- STATS -->
<div class="stats">
  <div class="stat">
    <div class="sv">{tr.get('fin_tickers', 0):,}</div>
    <div class="sl">Ticker mit Finanzdaten</div>
  </div>
  <div class="stat">
    <div class="sv">{tr.get('stammdaten', 0):,}</div>
    <div class="sl">Stammdaten gesamt</div>
  </div>
  <div class="stat">
    <div class="sv">{sum(1 for t in tickers.values() if any(q.get('has_10q') for q in t['quarters'].values())):,}</div>
    <div class="sl">mit mind. 1x 10-Q</div>
  </div>
  <div class="stat">
    <div class="sv">{sum(1 for t in tickers.values() if any(q.get('has_10k') for q in t['quarters'].values())):,}</div>
    <div class="sl">mit mind. 1x 10-K</div>
  </div>
</div>

<!-- FILTER -->
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
    <option value="std">std</option>
    <option value="biotech">biotech</option>
    <option value="pharma">pharma</option>
    <option value="bank">bank</option>
    <option value="holding">holding</option>
    <option value="investment">investment</option>
    <option value="mining">mining</option>
    <option value="adr">adr</option>
    <option value="non-std">non-std</option>
    <option value="dec_52w">dec_52w</option>
    <option value="no_data">no_data</option>
    <option value="no_sec">no_sec</option>
    <option value="warrant">warrant</option>
  </select>
  <select id="filterFiling" onchange="applyFilter()">
    <option value="">Alle Filing-Status</option>
    <option value="complete">10-Q komplett (alle 8 Qtrs)</option>
    <option value="partial">10-Q teilweise</option>
    <option value="missing">Keine 10-Q</option>
    <option value="has_csec">Hat c-sec Quartale</option>
  </select>
  <span class="filter-count" id="filterCount"></span>
</div>

<!-- TABLE -->
<div class="table-wrap" style="max-height: 70vh; overflow-y: auto;">
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

<div class="footer">
  AI Artifakte — SEC Filing Cabinet v1.0 | {total:,} Ticker | Generiert: {now}
</div>

<script>
const QTRS = {json.dumps(DISPLAY_QUARTERS)};
const DATA = {json.dumps(ticker_list, separators=(',', ':'))};
// DATA format: [sym, name, exchange, fin_type, fye, [[qlf,has10q,has10k], ...x8]]

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

  filtered = DATA.filter(r => {{
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

// Initial
sortFiltered();
render();
</script>
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
    print(f"[FC] Stammdaten: {trichter['stammdaten']:,} | Tradeable: {trichter['tradeable']:,} | Daily Screen: {trichter['daily_screen']:,}")

    print("[FC] Lade Ticker-Daten + Filing-Status...")
    tickers = load_ticker_data(ft_con, sec_con)
    print(f"[FC] {len(tickers):,} Ticker geladen")

    # HTML generieren
    print("[FC] Generiere HTML...")
    out_file = generate_html(trichter, tickers, output_path)
    print(f"[FC] Fertig: {out_file}")
    print(f"[FC] === Filing Cabinet generiert ===")

    ft_con.close()
    if sec_con:
        sec_con.close()


if __name__ == '__main__':
    main()
