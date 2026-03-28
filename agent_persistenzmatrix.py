#!/usr/bin/env python3
"""
AI Artifakte — Agent B1: Persistenzmatrix
==========================================
Eigenstaendiger, robuster Agent fuer die Score-Persistenz-Heatmap.
Berechnet das vollstaendige 11-Punkte-Scoring aus daily_screen Rohdaten
+ Fundamentaldaten aus v_fin_perf_001 + Stammdaten.
Erzeugt eine interaktive HTML-Persistenzmatrix fuer Live-Trading.

Features:
  - Integrierte Score-Berechnung (kein Abhaengigkeit von vorberechneten Scores)
  - iCloud-kompatibler DB-Zugriff (immutable/readonly Fallbacks)
  - Dynamische Score-Schwellen aus feiertag_config
  - Persistenz-Score mit Trend-Analyse
  - Durchschnittlicher Score (Avg) als Trading-Kriterium (>=8 = Trading-Ready)
  - Kategorisierung: Live-Ready / Watchlist / Neue Signale
  - JSON-Export fuer Trading-Agent

Aufruf:
  python3 agent_persistenzmatrix.py                          # Standard: 20 Tage
  python3 agent_persistenzmatrix.py --days 30                # 30-Tage-Fenster
  python3 agent_persistenzmatrix.py --date 2026-03-28        # Bestimmtes Enddatum
  python3 agent_persistenzmatrix.py --db /pfad/zur/db        # Andere DB
  python3 agent_persistenzmatrix.py --output /pfad/output    # Anderes Output-Verzeichnis
  python3 agent_persistenzmatrix.py --json                   # Zusaetzlich JSON exportieren
"""

import sqlite3
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path


# ==============================================================
# KONFIGURATION (aus feiertag_config uebernommen)
# ==============================================================
SCORE_THRESHOLDS = {11: 8, 10: 7, 9: 7}
MIN_SCORE_TOP = 8
DEFAULT_DAYS = 20

# Liquiditaetsfilter (2-von-3 Regel)
SCREEN_MIN_PRICE = 20
SCREEN_MIN_VOLUME = 500_000
SCREEN_MIN_DOLLAR_VOL = 10_000_000
LIQUIDITY_TOLERANCE = 0.30

# Scoring-Schwellen
SCORE_NEAR_HIGH_PCT = 25
SCORE_ABOVE_LOW_PCT = 25
SCORE_REV_GROWTH_HIGH = 50
SCORE_REV_GROWTH_MED = 20
SCORE_EARN_GROWTH_MIN = 20
SCORE_MAX_DIVIDEND_PCT = 0.5
SCORE_TECH_SECTORS = ['Technology', 'Communication Services', 'Financial Services']
SCORE_MIN_PERF_3M = 0

# DB-Suchpfade
DEFAULT_DB_PATHS = [
    Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path.home() / 'Documents' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path(__file__).resolve().parent.parent / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
]


def score_threshold(max_possible):
    return SCORE_THRESHOLDS.get(max_possible, MIN_SCORE_TOP)


def liquidity_check(price, avg_vol):
    """2-von-3 Liquiditaetsregel: Preis, Volumen, Dollar-Volumen."""
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
# DB-VERBINDUNG (robust, iCloud-sicher)
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
    raise FileNotFoundError(
        "feiertag_trading.db nicht gefunden.\n" +
        "\n".join(f"  - {p}" for p in DEFAULT_DB_PATHS) +
        "\nBitte --db /pfad/zur/db angeben."
    )


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
    except Exception as e:
        print(f"  [B1] WARN: Fundamentaldaten nicht verfuegbar: {e}", flush=True)
        return {}


