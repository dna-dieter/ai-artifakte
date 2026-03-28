# AI Artifakte – Projekt Börsenhandel – Masterplan

**Unternehmen:** AI Artifakte
**Projektstart:** 26.03.2026
**Status:** Phase 1 ✅ abgeschlossen (29.03.2026) — Phase 2 teilweise umgesetzt
**Repository:** [github.com/dna-dieter/ai-artifakte](https://github.com/dna-dieter/ai-artifakte)
**Lernquellen:** Feiertag Trading Academy (+ weitere geplant)

---

## Gesamtübersicht: Die Trading-Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  PHASE 1    │    │  PHASE 2    │    │  PHASE 3    │    │  PHASE 4    │    │  PHASE 5    │
│  Daten      │───▶│  Screening  │───▶│  Persistenz │───▶│  Trading    │───▶│  Journal &  │
│  beschaffen │    │  & Regeln   │    │  & Selektion│    │  Execution  │    │  Optimierung│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
     SEC API            Feiertag           Heatmap            TWS/IB           Tagebuch
     Kursdaten          Academy            Top 100-400        Pattern          P&L Tracking
     täglich            Regelwerk          Wochen-Stärke      Entries          Verbesserung
```

---

## Phase 1: Datenbeschaffung (Foundation)

**Ziel:** Zuverlässige, tägliche Versorgung mit Fundamental- und Kursdaten.

### 1.1 SEC-Finanzdaten (Fundamentals)

**Was:** Quartals- und Jahresdaten aller börsennotierten US-Unternehmen.
**Quelle:** SEC EDGAR (XBRL/JSON API) – kostenlos, offiziell, zuverlässig.
**Daten:** Revenue, Earnings, EPS, Market Cap, Dividende, Schuldenquote, Cashflow.

**Arbeitsschritte:**
- SEC EDGAR API-Zugang einrichten (User-Agent Header mit E-Mail)
- Python-Skript: Company Facts API → JSON → lokale Datenbank
- Mapping: CIK → Ticker-Symbol (SEC company_tickers.json)
- Täglicher Cron-Job für neue Filings
- Datenvalidierung: Fehlende Felder, Ausreißer erkennen
- Historische Daten laden (mindestens 3 Jahre für Backtesting)

**✅ Erledigt:** SEC-Pipeline läuft vollautomatisch. 10-Q + 10-K Loader, c-sec Berechnung, FYE-Erkennung, Shares Outstanding — alles via launchd täglich.

### 1.2 Tagesaktuelle Kursdaten (Price Data)

**Was:** OHLCV (Open, High, Low, Close, Volume) für alle relevanten Aktien.
**Quellen (Optionen):**
- Yahoo Finance (yfinance) – kostenlos, unzuverlässig bei hoher Last
- Alpha Vantage – kostenlos (500 Calls/Tag), zuverlässig
- Polygon.io – günstig, professionell, Echtzeit möglich
- Interactive Brokers API – bereits vorhanden durch TWS

**Arbeitsschritte:**
- Primäre Datenquelle wählen und API-Key beschaffen
- Python-Skript: Täglicher Download aller relevanten Ticker (S&P 500 + Extended)
- Datenspeicherung: SQLite oder PostgreSQL mit täglichen OHLCV-Einträgen
- Fallback-Quelle einrichten (wenn primäre Quelle ausfällt)
- Datenqualität: Splits, Dividenden-Adjustierung, fehlende Tage erkennen
- Historische Daten laden (mindestens 1 Jahr)

### 1.3 Datenspeicherung & Infrastruktur

**Was:** Zentrale Datenbank für alle Projekt-Daten.

**Arbeitsschritte:**
- Datenbankschema entwerfen (Entities, Preise, Screening-Ergebnisse, Trades)
- SQLite für den Anfang (lokal, einfach, kein Server nötig)
- Migration auf PostgreSQL wenn nötig (Multi-User, Performance)
- Backup-Strategie: Tägliches Backup der DB
- Daten-Pipeline: Scheduler für tägliche Imports (cron oder Python schedule)

**✅ Erledigt:** `feiertag_trading.db` (SQLite, WAL-Modus) mit 6.715 Stammdaten, 114K Finanzsätzen, Daily Screen, Earnings-Terminen. Zusätzlich `sec_data.db` (2.1 GB, ~8M Facts).

---

## Phase 2: Screening & Regelwerk

**Ziel:** Automatisierter Scanner, der täglich die "besten" Aktien nach Feiertag-Academy-Regeln filtert.

### 2.1 Handelsstrategie formalisieren

**Was:** Die Feiertag Trading Academy Regeln in maschinenlesbare Kriterien übersetzen.

**Arbeitsschritte:**
- Alle Screening-Kriterien dokumentieren (was genau macht eine Aktie "gut"?)
- Kriterien in Kategorien aufteilen: Fundamental, Technisch, Liquidität
- Gewichtung festlegen: Welche Kriterien wiegen schwerer?
- Score-Modell definieren (z.B. 0-11 Punkte wie in der Heatmap)
- Schwellenwerte bestimmen (ab wann ist ein Score "gut genug"?)
- Edge Cases definieren: Was passiert bei fehlenden Daten?

**Lücke erkannt:** Das Regelwerk muss eindeutig dokumentiert sein, bevor es automatisiert werden kann. → Regelwerk-Dokument erstellen.

### 2.2 Scanner-Engine bauen

**Was:** Python-Programm, das täglich alle Aktien gegen das Regelwerk prüft.

**Arbeitsschritte:**
- Scanner-Klasse in Python: nimmt Aktie + Daten → gibt Score zurück
- Fundamental-Filter: Revenue-Wachstum, Earnings-Trend, Dividende
- Technische Filter: Preis über/unter MAs, RSI, Volumen-Trend
- Liquiditäts-Filter: Mindest-Volumen, Mindest-Market-Cap
- Ergebnis: Tägliche Liste mit Ticker + Score + Detail-Breakdown
- Ergebnisse in Datenbank speichern (Datum, Ticker, Score, Einzelwerte)
- Dashboard-Integration: Screening-Ergebnisse als HTML-Seite

### 2.3 Screening-Konfiguration

**Was:** Flexibel anpassbare Parameter ohne Code-Änderung.

**Arbeitsschritte:**
- Config-Datei (YAML/JSON) für alle Schwellenwerte und Gewichtungen
- Möglichkeit, verschiedene Strategien als Profile zu speichern
- Logging: Welche Aktien warum rausgefiltert wurden

---

## Phase 3: Persistenz & Selektion

**Ziel:** Aus täglichen Screening-Ergebnissen die langfristig stärksten Aktien identifizieren.

### 3.1 Persistenzmatrix automatisieren

**Was:** Die bestehende Heatmap (heatmap.html) dynamisch aus der Datenbank generieren.

**Arbeitsschritte:**
- Tägliche Screening-Ergebnisse über Zeitfenster aggregieren (z.B. 20 Handelstage)
- Persistenz-Score berechnen: Wie oft war eine Aktie in den Top-Ergebnissen?
- Trend erkennen: Steigend, stabil, fallend
- Heatmap automatisch aus DB generieren (statt manuell gepflegtes HTML)
- Filteroptionen: Zeitraum, Mindest-Persistenz, Sektor

**Besteht bereits teilweise:** heatmap.html mit 153 Aktien und normalisierten Scores.
**Lücke:** Aktuell statisch – muss dynamisch aus DB generiert werden.

### 3.2 Watchlist-Management

**Was:** Die Top 100-400 Aktien als handelbare Watchlist pflegen.

**Arbeitsschritte:**
- Automatische Watchlist-Generierung aus Persistenzmatrix
- Kategorisierung: "Neu auf Liste", "Seit X Tagen", "Absteigend"
- Export-Format für TWS/IB (CSV oder API-Push)
- Alerts: Neue Aktien auf Watchlist, Aktien die rausfallen
- watchlist.html dynamisch generieren

### 3.3 Marktüberblick

**Was:** Tägliche Markt-Kontextinformationen für Trading-Entscheidungen.

**Arbeitsschritte:**
- Marktbreite-Indikatoren (Advance/Decline, New Highs/Lows)
- Sektor-Rotation erkennen
- VIX / Volatilitäts-Level
- Earnings-Saison-Kalender (besteht: earnings.html)
- markt.html dynamisch generieren

---

## Phase 4: Live Trading

**Ziel:** Effizientes Handeln der Watchlist-Aktien über TWS/Interactive Brokers.

### 4.1 TWS/IB-Anbindung

**Was:** Verbindung zwischen dem Projekt und der Interactive Brokers Trader Workstation.

**Arbeitsschritte:**
- IB API (ib_insync Python-Library) einrichten
- Verbindung zu TWS Paper Trading Account testen
- Watchlist automatisch in TWS importieren
- Echtzeit-Kurse für Watchlist-Aktien abfragen
- Kontoinformationen abrufen (Kapital, Margin, offene Positionen)

### 4.2 Pattern-Erkennung (Trading Signals)

**Was:** Einstiegssignale für die Watchlist-Aktien identifizieren.

**Arbeitsschritte:**
- Trading-Patterns aus Feiertag Academy definieren (z.B. Breakouts, Pullbacks)
- Technische Indikatoren berechnen (MA-Crosses, Volume Spikes, Candlestick Patterns)
- Alert-System: "AAPL zeigt Breakout-Pattern" per Notification
- Visuell: Chart mit markierten Signalen im Dashboard
- Unterscheidung: automatische Alerts vs. manuelle Chart-Analyse

**Lücke erkannt:** Welche konkreten Patterns sollen erkannt werden? → Muss aus Feiertag Academy abgeleitet werden.

### 4.3 Order-Management

**Was:** Trades über die IB API platzieren und verwalten.

**Arbeitsschritte:**
- Order-Typen implementieren: Market, Limit, Stop, Stop-Limit
- Position Sizing: Wie viel Kapital pro Trade? (Risikomanagement)
- Stop-Loss automatisch setzen
- Take-Profit Level definieren
- Order-Status tracking
- WICHTIG: Erst Paper Trading, dann Live mit kleinen Positionen

### 4.4 Risikomanagement

**Was:** Regeln zum Schutz des Kapitals.

**Arbeitsschritte:**
- Maximales Risiko pro Trade definieren (z.B. 1-2% des Portfolios)
- Maximale Anzahl gleichzeitiger Positionen
- Täglicher/wöchentlicher Max-Verlust (Circuit Breaker)
- Korrelations-Check: Nicht zu viele Aktien im gleichen Sektor
- Margin-Überwachung

**Lücke erkannt:** Risikomanagement ist nicht im beschriebenen Workflow enthalten – ist aber essentiell für nachhaltigen Erfolg.

---

## Phase 5: Börsentagebuch & Optimierung

**Ziel:** Jeden Trade dokumentieren und systematisch aus Erfahrungen lernen.

### 5.1 Trading Journal (Börsentagebuch)

**Was:** Vollständige Dokumentation jedes Trades.

**Pro Trade erfassen:**
- Datum/Uhrzeit Entry + Exit
- Ticker, Richtung (Long/Short), Positionsgröße
- Entry-Preis, Stop-Loss, Take-Profit, Exit-Preis
- P&L (absolut und prozentual)
- Strategie / Pattern das zum Einstieg führte
- Screenshot des Charts bei Entry
- Emotionen / Psychologischer Zustand
- Bewertung: Wurde die Strategie eingehalten? (Ja/Nein)
- Lessons Learned

**Arbeitsschritte:**
- journal.html als Eingabe-Interface bauen
- Trade-Daten in Datenbank speichern
- Automatischer Import von Trade-Daten aus IB (was möglich ist)
- Manuelle Ergänzung (Emotionen, Notizen, Screenshots)
- Tages-/Wochen-/Monatsansicht

### 5.2 Performance Analytics

**Was:** Statistische Auswertung der Trading-Ergebnisse.

**Kennzahlen:**
- Gesamte P&L, Win-Rate, Average Win vs. Average Loss
- Profit Factor, Sharpe Ratio, Max Drawdown
- Beste/schlechteste Trades
- Performance nach: Wochentag, Tageszeit, Sektor, Pattern-Typ
- Equity Curve (Kapitalverlauf über Zeit)

**Arbeitsschritte:**
- Analytics-Dashboard (analytics.html)
- Charts: Equity Curve, P&L-Verteilung, Win-Rate über Zeit
- Vergleich: Eigene Performance vs. Benchmark (S&P 500)
- Monatliche Performance-Reports

### 5.3 Feedback-Loop (Kontinuierliche Verbesserung)

**Was:** Erkenntnisse aus dem Journal zurück in die Strategie fließen lassen.

**Arbeitsschritte:**
- Monatliches Review: Was funktioniert, was nicht?
- Screening-Regeln anpassen basierend auf Trade-Ergebnissen
- Pattern-Erkennung verfeinern
- Risikomanagement-Parameter optimieren
- A/B-Testing: Verschiedene Strategie-Varianten vergleichen
- Backtesting neuer Regeln gegen historische Daten

---

## Phase 6: Automatisierung & Skalierung (Zukunft)

### 6.1 Vollautomatische Pipeline

- Cron/Scheduler: Täglich um 06:00 MEZ alle Daten aktualisieren
- Screening automatisch laufen lassen
- Persistenzmatrix + Watchlist automatisch aktualisieren
- Dashboard automatisch neu generieren
- GitHub Pages automatisch deployen

### 6.2 Alerting & Notifications

- E-Mail/Telegram-Alerts bei: neuen Screening-Hits, Pattern-Signalen, Risiko-Warnungen
- Morning Briefing: Tägliche Zusammenfassung per E-Mail

### 6.3 Backtesting Engine

- Historische Simulation der Strategie
- Walk-Forward-Analyse
- Parameter-Optimierung
- Out-of-Sample-Testing

---

## Technologie-Stack (Empfehlung)

| Komponente | Technologie | Begründung |
|---|---|---|
| Sprache | Python 3.11+ | Trading-Ökosystem, Datenanalyse, IB API |
| Datenbank | SQLite → PostgreSQL | Einfacher Start, spätere Skalierung |
| Kursdaten | yfinance + IB API | Kostenlos + professionell |
| Fundamentals | SEC EDGAR API | Offizielle, kostenlose Quelle |
| Broker | Interactive Brokers (ib_insync) | Bereits vorhanden (TWS) |
| Frontend | HTML/JS (bestehend) | Funktioniert, GitHub Pages kompatibel |
| Scheduling | cron + Python schedule | Einfach, zuverlässig |
| Versionierung | GitHub | Bereits eingerichtet |

---

## Priorisierte Reihenfolge der Umsetzung

### Sofort (Woche 1-2) — ✅ ERLEDIGT (26.-29.03.2026)
1. ✅ Datenbank-Schema entwerfen und SQLite aufsetzen — `feiertag_trading.db` (6.715 Stammdaten, 114K Finanzsätze)
2. ✅ SEC-Daten-Pipeline automatisieren — `load_sec_10q.py`, `load_sec_10k.py`, `calc_q4_c_sec.py`, `run_fin_load.py` (8.083 Firmen, 5.732 mit Facts, ~8M Facts, tagesaktuell via launchd)
3. ✅ Kursdaten-Pipeline automatisieren — `feiertag_daily_screener.py` via yfinance (launchd Di-Sa 02:30), Daily Screen 2.086 Ticker
4. ✅ Regelwerk der Feiertag Academy schriftlich dokumentiert — `methodik_analyse.md` (1.640 Zeilen), `feiertag_config.py` (11 Kriterien, alle Schwellenwerte)

**Zusätzlich umgesetzt in Phase 1:**
- ✅ SEC EDGAR XBRL Pipeline: 10.447 → 8.083 → 5.732 → 5.685 (NQ+NYSE)
- ✅ Market Cap Berechnung: Shares Outstanding SEC × Kurs, Public Float Fallback
- ✅ Gewichtetes YoY-Wachstum: `calc_weighted_growth.py` (W1=0.67, W2=0.33, Turnaround=+999%)
- ✅ SIC → Sektor-Mapping: 392 SIC-Beschreibungen → 16 Sektoren
- ✅ Earnings-Termine: `t_sym_edt_earningsdate` (26.537 Termine)
- ✅ FYE-Erkennung: Non-Dez Fiskaljahre (AAPL=Sep, DELL=Feb etc.) mit ±1 Monat Toleranz
- ✅ c-sec Berechnung: Q4 = 10K_annual - (Q1+Q2+Q3) für fehlende 10-Q

**SEC Filing Cabinet (Dashboard) — ✅ Live auf GitHub Pages:**
- ✅ Vollständiger Datentrichter: 10.447 SEC → 242 Kandidaten (transparent)
- ✅ Dynamische Slider: MktCap ($500M-$1.2B), Rev% (10-100%), Net% (10-100%)
- ✅ 16 Sektor-Filter mit Live-Counts
- ✅ 5 technische Filter-Pills: SMA50, SMA200, Golden Cross, 52W-Hoch, 3M-Performance
- ✅ 542 Factsheets (Klick auf Ticker → Modal mit Quartalszahlen, Growth, Earnings)
- ✅ FAATMAN+NVDA Mega-Cap Auswahl
- ✅ Live Trading Export (.txt Watchlist) + CSV Download
- ✅ ← Back-Button zum Dashboard

### Kurzfristig (Woche 3-4)
5. ✅ Scanner-Engine in Python bauen — `feiertag_daily_screener.py` + `feiertag_live_scanner.py` (11-Kriterien-Score, IB Streaming)
6. ✅ Persistenzmatrix dynamisch aus DB generieren — `generate_heatmap.py` → `heatmap.html` (20-Tage Score-Persistenz)
7. ✅ Watchlist automatisch erstellen und exportieren — `generate_watchlist.py` → `watchlist.html` + `live_watchlist_70.txt`
8. ☐ Börsentagebuch (journal.html) – Eingabe-Interface

### Mittelfristig (Woche 5-8)
9. ☐ TWS/IB-Anbindung (Paper Trading)
10. ☐ Pattern-Alerts implementieren
11. ☐ Performance Analytics Dashboard
12. ☐ Risikomanagement-Regeln implementieren

### Langfristig (Monat 3+)
13. ☐ Vollautomatische tägliche Pipeline
14. ☐ Alerting (E-Mail/Telegram)
15. ☐ Backtesting Engine
16. ☐ Feedback-Loop systematisieren

---

## Offene Fragen

1. ~~**Datenquelle Kurse:**~~ ✅ yfinance (Daily Screener) + IB API (Live Scanner)
2. ~~**SEC-Automatisierung:**~~ ✅ Vollautomatisch via launchd (Di-Sa 02:30)
3. ~~**Feiertag Academy Regeln:**~~ ✅ `methodik_analyse.md` + `feiertag_config.py`
4. **IB-Account:** Paper Trading Account bereits eingerichtet? → Live-Account U7793506 aktiv
5. **Hosting:** Soll das Dashboard langfristig auf GitHub Pages bleiben oder auf einen eigenen Server?
6. **Kapital & Risiko:** Wie groß ist das Trading-Konto? (bestimmt Position Sizing)
7. **Daily Ticker:** Tägliche Aktualisierung des Filing Cabinets noch nicht automatisiert — nächster Schritt

---

*Dieses Dokument ist ein lebendes Dokument. Es wird mit jedem Fortschritt aktualisiert und detaillierter.*

*Erstellt: 28.03.2026*
*Letzte Aktualisierung: 29.03.2026 — Phase 1 abgeschlossen*
