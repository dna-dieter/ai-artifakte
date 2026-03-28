#!/usr/bin/env python3
"""
AI Artifakte — Agent-Dashboard (Lokale Steuerung)
===================================================
Lokale Web-Oberflaeche zur Steuerung der Trading-Pipeline.

Pipeline:
  Step 1: DB-Status pruefen
  Step 2: Persistenzmatrix generieren (Agent B1)
  Step 3: Pre-Market Scan (Agent B2)
  Step 4: TWS-Excel Bridge (Agent B3)
  Step 5: Dateien pruefen & oeffnen

USAGE:
  python3 agent_dashboard.py                 # Standard (Port 5050)
  python3 agent_dashboard.py --port 8080     # Anderer Port
  python3 agent_dashboard.py --debug         # Debug-Modus

Dann im Browser: http://localhost:5050
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import Flask, render_template_string, jsonify, request

# ==============================================================
# KONFIGURATION
# ==============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
DB_SEARCH_PATHS = [
    Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    Path.home() / 'Documents' / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
    SCRIPT_DIR.parent / 'Feiertag_Trading_Academy' / 'datenbank' / 'feiertag_trading.db',
]

AGENTS = {
    'b1': {'name': 'Persistenzmatrix', 'script': 'agent_persistenzmatrix.py',
           'args': ['--json'], 'outputs': ['persistenzmatrix.html', 'persistenzmatrix.json']},
    'b2': {'name': 'Pre-Market Scan', 'script': 'agent_premarket_scan.py',
           'args': ['--json'], 'outputs': ['premarket_scan.html', 'premarket_scan.json']},
    'b3': {'name': 'TWS-Excel Bridge', 'script': 'agent_tws_excel.py',
           'args': ['--dry-run'], 'outputs': []},  # dynamisch
}

# Globaler Status
pipeline_state = {
    'steps': {
        'db':   {'status': 'pending', 'message': '', 'data': {}},
        'b1':   {'status': 'pending', 'message': '', 'data': {}},
        'b2':   {'status': 'pending', 'message': '', 'data': {}},
        'b3':   {'status': 'pending', 'message': '', 'data': {}},
        'review': {'status': 'pending', 'message': '', 'data': {}},
    },
    'log': [],
    'running': None,
}
state_lock = threading.Lock()

app = Flask(__name__)


# ==============================================================
# HILFSFUNKTIONEN
# ==============================================================
def find_db():
    for p in DB_SEARCH_PATHS:
        if p.exists():
            return p
    return None


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
    return None


def add_log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    with state_lock:
        pipeline_state['log'].append(f'[{ts}] {msg}')
        if len(pipeline_state['log']) > 200:
            pipeline_state['log'] = pipeline_state['log'][-100:]


def set_step(step, status, message='', data=None):
    with state_lock:
        pipeline_state['steps'][step]['status'] = status
        pipeline_state['steps'][step]['message'] = message
        if data:
            pipeline_state['steps'][step]['data'].update(data)
    # Persistiere Status fuer Claude-Chat-Integration
    save_pipeline_status(step, status, message, data)


def save_pipeline_status(step=None, status=None, message=None, data=None):
    """Schreibt den Pipeline-Status in eine JSON-Datei, damit Claude im Chat
    jederzeit den aktuellen Stand lesen und besprechen kann."""
    status_file = SCRIPT_DIR / 'pipeline_status.json'
    try:
        with state_lock:
            snapshot = {
                'updated': datetime.now().isoformat(),
                'next_trading_day': next_trading_day_str(),
                'steps': {},
                'last_event': {
                    'step': step, 'status': status,
                    'message': message, 'data': data,
                    'timestamp': datetime.now().isoformat(),
                },
                'log_tail': pipeline_state['log'][-20:],
            }
            for k, v in pipeline_state['steps'].items():
                snapshot['steps'][k] = {
                    'status': v['status'],
                    'message': v['message'],
                    'data': v['data'],
                }
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        pass  # Nicht blockierend


def next_trading_day_str():
    d = next_trading_day()
    weekdays = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
    return f'{weekdays[d.weekday()]} {d.strftime("%d.%m.%Y")}'


def next_trading_day():
    d = date.today()
    if d.weekday() >= 5:
        d += timedelta(days=(7 - d.weekday()))
    return d


# ==============================================================
# PIPELINE-SCHRITTE
# ==============================================================
def run_db_check():
    add_log('DB-Status wird geprueft...')
    set_step('db', 'running', 'Pruefe Datenbank...')

    db_path = find_db()
    if not db_path:
        set_step('db', 'error', 'DB nicht gefunden!')
        add_log('FEHLER: feiertag_trading.db nicht gefunden')
        return False

    con = connect_db(db_path)
    if not con:
        set_step('db', 'error', f'Verbindung fehlgeschlagen: {db_path}')
        add_log(f'FEHLER: DB-Verbindung zu {db_path}')
        return False

    try:
        # Letztes Datum
        row = con.execute("SELECT MAX(datum), COUNT(DISTINCT datum), COUNT(DISTINCT ticker) FROM daily_screen").fetchone()
        last_date = row[0] or '?'
        num_days = row[1] or 0
        num_tickers = row[2] or 0

        # Fundamentals
        fund_row = con.execute("SELECT COUNT(DISTINCT sym) FROM v_fin_perf_001 WHERE status='reported'").fetchone()
        num_fund = fund_row[0] if fund_row else 0

        # SEC DB Groesse
        db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 1)

        con.close()

        data = {
            'db_path': str(db_path),
            'last_date': last_date,
            'num_days': num_days,
            'num_tickers': num_tickers,
            'num_fundamentals': num_fund,
            'db_size_mb': db_size_mb,
        }

        # Pruefe ob aktuell
        today = date.today()
        last = datetime.strptime(last_date, '%Y-%m-%d').date()
        days_old = (today - last).days
        # Wochenende beruecksichtigen
        if today.weekday() == 5:
            days_old -= 1
        elif today.weekday() == 6:
            days_old -= 2

        if days_old <= 1:
            status_msg = f'Aktuell ({last_date})'
            set_step('db', 'done', status_msg, data)
        elif days_old <= 3:
            status_msg = f'{days_old} Tage alt ({last_date})'
            set_step('db', 'warning', status_msg, data)
        else:
            status_msg = f'VERALTET: {days_old} Tage alt ({last_date})'
            set_step('db', 'warning', status_msg, data)

        add_log(f'DB OK: {last_date}, {num_tickers} Ticker, {num_fund} Fundamentals, {db_size_mb} MB')
        return True

    except Exception as e:
        con.close()
        set_step('db', 'error', str(e))
        add_log(f'FEHLER: {e}')
        return False


def run_agent(agent_key, extra_args=None):
    agent = AGENTS[agent_key]
    script = SCRIPT_DIR / agent['script']

    if not script.exists():
        set_step(agent_key, 'error', f'Script nicht gefunden: {agent["script"]}')
        add_log(f'FEHLER: {agent["script"]} existiert nicht')
        return False

    add_log(f'Starte {agent["name"]}...')
    set_step(agent_key, 'running', f'{agent["name"]} laeuft...')

    cmd = [sys.executable, str(script)] + agent['args']
    if extra_args:
        cmd.extend(extra_args)

    # Fuer B1: Datum-Argument
    db_data = pipeline_state['steps']['db'].get('data', {})
    last_date = db_data.get('last_date')
    if last_date and agent_key in ('b1', 'b2'):
        cmd.extend(['--date', last_date])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(SCRIPT_DIR)
        )

        output = result.stdout + result.stderr
        for line in output.strip().split('\n'):
            if line.strip():
                add_log(f'  {line.strip()}')

        if result.returncode == 0:
            # Outputs pruefen
            outputs_found = []
            for fn in agent['outputs']:
                fp = SCRIPT_DIR / fn
                if fp.exists():
                    outputs_found.append(fn)

            # B3: Excel dynamisch finden
            if agent_key == 'b3':
                for f in SCRIPT_DIR.glob('trading_orders_*.xlsx'):
                    outputs_found.append(f.name)

            data = {'outputs': outputs_found}

            # Parse-Zusammenfassung aus Output
            for line in output.split('\n'):
                if 'Live-Ready:' in line:
                    data['live_ready'] = line.split('Live-Ready:')[1].strip()
                if 'Kandidaten mit Setups:' in line:
                    data['candidates'] = line.split(':')[1].strip()
                if 'Stop-Buy' in line and 'Stop-Sell' in line:
                    data['orders_summary'] = line.strip().split(']')[1].strip() if ']' in line else line.strip()

            set_step(agent_key, 'done', f'{agent["name"]} fertig', data)
            add_log(f'{agent["name"]} abgeschlossen. Outputs: {", ".join(outputs_found)}')
            return True
        else:
            set_step(agent_key, 'error', f'Exit Code {result.returncode}')
            add_log(f'FEHLER: {agent["name"]} Exit {result.returncode}')
            return False

    except subprocess.TimeoutExpired:
        set_step(agent_key, 'error', 'Timeout (5 Min)')
        add_log(f'FEHLER: {agent["name"]} Timeout')
        return False
    except Exception as e:
        set_step(agent_key, 'error', str(e))
        add_log(f'FEHLER: {e}')
        return False


def run_step_async(step, extra_args=None):
    """Fuehre einen Schritt im Hintergrund aus."""
    def _run():
        with state_lock:
            pipeline_state['running'] = step
        try:
            if step == 'db':
                run_db_check()
            elif step in AGENTS:
                run_agent(step, extra_args)
            elif step == 'review':
                set_step('review', 'done', 'Dateien bereit zur Pruefung')
                add_log('Review-Schritt: Dateien bereit')
        finally:
            with state_lock:
                pipeline_state['running'] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ==============================================================
# HTML TEMPLATE
# ==============================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Artifakte — Trading Dashboard</title>
<style>
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
  max-width: 960px; margin: 0 auto; padding: 20px;
}
h1 { color: var(--accent); font-size: 22px; margin-bottom: 4px; }
.subtitle { color: var(--dim); font-size: 11px; margin-bottom: 24px; }

/* Pipeline Steps */
.pipeline { display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }
.step {
  background: var(--surface); border: 1px solid #2d3436;
  border-radius: 8px; padding: 16px 20px;
  display: flex; align-items: center; gap: 16px;
  transition: all 0.3s;
}
.step.active { border-color: var(--accent); box-shadow: 0 0 12px rgba(233,69,96,0.15); }
.step.done { border-color: var(--green); }
.step.error { border-color: var(--red); }
.step.warning { border-color: var(--orange); }
.step.running { border-color: var(--blue); animation: pulse 1.5s infinite; }
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(116,185,255,0.3); }
  50% { box-shadow: 0 0 16px 4px rgba(116,185,255,0.15); }
}

.step-num {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: bold; font-size: 14px; flex-shrink: 0;
  background: var(--surface2); color: var(--dim);
}
.step.done .step-num { background: var(--green); color: #000; }
.step.running .step-num { background: var(--blue); color: #000; }
.step.error .step-num { background: var(--red); color: #fff; }
.step.warning .step-num { background: var(--orange); color: #000; }

.step-content { flex: 1; }
.step-title { font-size: 14px; font-weight: bold; color: var(--text); }
.step-msg { font-size: 11px; color: var(--dim); margin-top: 2px; }
.step-data { font-size: 10px; color: var(--green2); margin-top: 4px; }

.step-actions { display: flex; gap: 8px; flex-shrink: 0; }

button {
  font-family: inherit; font-size: 11px; font-weight: bold;
  padding: 6px 14px; border-radius: 5px; border: none;
  cursor: pointer; transition: all 0.2s;
}
button:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-run { background: var(--accent); color: #fff; }
.btn-run:hover:not(:disabled) { background: #ff4757; transform: translateY(-1px); }
.btn-open { background: var(--surface2); color: var(--blue); border: 1px solid var(--blue); }
.btn-open:hover { background: var(--blue); color: #000; }
.btn-live { background: var(--green); color: #000; }
.btn-live:hover:not(:disabled) { background: #55efc4; }

/* Quick Actions */
.quick-bar {
  display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap;
}
.quick-bar button { font-size: 12px; padding: 8px 16px; }

/* Log */
.log-section { margin-top: 20px; }
.log-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.log-title { color: var(--dim); font-size: 12px; font-weight: bold; }
.log-box {
  background: #0a0a14; border: 1px solid #1a1a2e;
  border-radius: 6px; padding: 12px; max-height: 250px;
  overflow-y: auto; font-size: 10px; line-height: 1.6;
  color: var(--dim);
}
.log-box .log-info { color: var(--text); }
.log-box .log-ok { color: var(--green); }
.log-box .log-err { color: var(--red); }
.log-box .log-warn { color: var(--orange); }

/* Output Links */
.outputs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.output-link {
  display: inline-block; font-size: 10px; padding: 2px 8px;
  background: var(--surface2); color: var(--blue); text-decoration: none;
  border-radius: 3px; border: 1px solid #333;
}
.output-link:hover { background: var(--blue); color: #000; }

/* Footer */
.footer { margin-top: 30px; text-align: center; color: var(--dim); font-size: 10px; }
</style>
</head>
<body>

<h1>AI Artifakte — Trading Dashboard</h1>
<div class="subtitle">
  Naechster Handelstag: <strong id="nextDay">—</strong> |
  Pipeline-Status: <strong id="pipelineStatus">Bereit</strong> |
  <span id="clock"></span>
</div>

<div class="quick-bar">
  <button class="btn-run" onclick="runAll()">Komplette Pipeline starten</button>
  <button class="btn-open" onclick="resetAll()">Reset</button>
</div>

<div class="pipeline" id="pipeline">

  <div class="step" id="step-db">
    <div class="step-num">1</div>
    <div class="step-content">
      <div class="step-title">DB-Status</div>
      <div class="step-msg" id="msg-db">Datenbank pruefen</div>
      <div class="step-data" id="data-db"></div>
    </div>
    <div class="step-actions">
      <button class="btn-run" onclick="runStep('db')">Pruefen</button>
    </div>
  </div>

  <div class="step" id="step-b1">
    <div class="step-num">2</div>
    <div class="step-content">
      <div class="step-title">Persistenzmatrix (B1)</div>
      <div class="step-msg" id="msg-b1">Score-Persistenz ueber 20 Boersentage</div>
      <div class="step-data" id="data-b1"></div>
      <div class="outputs" id="out-b1"></div>
    </div>
    <div class="step-actions">
      <button class="btn-run" onclick="runStep('b1')">Generieren</button>
    </div>
  </div>

  <div class="step" id="step-b2">
    <div class="step-num">3</div>
    <div class="step-content">
      <div class="step-title">Pre-Market Scan (B2)</div>
      <div class="step-msg" id="msg-b2">Setups nach Ollis Methodik erkennen</div>
      <div class="step-data" id="data-b2"></div>
      <div class="outputs" id="out-b2"></div>
    </div>
    <div class="step-actions">
      <button class="btn-run" onclick="runStep('b2')">Scannen</button>
    </div>
  </div>

  <div class="step" id="step-b3">
    <div class="step-num">4</div>
    <div class="step-content">
      <div class="step-title">TWS-Excel Bridge (B3)</div>
      <div class="step-msg" id="msg-b3">Stop-Buy/Sell Orders fuer Excel generieren</div>
      <div class="step-data" id="data-b3"></div>
      <div class="outputs" id="out-b3"></div>
    </div>
    <div class="step-actions">
      <button class="btn-run" onclick="runStep('b3')" title="Dry-Run (DB-Daten)">Dry-Run</button>
      <button class="btn-live" onclick="runStep('b3_live')" title="Live TWS-Verbindung">TWS Live</button>
    </div>
  </div>

  <div class="step" id="step-review">
    <div class="step-num">5</div>
    <div class="step-content">
      <div class="step-title">Pruefung & Freigabe</div>
      <div class="step-msg" id="msg-review">Excel pruefen, Orders freigeben</div>
      <div class="step-data" id="data-review"></div>
    </div>
    <div class="step-actions">
      <button class="btn-open" onclick="runStep('review')">Abschliessen</button>
    </div>
  </div>

</div>

<div class="log-section">
  <div class="log-header">
    <span class="log-title">Log</span>
    <button class="btn-open" onclick="clearLog()" style="font-size:10px;padding:2px 8px;">Leeren</button>
  </div>
  <div class="log-box" id="logBox"></div>
</div>

<div class="footer">AI Artifakte — Agent Dashboard v1.0 | Lokal auf Port {{ port }}</div>

<script>
const STEPS = ['db', 'b1', 'b2', 'b3', 'review'];
let autoRunQueue = [];

function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('de-DE');
}
setInterval(updateClock, 1000);
updateClock();

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const state = await r.json();
    renderState(state);
  } catch(e) {}
}

function renderState(state) {
  document.getElementById('nextDay').textContent = state.next_trading_day || '—';

  let running = state.running;
  document.getElementById('pipelineStatus').textContent = running ? 'Laeuft...' : 'Bereit';

  for (const key of STEPS) {
    const s = state.steps[key];
    const el = document.getElementById('step-' + key);
    el.className = 'step ' + (s.status === 'done' ? 'done' :
                               s.status === 'running' ? 'running' :
                               s.status === 'error' ? 'error' :
                               s.status === 'warning' ? 'warning' : '');

    document.getElementById('msg-' + key).textContent = s.message || el.querySelector('.step-msg').textContent;

    // Data
    const dataEl = document.getElementById('data-' + key);
    if (key === 'db' && s.data) {
      const d = s.data;
      dataEl.innerHTML = d.num_tickers ?
        `${d.num_tickers} Ticker | ${d.num_fundamentals} Fundamentals | ${d.num_days} Tage | ${d.db_size_mb} MB` : '';
    } else if (s.data) {
      let parts = [];
      if (s.data.live_ready) parts.push('Live-Ready: ' + s.data.live_ready);
      if (s.data.candidates) parts.push('Kandidaten: ' + s.data.candidates);
      if (s.data.orders_summary) parts.push(s.data.orders_summary);
      dataEl.textContent = parts.join(' | ');
    }

    // Outputs
    const outEl = document.getElementById('out-' + key);
    if (outEl && s.data && s.data.outputs) {
      outEl.innerHTML = s.data.outputs.map(f =>
        `<a class="output-link" href="/file/${f}" target="_blank">${f}</a>`
      ).join('');
    }

    // Buttons deaktivieren wenn Agent laeuft
    el.querySelectorAll('button').forEach(btn => {
      btn.disabled = !!running;
    });
  }

  // Log
  const logBox = document.getElementById('logBox');
  logBox.innerHTML = state.log.map(line => {
    let cls = 'log-info';
    if (line.includes('FEHLER') || line.includes('ERROR')) cls = 'log-err';
    else if (line.includes('WARN')) cls = 'log-warn';
    else if (line.includes('fertig') || line.includes(' OK')) cls = 'log-ok';
    return `<div class="${cls}">${line}</div>`;
  }).join('');
  logBox.scrollTop = logBox.scrollHeight;

  // Auto-Run naechster Schritt
  if (!running && autoRunQueue.length > 0) {
    const next = autoRunQueue.shift();
    setTimeout(() => runStep(next), 500);
  }
}

async function runStep(step) {
  let actualStep = step;
  let extra = {};
  if (step === 'b3_live') {
    actualStep = 'b3';
    extra = {mode: 'live'};
  }
  await fetch('/api/run/' + actualStep, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(extra)});
  fetchState();
}

function runAll() {
  autoRunQueue = ['b1', 'b2', 'b3', 'review'];
  runStep('db');
}

async function resetAll() {
  await fetch('/api/reset', {method: 'POST'});
  fetchState();
}

async function clearLog() {
  await fetch('/api/clear-log', {method: 'POST'});
  fetchState();
}

// Auto-Refresh
setInterval(fetchState, 1500);
fetchState();
</script>
</body>
</html>"""