def load_sectors(con):
    try:
        rows = con.execute(
            "SELECT std_sym, std_sector FROM t_std_stammdaten WHERE std_sector IS NOT NULL AND std_sector != ''"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


# ==============================================================
# SCORING (11 Kriterien)
# ==============================================================
def score_ticker(raw, fundamentals, sectors, ticker):
    """Berechne Score /11 fuer einen Ticker-Tag.

    VORFILTER: Liquiditaetscheck (2-von-3 Regel)
    K01+K02: Phase-2     = 2 Pkt
    K03:     Golden Cross = 1 Pkt
    K04:     < 25% unter 52W-Hoch = 1 Pkt
    K05:     > 25% ueber 52W-Tief = 1 Pkt
    K06+K07: Revenue Growth YoY   = 1-2 Pkt
    K08:     Earnings Growth YoY  = 1 Pkt
    K09:     Keine Dividende      = 1 Pkt
    K10:     Tech Sektor          = 1 Pkt
    K11:     3M-Perf > 0%         = 1 Pkt
    """
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

    score += 1  # K09: TODO echte Dividenden-Daten

    sector = sectors.get(ticker, '')
    if sector in SCORE_TECH_SECTORS:
        score += 1

    p3m = raw.get('perf_3m')
    if p3m is not None and p3m > SCORE_MIN_PERF_3M:
        score += 1

    return score, score_max


# ==============================================================
# SCORING FUER ALLE TAGE
# ==============================================================
def compute_all_scores(raw_data, dates, fundamentals, sectors):
    scored = {}
    for ticker in set(raw_data.keys()):
        t_dates = raw_data[ticker]
        scored[ticker] = {}
        for d in dates:
            if d not in t_dates:
                continue
            raw = t_dates[d]
            s, mx = score_ticker(raw, fundamentals, sectors, ticker)
            if s is None:
                continue
            scored[ticker][d] = {
                'score': s, 'max': mx,
                'phase2': raw.get('phase2', 0),
                'kurs': raw.get('kurs'),
                'perf_1d': raw.get('perf_1d'),
                'perf_3m': raw.get('perf_3m'),
                'abst_hoch': raw.get('abst_hoch'),
                'golden_cross': raw.get('golden_cross'),
                'sma50': raw.get('sma50'),
                'sma200': raw.get('sma200'),
                'avg_vol': raw.get('avg_vol'),
            }
    return scored


def filter_qualified(scored, dates):
    qualified = {}
    for ticker, t_data in scored.items():
        for d in dates:
            info = t_data.get(d)
            if info and info['score'] >= score_threshold(info['max']):
                qualified[ticker] = t_data
                break
    return qualified


# ==============================================================
# PERSISTENZ-ANALYSE
# ==============================================================
def analyze_persistence(data, dates):
    analysis = {}
    for ticker, t_data in data.items():
        scores = []
        above_threshold_days = 0
        total_days = 0

        for d in dates:
            info = t_data.get(d)
            if info and info['score'] is not None:
                scores.append(info['score'])
                total_days += 1
                if info['score'] >= score_threshold(info['max']):
                    above_threshold_days += 1

        if not scores:
            continue

        last_day = None
        for d in reversed(dates):
            if d in t_data:
                last_day = t_data[d]
                break
        if not last_day:
            continue

        recent = scores[-5:] if len(scores) >= 5 else scores
        older = scores[-10:-5] if len(scores) >= 10 else scores[:max(1, len(scores)//2)]
        r_avg = sum(recent) / len(recent)
        o_avg = sum(older) / len(older) if older else r_avg
        trend = 'up' if r_avg > o_avg + 0.5 else ('down' if r_avg < o_avg - 0.5 else 'stable')

        streak = 0
        for d in reversed(dates):
            info = t_data.get(d)
            if info and info['score'] >= score_threshold(info['max']):
                streak += 1
            else:
                break

        persistence_pct = round(above_threshold_days / total_days * 100) if total_days > 0 else 0
        avg_score = round(sum(scores) / len(scores), 1)
        rank_score = (
            persistence_pct * 0.60 +
            (last_day['score'] / max(last_day['max'], 1) * 100) * 0.25 +
            min(streak / max(len(dates), 1) * 100, 100) * 0.15
        )

        analysis[ticker] = {
            'persistence_pct': persistence_pct,
            'above_threshold_days': above_threshold_days,
            'total_days': total_days,
            'avg_score': avg_score,
            'current_score': last_day['score'],
            'current_max': last_day['max'],
            'current_kurs': last_day.get('kurs'),
            'phase2': last_day.get('phase2'),
            'perf_3m': last_day.get('perf_3m'),
            'abst_hoch': last_day.get('abst_hoch'),
            'trend': trend,
            'streak': streak,
            'rank_score': round(rank_score, 1),
        }

    return analysis


# ==============================================================
# HTML GENERATION
# ==============================================================
def generate_html(data, dates, ranked_tickers, analysis, generation_date):
    trend_icons = {'up': '\u25b2', 'down': '\u25bc', 'stable': '\u25ba'}
    trend_colors = {'up': '#00b894', 'down': '#d63031', 'stable': '#fdcb6e'}

    html = []
    html.append('<!DOCTYPE html>')
    html.append('<html lang="de"><head><meta charset="utf-8">')
    html.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    html.append(f'<title>Persistenzmatrix \u2014 {generation_date}</title>')
    html.append("""<style>
:root {
  --bg: #0f0f1a; --surface: #1a1a2e; --surface2: #16213e;
  --text: #e8e8f0; --dim: #636e72; --accent: #e94560;
  --green: #00b894; --green2: #00cec9; --green3: #81ecec;
  --yellow: #ffeaa7; --orange: #fdcb6e; --red: #d63031;
  --blue: #74b9ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  background: var(--bg); color: var(--text);
  padding: 16px; font-size: 12px; line-height: 1.4;
}
h1 { color: var(--accent); font-size: 18px; margin-bottom: 4px; }
.meta { color: var(--dim); margin-bottom: 12px; font-size: 11px; }
.stats { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.stat-card {
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 6px; padding: 10px 14px; min-width: 120px;
}
.stat-card .label { color: var(--dim); font-size: 10px; text-transform: uppercase; }
.stat-card .value { font-size: 20px; font-weight: bold; color: var(--green); }
.stat-card .value.warn { color: var(--orange); }
.stat-card .value.bad { color: var(--red); }
.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.filters label { color: var(--dim); font-size: 11px; }
.filters select, .filters input {
  background: var(--surface); color: var(--text); border: 1px solid #2d3436;
  border-radius: 4px; padding: 4px 8px; font-size: 11px; font-family: inherit;
}
.matrix-wrap { overflow-x: auto; max-height: 80vh; overflow-y: auto; }
table { border-collapse: collapse; font-size: 11px; width: auto; }
th, td { padding: 3px 5px; text-align: center; border: 1px solid #222; white-space: nowrap; }
thead th {
  background: var(--surface2); position: sticky; top: 0; z-index: 10;
  font-size: 10px; color: var(--dim);
}
.col-ticker {
  text-align: left; font-weight: bold; background: var(--surface2);
  position: sticky; left: 0; z-index: 5; min-width: 55px; color: var(--blue);
}
thead .col-ticker { z-index: 15; }
.col-persist { min-width: 45px; font-weight: bold; }
.col-avg { min-width: 35px; font-weight: bold; font-size: 11px; }
.avg-high { color: #00b894; background: rgba(0,184,148,0.15); }
.avg-med { color: #81ecec; }
.avg-low { color: #636e72; }
.col-trend { min-width: 22px; }
.col-streak { min-width: 30px; }
.col-meta { font-size: 10px; color: var(--dim); min-width: 50px; }
.s11, .s10, .s9 { background: var(--green); color: #000; font-weight: bold; }
.s8 { background: var(--green2); color: #000; }
.s7 { background: var(--green3); color: #000; }
.s6 { background: var(--yellow); color: #000; }
.s5 { background: var(--orange); color: #000; }
.s4, .s3, .s2, .s1, .s0 { background: #5e1a1a; color: #ff7675; }
.empty { background: #1a1a1a; color: #444; }
.above-thresh { box-shadow: inset 0 0 0 1.5px #ffffffaa; }
.persist-bar {
  display: inline-block; height: 12px; border-radius: 2px;
  vertical-align: middle; margin-right: 3px;
}
.p-high { background: var(--green); }
.p-med { background: var(--yellow); }
.p-low { background: var(--red); }
.cat-row td {
  background: var(--surface); color: var(--accent); font-weight: bold;
  text-align: left; padding: 6px; font-size: 11px;
}
.badge-live {
  display: inline-block; background: var(--green); color: #000;
  font-size: 9px; font-weight: bold; padding: 1px 4px; border-radius: 3px; margin-left: 3px;
}
.badge-watch {
  display: inline-block; background: var(--yellow); color: #000;
  font-size: 9px; font-weight: bold; padding: 1px 4px; border-radius: 3px; margin-left: 3px;
}
@media (max-width: 768px) {
  body { padding: 8px; font-size: 11px; }
  .stats { gap: 8px; }
  .stat-card { min-width: 90px; padding: 6px 10px; }
}
</style></head><body>""")

    html.append(f'<h1>Persistenzmatrix \u2014 AI Artifakte</h1>')
    html.append(f'<div class="meta">Stand: {generation_date} | {len(dates)} B\u00f6rsentage | {len(ranked_tickers)} Ticker qualifiziert | Agent B1 v1.1</div>')

    total = len(ranked_tickers)
    live_ready = sum(1 for t in ranked_tickers
                     if analysis[t]['persistence_pct'] >= 70
                     and analysis[t]['current_score'] >= score_threshold(analysis[t]['current_max'] or 11))
    trading_ready = sum(1 for t in ranked_tickers if analysis[t]['avg_score'] >= 8.0 and analysis[t]['persistence_pct'] >= 70)
    trending_up = sum(1 for t in ranked_tickers if analysis[t]['trend'] == 'up')
    avg_persist = round(sum(analysis[t]['persistence_pct'] for t in ranked_tickers) / total) if total > 0 else 0

    html.append('<div class="stats">')
    html.append(f'<div class="stat-card"><div class="label">Qualifiziert</div><div class="value">{total}</div></div>')
    cls = '' if live_ready >= 10 else ('warn' if live_ready >= 5 else 'bad')
    html.append(f'<div class="stat-card"><div class="label">Live-Ready</div><div class="value {cls}">{live_ready}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">\u2205 \u2265 8 Trading</div><div class="value">{trading_ready}</div></div>')
    html.append(f'<div class="stat-card"><div class="label">Trend \u25b2</div><div class="value">{trending_up}</div></div>')
    cls2 = '' if avg_persist >= 50 else ('warn' if avg_persist >= 30 else 'bad')
    html.append(f'<div class="stat-card"><div class="label">\u2205 Persistenz</div><div class="value {cls2}">{avg_persist}%</div></div>')
    html.append('</div>')

    html.append('''<div class="filters">
      <label>Filter:</label>
      <select id="filterCat" onchange="applyFilter()">
        <option value="all">Alle</option>
        <option value="live">Live-Ready (\u226570%)</option>
        <option value="watch">Watchlist (40-69%)</option>
        <option value="new">Neue Signale (\u226439%)</option>
      </select>
      <select id="filterTrend" onchange="applyFilter()">
        <option value="all">Alle Trends</option>
        <option value="up">\u25b2 Steigend</option>
        <option value="stable">\u25ba Stabil</option>
        <option value="down">\u25bc Fallend</option>
      </select>
      <select id="filterAvg" onchange="applyFilter()">
        <option value="all">Alle \u2205</option>
        <option value="8">\u2205 \u2265 8 (Trading)</option>
        <option value="7">\u2205 \u2265 7</option>
      </select>
      <input type="text" id="filterTicker" placeholder="Ticker suchen..." oninput="applyFilter()" style="width:100px;">
    </div>''')

    html.append('<div class="matrix-wrap"><table id="matrix"><thead><tr>')
    html.append('<th class="col-ticker">Ticker</th>')
    html.append('<th class="col-persist">P%</th>')
    html.append('<th class="col-avg" title="Durchschnittlicher Score ueber alle Tage">\u2205</th>')
    html.append('<th class="col-trend">T</th>')
    html.append('<th class="col-streak">Str</th>')
    html.append('<th class="col-meta">Kurs</th>')
    html.append('<th class="col-meta">vHoch</th>')
    for d in dates:
        dt = datetime.strptime(d, '%Y-%m-%d')
        wd = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][dt.weekday()]
        html.append(f'<th>{d[5:]}<br><span style="font-size:9px;color:#555">{wd}</span></th>')
    html.append('</tr></thead><tbody>')

    categories = {'live': [], 'watch': [], 'new': []}
    cat_labels = {
        'live': 'LIVE-READY \u2014 Persistenz \u2265 70%, aktuell \u00fcber Schwelle',
        'watch': 'WATCHLIST \u2014 Persistenz 40-69%',
        'new': 'NEUE SIGNALE \u2014 Persistenz < 40%',
    }

    for ticker in ranked_tickers:
        a = analysis[ticker]
        pp = a['persistence_pct']
        above_now = a['current_score'] >= score_threshold(a['current_max'] or 11)
        if pp >= 70 and above_now:
            categories['live'].append(ticker)
        elif pp >= 40:
            categories['watch'].append(ticker)
        else:
            categories['new'].append(ticker)

    num_cols = 7 + len(dates)

    for cat_key in ['live', 'watch', 'new']:
        tickers = categories[cat_key]
        if not tickers:
            continue

        html.append(f'<tr class="cat-row" data-cat="{cat_key}"><td colspan="{num_cols}">{cat_labels[cat_key]} ({len(tickers)})</td></tr>')

        for ticker in tickers:
            a = analysis[ticker]
            t_data = data.get(ticker, {})
            trend_icon = trend_icons.get(a['trend'], '?')
            trend_col = trend_colors.get(a['trend'], '#fff')

            pp = a['persistence_pct']
            p_cls = 'p-high' if pp >= 70 else ('p-med' if pp >= 40 else 'p-low')
            bar_w = max(2, int(pp * 0.35))

            badge = ''
            if cat_key == 'live':
                badge = '<span class="badge-live">LIVE</span>'
            elif cat_key == 'watch':
                badge = '<span class="badge-watch">WATCH</span>'

            kurs_str = f"${a['current_kurs']:.2f}" if a['current_kurs'] else '-'
            hoch_str = f"{a['abst_hoch']:.0f}%" if a['abst_hoch'] is not None else '-'
            avg_s = a['avg_score']
            avg_cls = 'avg-high' if avg_s >= 8 else ('avg-med' if avg_s >= 7 else 'avg-low')

            html.append(f'<tr data-cat="{cat_key}" data-trend="{a["trend"]}" data-ticker="{ticker}" data-avg="{avg_s:.1f}">')
            html.append(f'<td class="col-ticker">{ticker}{badge}</td>')
            html.append(f'<td class="col-persist"><span class="persist-bar {p_cls}" style="width:{bar_w}px"></span>{pp}%</td>')
            html.append(f'<td class="col-avg {avg_cls}">{avg_s:.1f}</td>')
            html.append(f'<td class="col-trend" style="color:{trend_col}">{trend_icon}</td>')
            html.append(f'<td class="col-streak">{a["streak"]}d</td>')
            html.append(f'<td class="col-meta">{kurs_str}</td>')
            html.append(f'<td class="col-meta">{hoch_str}</td>')

            for d in dates:
                info = t_data.get(d)
                if info and info['score'] is not None:
                    s = info['score']
                    mx = info['max']
                    cls = f's{min(s, 11)}'
                    above = ' above-thresh' if s >= score_threshold(mx) else ''
                    html.append(f'<td class="{cls}{above}">{s}/{mx}</td>')
                else:
                    html.append('<td class="empty">\u00b7</td>')

            html.append('</tr>')

    html.append('</tbody></table></div>')

    html.append("""<script>
function applyFilter() {
  const cat = document.getElementById('filterCat').value;
  const trend = document.getElementById('filterTrend').value;
  const avgMin = document.getElementById('filterAvg').value;
  const search = document.getElementById('filterTicker').value.toUpperCase();
  document.querySelectorAll('#matrix tbody tr').forEach(row => {
    if (row.classList.contains('cat-row')) {
      row.style.display = (cat === 'all' || cat === row.dataset.cat) ? '' : 'none';
      return;
    }
    let show = true;
    if (cat !== 'all' && row.dataset.cat !== cat) show = false;
    if (trend !== 'all' && row.dataset.trend !== trend) show = false;
    if (avgMin !== 'all' && parseFloat(row.dataset.avg || 0) < parseFloat(avgMin)) show = false;
    if (search && !(row.dataset.ticker || '').includes(search)) show = false;
    row.style.display = show ? '' : 'none';
  });
}
</script>""")

    html.append(f'<div class="meta" style="margin-top:12px;">AI Artifakte \u2014 Agent B1 Persistenzmatrix v1.1 | Generiert: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    html.append('</body></html>')
    return '\n'.join(html)


# ==============================================================
# JSON EXPORT
# ==============================================================
def generate_json(ranked_tickers, analysis, dates, data):
    output = {
        'generated': datetime.now().isoformat(),
        'trading_days': dates,
        'num_days': len(dates),
        'summary': {
            'total_qualified': len(ranked_tickers),
            'live_ready': sum(1 for t in ranked_tickers
                             if analysis[t]['persistence_pct'] >= 70
                             and analysis[t]['current_score'] >= score_threshold(analysis[t]['current_max'] or 11)),
            'trading_ready_avg8': sum(1 for t in ranked_tickers
                                      if analysis[t]['avg_score'] >= 8.0
                                      and analysis[t]['persistence_pct'] >= 70),
            'trending_up': sum(1 for t in ranked_tickers if analysis[t]['trend'] == 'up'),
        },
        'tickers': {}
    }
    for ticker in ranked_tickers:
        a = analysis[ticker]
        t_data = data.get(ticker, {})
        daily = []
        for d in dates:
            info = t_data.get(d)
            if info:
                daily.append({'date': d, 'score': info['score'], 'max': info['max']})
            else:
                daily.append({'date': d, 'score': None, 'max': None})
        output['tickers'][ticker] = {
            'rank_score': a['rank_score'],
            'persistence_pct': a['persistence_pct'],
            'avg_score': a['avg_score'],
            'trend': a['trend'],
            'streak': a['streak'],
            'current_score': a['current_score'],
            'current_max': a['current_max'],
            'current_kurs': a['current_kurs'],
            'phase2': a.get('phase2'),
            'perf_3m': a.get('perf_3m'),
            'abst_hoch': a.get('abst_hoch'),
            'daily_scores': daily,
        }
    return output


# ==============================================================
# HAUPTPROGRAMM
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='AI Artifakte \u2014 Agent B1: Persistenzmatrix')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS, help='Anzahl Boersentage')
    parser.add_argument('--date', default=date.today().isoformat(), help='Enddatum')
    parser.add_argument('--db', help='Pfad zur feiertag_trading.db')
    parser.add_argument('--output', help='Output-Verzeichnis')
    parser.add_argument('--json', action='store_true', help='JSON exportieren')
    parser.add_argument('--quiet', action='store_true', help='Nur Fehler ausgeben')
    args = parser.parse_args()

    def log(msg):
        if not args.quiet:
            print(f"  [B1] {msg}", flush=True)

    log("=== Persistenzmatrix-Agent gestartet ===")

    try:
        db_path = find_database(args.db)
        log(f"DB: {db_path}")
    except FileNotFoundError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        con = connect_db(db_path)
        log("DB-Verbindung OK")
    except ConnectionError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)

    dates = load_trading_days(con, args.date, args.days)
    if not dates:
        log("FEHLER: Keine Daten in daily_screen")
        con.close()
        sys.exit(1)
    log(f"Zeitraum: {dates[0]} bis {dates[-1]} ({len(dates)} Tage)")

    log("Lade Rohdaten...")
    raw_data = load_raw_data(con, dates)
    log(f"Rohdaten: {len(raw_data)} Ticker")

    log("Lade Fundamentaldaten...")
    fundamentals = load_fundamentals(con)
    log(f"Fundamentals: {len(fundamentals)} Ticker mit Daten")

    log("Lade Sektoren...")
    sectors = load_sectors(con)
    log(f"Sektoren: {len(sectors)} Ticker mit Sektor")
    con.close()

    log("Berechne Scores /11 fuer alle Ticker und Tage...")
    scored = compute_all_scores(raw_data, dates, fundamentals, sectors)
    log(f"Scores berechnet: {len(scored)} Ticker")

    qualified = filter_qualified(scored, dates)
    log(f"Qualifiziert (>= Schwelle an mind. 1 Tag): {len(qualified)} Ticker")

    if not qualified:
        log("WARNUNG: Keine Ticker haben die Score-Schwelle erreicht")

    analysis = analyze_persistence(qualified, dates)
    ranked = sorted(analysis.keys(), key=lambda t: -analysis[t]['rank_score'])
    log(f"Analysiert: {len(ranked)} Ticker mit Persistenz-Ranking")

    live_ready = [t for t in ranked
                  if analysis[t]['persistence_pct'] >= 70
                  and analysis[t]['current_score'] >= score_threshold(analysis[t]['current_max'] or 11)]
    trading_avg8 = [t for t in live_ready if analysis[t]['avg_score'] >= 8.0]
    log(f"Live-Ready: {len(live_ready)} Ticker")
    log(f"Trading-Ready (Avg>=8): {len(trading_avg8)} Ticker")
    if trading_avg8:
        top5 = ', '.join(
            f"{t} (\u2205{analysis[t]['avg_score']:.1f}, {analysis[t]['current_score']}/{analysis[t]['current_max']})"
            for t in trading_avg8[:5]
        )
        log(f"  Top 5: {top5}")

    out_dir = Path(args.output) if args.output else Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)

    html_content = generate_html(qualified, dates, ranked, analysis, args.date)
    html_path = out_dir / 'persistenzmatrix.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    log(f"HTML: {html_path}")

    if args.json:
        json_data = generate_json(ranked, analysis, dates, qualified)
        json_path = out_dir / 'persistenzmatrix.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        log(f"JSON: {json_path}")

    log("=== Persistenzmatrix fertig ===")
    return {'html_path': str(html_path), 'num_tickers': len(ranked), 'live_ready': len(live_ready), 'dates': dates}


if __name__ == '__main__':
    result = main()
