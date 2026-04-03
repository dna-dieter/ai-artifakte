# AI Artifakte – Projekt Börsenhandel – Claude Steuerungsdatei

## Projektkontext

**Unternehmen:** AI Artifakte (Dieters eigenes Unternehmen)

Wir entwickeln ein Handelssystem für Aktienhandel. Das System umfasst eine vollständige Trading-Pipeline von der Datenbeschaffung bis zur Performance-Analyse. Die Handelsstrategien basieren auf verschiedenen Lernquellen — aktuell u.a. der Feiertag Trading Academy Methodik, weitere Quellen werden hinzugefügt.

## Nutzer-Profil

- **Name:** Dieter
- **E-Mail:** dieter.nadolski@gmail.com
- **GitHub-ID:** dna-dieter
- **Erfahrung:** Lernt CoWork systematisch am Beispiel dieses Projekts. Bevorzugt praktische, schrittweise Herangehensweise.
- **Lernstil:** Praktisch, Schritt für Schritt, mit Feedback-Schleife. Lernt am besten an konkreten Beispielen.
- **Sprache:** Deutsch (Kommunikation), Englisch (Code & Variablen)

## Arbeitsumgebung

- **2-Rechner-Setup:** Alle Projektdateien liegen zentral im iCloud-Ordner "Boersenhandel", damit beide Rechner synchron bleiben.
- **Konsistenz-Prinzip:** Da das Auto-Memory von Claude rechner-spezifisch sein kann, ist diese CLAUDE.md die zentrale Wahrheitsquelle. Alles Wichtige hier festhalten — nicht nur im Auto-Memory.
- **Zweiter Ordner:** "CoWork richtig benutzen" für allgemeine CoWork-Learnings (projektübergreifend).
- **Domain:** ai-artifakte.com (gesichert, Platzhalter aktiv, SSL noch offen)
- **Repository:** [github.com/dna-dieter/ai-artifakte](https://github.com/dna-dieter/ai-artifakte) *(Umbenennung von exchange-dashboard geplant)*
- **Projektstart:** 26.03.2026

## Projektstruktur

```
AI-Artifakte/                           ← iCloud-Ordner (Umbenennung von "Boersenhandel" geplant)
├── CLAUDE.md                        ← Diese Steuerungsdatei (immer im Hauptverzeichnis!)
├── PROJEKTPLAN.md                   ← Masterplan mit allen Phasen
├── KONZEPT-UEBERSICHT.html         ← Visuelle Konzeptübersicht
└── (weitere Dateien folgen)
```

## Datenbanken

| Datenbank | Ordner | Inhalt |
|---|---|---|
| **stock_prices.db** | `SEC Aktien/` | Aktienkurse (daily prices), relative Stärke, Validierungen. Quelle: yfinance + IB API. |
| **sec_data.db** | `SEC filing/` | SEC-Fundamentaldaten (Companyfacts, Filings, XBRL). Quelle: SEC EDGAR API. |

**`SEC Aktien/`** ist der zentrale Ordner für alles rund um Kursdaten, Screening und Chartanalyse. Hier liegen auch alle Python-Skripte für Preisloading, VCP-Screening, Relative Stärke, Marktanalyse und Live-Trading.

## Earnings-Bewertung (10-K / 10-Q Regel)

### Aktualitäts-Gewichtung

Nicht alle Filings sind gleich aktuell. Die Gewichtung spiegelt wider, wie zeitnah die Daten zum betroffenen Quartal sind:

| Filing-Typ | Veröffentlichungszeitpunkt | Gewichtung |
|---|---|---|
| **10-Q** (Quartalsbericht) | — | **1.0** (immer aktuell) |
| **10-K** (Jahresbericht) | Ende 1. Monat eines Quartals | **0.3** |
| **10-K** (Jahresbericht) | Ende 2. Monat eines Quartals | **0.65** |
| **10-K** (Jahresbericht) | Ende 3. Monat eines Quartals | **0.9** |

Entscheidend für die Gewichtung ist der **Stichtag des Fiskaljahresendes (FYE)** — also in welchem Monat des Kalenderquartals das Geschäftsjahr endet:

| FYE-Stichtag im Kalenderquartal | Gewichtung | Beispiele |
|---|---|---|
| **Monat 1** (Jan, Apr, Jul, Okt) | **0.3** | DELL (Jan 29), CIEN (Okt 31), WDC (Jul 3), CASY (Apr 30) |
| **Monat 2** (Feb, Mai, Aug, Nov) | **0.65** | ROST (Feb 1), APLD (Mai 31), JBL (Aug 31), ADI (Nov 1) |
| **Monat 3** (Mär, Jun, Sep, Dez) | **0.9** | SNDK (Jun 28), MU (Sep 3), AMD (Dez 26), FLEX (Mär 31) |

### Q4-Berechnung aus 10-K

Da Q4 nicht als eigenständiger 10-Q-Bericht eingereicht wird, muss Q4 aus dem 10-K abgeleitet werden:

**Q4 Earnings = 10-K (Gesamtjahr FY) − Q1 (10-Q) − Q2 (10-Q) − Q3 (10-Q)**

Diese Regel gilt generell für **jedes Quartal, in dem ein 10-K statt eines 10-Q abgegeben wird**. Nicht alle Firmen haben Kalenderjahr als Geschäftsjahr — das betroffene Quartal kann also Q1, Q2, Q3 oder Q4 sein. In jedem Fall: Das Quartal, in dem der 10-K publiziert wird, erhält die Aktualitäts-Gewichtung gemäß obiger Tabelle (0.3 / 0.65 / 0.9 je nach Monat).

### Screening-Regel für Earnings

Für die Earnings-Berechnung im Screening werden immer die **letzten 2 Quartale mit einer Gewichtung > 0.8** herangezogen. Das bedeutet:

- 10-Q-Daten (Gewichtung 1.0) qualifizieren sich **immer**
- 10-K-abgeleitete Quartalsdaten qualifizieren sich **nur**, wenn der 10-K spät im Quartal publiziert wurde (Gewichtung 0.9)
- 10-K-Daten mit Gewichtung 0.3 oder 0.65 werden für das Screening **nicht** verwendet (zu veraltet)

### Earnings-Berechnung (gewichteter Durchschnitt)

Die beiden qualifizierten Quartale gehen mit unterschiedlicher Gewichtung in die Earnings-Berechnung ein:

| Quartal | Gewichtung | Begründung |
|---|---|---|
| **Jüngstes** qualifiziertes Quartal | **2/3** | Aktuellste Daten, höchste Relevanz |
| **Zweitjüngstes** qualifiziertes Quartal | **1/3** | Ergänzender Kontext, geringere Relevanz |

**Summe der Gewichte: 1.0** (= ein voller Datenpunkt für die Screening-Entscheidung)

**Formel:** `Earnings Score = (2/3 × EPS jüngstes Quartal) + (1/3 × EPS zweitjüngstes Quartal)`

Analog für Revenue Growth: `Revenue Score = (2/3 × Revenue Growth jüngstes Q) + (1/3 × Revenue Growth zweitjüngstes Q)`

### Beispiel

Firma mit Geschäftsjahr = Kalenderjahr:
- Q1 2026 (10-Q, filed Mai 2026) → Gewichtung 1.0 ✓ → geht mit **2/3** ein
- Q4 2025 (aus 10-K, filed Ende Februar 2026 = 2. Monat von Q1) → Gewichtung 0.65 ✗
- Q3 2025 (10-Q, filed November 2025) → Gewichtung 1.0 ✓ → geht mit **1/3** ein

→ Screening nutzt Q1 2026 (2/3) und Q3 2025 (1/3) als gewichteten Earnings Score.

## Screening-Regeln (Feiertag-Methodik)

Quelle: feiertag-chart-experte Skill, Abschnitte 8 (Screening) und 9 (Fundamentale Vorselektion).

### Priorisierte Vorselektion (Stufe 0 — Mindestanforderungen)

1. Preis >= $5
2. Earnings YoY Performance > 0% (positiv)
3. Revenue YoY Performance > 0% (positiv)
4. Tägliches Handelsvolumen >= 200.000 Shares

### Technisches Screening (Schritt 1)

1. Close > 200-Tage SMA
2. 200-Tage SMA steigend (vs. 5 Tage zuvor)
3. Relative Stärke > 70
4. Kurs innerhalb 10–20% des 52-Wochen-Hochs
5. Tägliches Volumen > 500.000 Shares
6. Aktie in Phase 2 (30w-MA steigend, 200d-MA steigend)
7. Aktie ist Leader (Top RS im Sektor)
8. Nicht extended (Kurs nicht >30% über 200d-MA)
9. Tägliches Dollar-Volumen > $10M
10. Markt nicht in Phase 4 (QQQ/SPY nicht in Phase 4)
11. Neue 52w-Hochs = stärkstes Signal (kein Overhead Supply)
12. Pre-Market Gap-ups >5–10% auf Earnings/News screenen (Bull Snort)
13. VCP bildet sich oft 2–3 Tage vor Earnings — vorher screenen
14. Gap-ups >3–5% in Phase-2-Aktien screenen (Start Rallye)

### Fundamentale Vorselektion (Schritt 2)

15. Revenue Growth: Ziel +10% bis +50% YoY
16. Earnings Growth: Ziel +20% bis +100% YoY
17. Earnings Growth > Revenue Growth = Margenexpansion (bullish)
18. Earnings Acceleration: aktuelles Quartal > vorheriges Quartal
19. Phase-2-Leader haben beschleunigende Earnings
20. KGV 15–25 = günstige Phase-2-Leader, bestes Risiko/Reward
21. KGV 40–80 = bereits erkannt, hohe Erwartungen
22. KGV >100 = spekulativ, höheres Umkehr-Risiko
23. Hohe KGV in Phase 2 nicht ausschließen — Momentum überwindet Bewertung
24. Sicherste Trades: KGV 20–50 mit beschleunigenden Earnings

## Designprinzipien

- **Vollständigkeit & Korrektheit vor Bequemlichkeit:** Wir gehen zur Primärquelle (SEC EDGAR), nicht zu Aggregatoren (Yahoo Finance, Finviz etc.). Standardlösungen liefern oft unvollständige oder fehlerhafte Fundamentaldaten — diese Hindernisse wollen wir vermeiden.
- **SEC-Filings als Fundament:** Alle Fundamentaldaten (Earnings Growth, Sales Growth etc.) kommen direkt aus den offiziellen Filings aller US-börsennotierten Unternehmen bei der SEC.

## Technologie-Stack

- **Sprache:** Python 3.11+
- **Datenbank:** SQLite (Start) → PostgreSQL (Skalierung)
- **Kursdaten:** yfinance + IB API
- **Fundamentaldaten:** SEC EDGAR API
- **Broker:** Interactive Brokers (TWS, ib_insync)
- **Frontend:** HTML/JS, GitHub Pages
- **Versionierung:** GitHub

## Aktuelle Phase

**Phase 1 – Datenbeschaffung:** SEC-Finanzdaten, tagesaktuelle Kursdaten, Datenbankinfrastruktur aufbauen.

## Regeln für Claude

1. **Dateispeicherung:** Alle Dateien im iCloud-Projektordner ablegen, damit beide Rechner synchron bleiben.
2. **Code-Stil:** Python-Code mit aussagekräftigen englischen Variablennamen, deutsche Kommentare wo hilfreich.
3. **Dokumentation:** Fortschritt im PROJEKTPLAN.md aktualisieren.
4. **Git:** Commits auf das Repository dna-dieter/ai-artifakte pushen wenn gewünscht.
5. **Vorsicht bei Trades:** Niemals echte Orders ohne explizite Freigabe – immer zuerst Paper Trading.
6. **Verfügbare Skills nutzen:** Claude-Skills (xlsx, pdf, docx, pptx etc.) aktiv einsetzen wenn passend.
7. **CoWork-Learnings:** Bei neuen Erkenntnissen über die CoWork-Nutzung diese im Ordner "CoWork richtig benutzen/COWORK-LEARNINGS.md" dokumentieren — nicht hier.
8. **Mitlernen:** Claude denkt aktiv mit und schlägt Verbesserungen vor, statt nur Aufträge abzuarbeiten.
9. **Custom Skills aus meinBrain laden:** Siehe Abschnitt "Custom Skill-Registry" unten. Bei Bedarf die SKILL.md über den Filesystem-MCP laden.
10. **Nachfragen statt einfach machen:** Wenn eine Vorgabe von Dieter nicht erfuellbar ist (technische Einschraenkung, fehlender Zugriff, Widerspruch zu anderen Anforderungen), MUSS Claude darauf hinweisen und nachfragen — NIEMALS stillschweigend eine Alternative umsetzen oder die Vorgabe ignorieren. Lieber einmal zu viel fragen als einmal falsch abbiegen.

## Feedback & Präferenzen (was Claude sich merken soll)

- **Konsistenz über 2 Rechner:** Dieter bevorzugt strikte Konsistenz. Alles Projektrelevante in diese CLAUDE.md, nicht nur ins Auto-Memory.
- **Iterativ arbeiten:** Nicht alles auf einmal, sondern Schritt für Schritt. Claude fragt nach, wenn etwas unklar ist.
- **CLAUDE.md ins Hauptverzeichnis:** Keine Unterordner für Steuerungsdateien. CLAUDE.md gehört direkt ins Root des Projektordners.

## Custom Skill-Registry (meinBrain)

CoWork lädt Symlink-Skills aus dem Boersenhandel-Ordner NICHT automatisch, weil die Sandbox die absoluten Mac-Pfade nicht auflösen kann. Die Skills liegen aber vollständig in meinBrain und sind über den **Filesystem-MCP** jederzeit lesbar.

### Lade-Anweisung

Wenn ein Trigger-Keyword aus der Tabelle unten auftaucht, lade den Skill mit:
```
mcp__filesystem__read_file(path="/Users/dieternadolski/Library/Mobile Documents/iCloud~md~obsidian/Documents/meinBrain/.claude/skills/{skill-name}/SKILL.md")
```
Erst lesen, dann die Anweisungen aus der SKILL.md befolgen. Nicht alle Skills auf Vorrat laden — das frisst Context.

### Skill-Verzeichnis

| Skill | Trigger-Keywords | Zweck |
|---|---|---|
| **feiertag-chart-experte** | chart analyse, setup erkennung, einstieg, weinstein, undercut, maur, vcp, keilausbruch, cup and handle, fehldurchbruch, screening, phase 2, relative stärke | Feiertag Academy: 6 Long-Setups, Weinstein-Phasen, Screening, Einstiegs-Optimierung |
| **feiertag-positions-management** | stopp setzung, stop loss, trailing stop, position sizing, risk management, gewinnmitnahme, exit signal, ma verlust, climax top, sell rules | Feiertag Academy: Positionsmanagement, Stopps, Trailing, VIX-Regime |
| **chart-experte** | tradingview, lightweight charts, chart pattern, candlestick, html chart, setup visualization | TradingView Lightweight Charts Implementation, Pattern-Erkennung |
| **sec-expert-advisor** | SEC regulierung, börse erklärt, XBRL, filing typ, formular, IPO prozess, delisting, börseninfrastruktur, DTCC, FINRA | SEC-Regulierungswissen, Börseninfrastruktur, XBRL-Taxonomie |
| **sec-load-expert** | full load, delta update, companyfacts, sec_data.db, db schema, tabelle, index, validierung, SQL query, skript ausführen | Technische SEC-Datenpipeline, DB-Schema, Skripte |
| **ipo-expert** | IPO, börsengang, S-1 filing, IPO pipeline, neue listings, going public, SPAC, direct listing | IPO-Erkennung und Reporting aus sec_data.db |
| **obsidian-gedanken** | sessionstart, vault, gedanke, idee, notiere, merke dir, aufgabe, reflexion, in obsidian, second brain, übergabe | Obsidian-Vault Betriebssystem, Session-Routinen, Querverweise |
| **claude-nutzung-effizient** | ressourcen sparen, token sparen, effizienter, max plan, nacht batch, scheduled task, context budget | Token-Optimierung, Nacht-Batches, Context-Management |
| **mac-mini-remote** | mac mini, server, sec load status, läuft der job, launchd, remote, com.sec.update | Mac Mini Status-Checks, Job-Überwachung, Remote-Befehle |
| **terminal-auslesen** | terminal, log lesen, was sagt das terminal, prozess läuft, ergebnis vom script, logrun | Terminal-Output via logrun auslesen |
| **terminal-watchdog** | watchdog, pending logs, terminal ergebnis, watchdog status | Automatischer Terminal-Log-Watchdog |
| **markt-analyse** | marktanalyse, wie steht der markt, SPY analyse, intraday, opening range, VWAP, marktbreite, breadth, VIX regime, trading-ampel, darf ich traden, positionsgröße, marktumfeld, 5-minuten-kerzen, market signal, tagesanalyse, morgenroutine börse | Feiertag Marktroutine v2: Tagesanalyse + SPY 5-Min Intraday + VIX-Regime + Breadth + Trading-Ampel |
| **live-trading** | live trading, echtzeit, watchlist generieren, pre-market scan, trading session, TWS monitor, undercut alarm, intraday, live dashboard, 1-min chart, tick data, uc watch, börse live | Echtzeit-UC-Scanner: Pre-Market Watchlist → TWS Streaming → 1-Min-Bars → Tendenz-Erkennung → Desktop-Alerts |
| **feiertag-gruppe-discord** | discord, feiertag discord, livetrading kanal, was wurde gepostet, discord zusammenfassung, was sagt olli, neue setups discord, discord nachrichten, was läuft im livetrading, discord check, gruppe lesen, community update, was haben die anderen, discord heute | Feiertag Trading Academy Discord via Claude in Chrome auslesen und zusammenfassen |
| **feiertag-discord-analyse** | discord analyse, olli beispiel, praxisbeispiel, was hat olli gesagt zu, discord learnings, discord strategie, olli praxis | Praxisbeispiele aus Discord: Olli→Strategie, Christian→Ergänzung. Brücke zwischen Discord-Reader und Methodik-Skills |
| **morgenroutine-experte** | morgenroutine, mantel, mantelroutine, schedule.toml, mantel.py, launchd morgenroutine, dashboard morgenroutine, nachtbatch, job schedule, startzeit, plist morgenroutine, 00 Morgenroutine, jobs konfigurieren | Mantelroutine-Infrastruktur: TOML-gesteuerter Job-Runner, launchd, Dashboard, Schedule-Verwaltung |
| **elliott-wellen** | elliott, wellen, impulswelle, korrektur, abc, wave count, 5-3 struktur, wellengrad, zigzag, flat, triangle | Elliott-Wellen-Theorie: 5-3 Struktur, Korrekturmuster, Wave-Counting, Christians Discord-Validierung |
| **fibonacci-analyse** | fibonacci, retracement, extension, golden pocket, fib cluster, fib symmetrie, 61.8, 38.2 | Fibonacci-Analyse: Retracements, Extensions, Cluster, Christians SPX Fib Symmetrie |

### Bereits nativ in CoWork geladen (kein Nachladen nötig)

git-sync-agent, sec-data-loader, n8n-workflow-builder, youtube-traffic-skill, xlsx, pdf, docx, pptx, skill-creator, mcp-builder, canvas-design, algorithmic-art, internal-comms, schedule

## Entscheidungslog

| Datum | Entscheidung | Begründung |
|---|---|---|
| 28.03.2026 | CLAUDE.md ins Root verschoben | Unterordner "Claude Steuerung" war unnötig, Claude findet CLAUDE.md am besten im Hauptverzeichnis |
| 28.03.2026 | Zweiter Ordner für CoWork-Learnings | Meta-Learnings über CoWork getrennt vom Projekt halten, projektübergreifend wiederverwendbar |
| 28.03.2026 | CLAUDE.md als zentrale Wahrheitsquelle | Auto-Memory ist rechner-spezifisch, CLAUDE.md synct über iCloud auf beide Rechner |
| 28.03.2026 | Umbenennung auf "AI Artifakte" | Dieters eigenes Unternehmen, Feiertag Academy ist nur eine von mehreren Lernquellen |
| 01.04.2026 | Custom Skill-Registry in CLAUDE.md | Symlinks in CoWork-Sandbox broken; Lösung: Skill-Verzeichnis mit Trigger-Keywords + on-demand Laden via Filesystem-MCP |
| 01.04.2026 | feiertag-gruppe-discord Skill erstellt | Discord-Gruppe via Claude in Chrome auslesen; kein Discord-MCP verfügbar, Browser-Zugang ist einziger Weg |
| 01.04.2026 | feiertag-discord-analyse Skill erstellt | Praxisbeispiele separat sammeln statt Methodik-Skills aufzublähen; Brücke Discord→Strategie |
| 01.04.2026 | market_analysis.py v2 + markt-analyse Skill | 5-Min Intraday (OR, VWAP, Trend), Breadth-Fix (ROW_NUMBER statt Kalendertage), VIX-Regime mit Position-Sizing, Trading-Ampel |
| 03.04.2026 | elliott-wellen Skill erstellt | Vollstaendige Theorie + Christians praktische Discord-Validierung + Python-Implementation |
| 03.04.2026 | fibonacci-analyse Skill erstellt | Retracements, Extensions, Golden Pocket, SPX Fib Symmetrie + Python-Implementation |
| 03.04.2026 | Screening-Regeln in CLAUDE.md dokumentiert | 24 Regeln aus feiertag-chart-experte (Technisches Screening + Fundamentale Vorselektion), ohne Priorisierung |