# ==============================================================
# FLASK ROUTES
# ==============================================================
@app.route('/')
def index():
    port = request.host.split(':')[1] if ':' in request.host else '5050'
    return render_template_string(HTML_TEMPLATE, port=port)


@app.route('/api/state')
def api_state():
    ntd = next_trading_day()
    with state_lock:
        return jsonify({
            'steps': pipeline_state['steps'],
            'log': pipeline_state['log'][-80:],
            'running': pipeline_state['running'],
            'next_trading_day': next_trading_day_str(),
        })


@app.route('/api/run/<step>', methods=['POST'])
def api_run(step):
    with state_lock:
        if pipeline_state['running']:
            return jsonify({'error': 'Agent laeuft bereits'}), 409

    extra_args = None
    if step == 'b3':
        body = request.get_json(silent=True) or {}
        if body.get('mode') == 'live':
            extra_args = ['--live']
            # Entferne --dry-run
            AGENTS['b3']['args'] = ['--live']
        else:
            AGENTS['b3']['args'] = ['--dry-run']

    run_step_async(step, extra_args)
    return jsonify({'ok': True})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    with state_lock:
        for k in pipeline_state['steps']:
            pipeline_state['steps'][k] = {'status': 'pending', 'message': '', 'data': {}}
        pipeline_state['running'] = None
    add_log('Pipeline zurueckgesetzt')
    save_pipeline_status('reset', 'pending', 'Pipeline zurueckgesetzt')
    return jsonify({'ok': True})


@app.route('/api/clear-log', methods=['POST'])
def api_clear_log():
    with state_lock:
        pipeline_state['log'] = []
    return jsonify({'ok': True})


@app.route('/file/<path:filename>')
def serve_file(filename):
    fp = SCRIPT_DIR / filename
    if fp.exists():
        from flask import send_file
        return send_file(str(fp))
    return 'Datei nicht gefunden', 404


# ==============================================================
# HAUPTPROGRAMM
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='AI Artifakte — Agent Dashboard')
    parser.add_argument('--port', type=int, default=5050)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    print(f"""
  ╔══════════════════════════════════════════════════╗
  ║  AI Artifakte — Trading Dashboard               ║
  ║  http://localhost:{args.port}                        ║
  ║  Ctrl+C zum Beenden                             ║
  ╚══════════════════════════════════════════════════╝
    """)

    app.run(host='127.0.0.1', port=args.port, debug=args.debug, threaded=True)


if __name__ == '__main__':
    main()
