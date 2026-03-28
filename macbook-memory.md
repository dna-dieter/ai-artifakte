# Claude Auto-Memory (Export vom 29.03.2026)

Dieses Dokument ist ein Export des Claude Auto-Memory vom MacBook.
Zweck: Damit der Mac Mini denselben Kontext hat wie das MacBook.
Bei Abweichungen gilt die CLAUDE.md als zentrale Wahrheitsquelle.

---

## Index

- User-Profil — Dieter, Trading-Projekt, lernt CoWork, 2-Rechner-Setup mit iCloud
- CoWork-Learnings Ordner — Dieter will alle CoWork-Learnings im separaten Ordner "CoWork richtig benutzen" dokumentieren
- AI Artifakte – Börsenhandel — Dieters Unternehmen "AI Artifakte", Aktienhandel-System, Phase 1 aktiv seit 26.03.2026
- SEC EDGAR Pipeline — Operative Pipeline: 8.083 Firmen, 5.732 mit Facts, ~8M Facts, 2.1GB DB, tagesaktuell
- Nächste Schritte — Phase 1 done; nächste Session: Daily Ticker, Filing-Cabinet Skill, MCP-Strategie

---

## User-Profil Dieter
type: user

Dieter nutzt Claude CoWork zum ersten Mal produktiv. Er arbeitet mit einem 2-Rechner-Setup (iCloud-Sync). GitHub-ID: dna-dieter. E-Mail: dieter.nadolski@gmail.com.

Er möchte CoWork systematisch lernen und die Learnings dokumentieren. Praktische Beispiele sind ihm wichtig — er lernt am besten anhand konkreter Erfahrungen aus echten Projekten.

Sprache: Deutsch für Kommunikation, Englisch für Code.

---

## CoWork-Learnings dokumentieren
type: feedback

Dieter möchte, dass Claude bei jedem Gespräch mitlernt und neue Erkenntnisse über die Nutzung von CoWork im Dokument "CoWork richtig benutzen/COWORK-LEARNINGS.md" ergänzt.

**Why:** Das Boersenhandel-Projekt ist sein erstes richtiges CoWork-Projekt. Die Learnings sollen projektübergreifend wiederverwendbar sein und auch für andere Projekte helfen.

**How to apply:** Am Ende einer Session oder wenn ein neues Learning entsteht, das Dokument COWORK-LEARNINGS.md im Ordner "CoWork richtig benutzen" aktualisieren (neuen Eintrag im Learnings-Log mit Datum ergänzen). Trennung beachten: Projekt-Inhalte → Boersenhandel-Ordner, Meta-Learnings über CoWork → "CoWork richtig benutzen"-Ordner.

---

## AI Artifakte – Projekt Börsenhandel
type: project

Erstes produktives CoWork-Projekt von Dieter unter seinem Unternehmen "AI Artifakte". Entwicklung eines Handelssystems für US-Aktien.

**Status:** Phase 1 ✅ abgeschlossen (29.03.2026) — Filing Cabinet, SEC Pipeline, Screener komplett. Nächste Schritte: Daily Ticker Automatisierung, eigener Skill, MCP-Strategie (siehe Abschnitt "Nächste Schritte")
**Repo:** github.com/dna-dieter/exchange-dashboard → Umbenennung zu ai-artifakte geplant
**Projektstart:** 26.03.2026
**Steuerung:** CLAUDE.md im Root des Projektordners
**Masterplan:** PROJEKTPLAN.md (umbenannt von PROJEKTPLAN-Boersenhandel.md)

**Lernquellen:** Feiertag Trading Academy + weitere geplant (nicht exklusiv an eine Methodik gebunden)

**Why:** Dieter handelt Aktien und möchte den Prozess unter seiner Marke "AI Artifakte" systematisieren und automatisieren. Feiertag Academy ist eine von mehreren Lernquellen.

**How to apply:** Bei Arbeit am Projekt immer den Projektplan und die CLAUDE.md als Kontext nutzen. Fortschritt dort dokumentieren. Branding: "AI Artifakte" als übergreifender Titel.

---

## SEC EDGAR Pipeline operativ
type: project

Dieters SEC EDGAR Pipeline ist operativ (Stand 28.03.2026). Standort: iCloud Drive > Dokumente > SEC filing

**Datenbank (sec_data.db, ~2.1GB SQLite):**
- 8.083 Unternehmen, 5.732 mit Bewegungsdaten (has_facts=1)
- 7.916.627 Financial Facts im EAV-Modell
- Zeitraum: ca. 2009–2026, tagesaktuell
- View `v_financials`: Pivot-Sicht mit revenue, net_income, eps_diluted, assets, equity, cash etc.
- companies-Tabelle hat fiscal_year_end (MMDD), exchange, sic, category

**Screening-relevante DB-Felder:**
- v_financials.revenue → Sales Growth
- v_financials.net_income → Earnings Growth
- v_financials.fiscal_period → Q1/Q2/Q3/Q4/FY
- v_financials.form → 10-K vs 10-Q
- companies.fiscal_year_end → Für 10-K-Regel (MMDD)

**Automatisierung:**
- Delta-Update Di–Sa 2:00 via macOS launchd (com.sec.update.plist)
- Retry: 5 Versuche, 5 Min Pause
- Status-Dashboard: dna-dieter.github.io/sec-filing-status/

**Skripte (NUR LESEN!):**
- load_sec_data.py — Erstaufbau (~3 Min)
- enrich_companies.py — Stammdaten anreichern (~15 Min)
- update_sec_data.py — Tägliches Delta (~2–5 Min)

**Why:** Phase 1 (Datenbeschaffung) ist de facto abgeschlossen. Die Pipeline läuft autonom.

**How to apply:** Screening-Engine kann direkt SQL gegen v_financials/sec_data.db fahren. Ordner ist READ-ONLY für Claude. Nicht anfassen, nur als Datenquelle nutzen.

---

## Nächste Schritte nach Phase 1
type: project

Phase 1 (Filing Cabinet, SEC Pipeline, Screener) ist abgeschlossen (29.03.2026). Drei nächste Themen:

**1. Daily Ticker Automatisierung**
agent_filing_cabinet.py soll täglich automatisch laufen, filing_cabinet.html neu generieren und auf GitHub Pages deployen. Analog zum bestehenden launchd-Job (feiertag_daily_report.py, Di-Sa 02:30).

**Why:** Filing Cabinet zeigt aktuell einen Snapshot. Ohne tägliche Regenerierung veralten Kursdaten, Scores und Factsheets.
**How to apply:** Skript für täglichen Lauf einrichten (launchd oder scheduled-task), inkl. Git-Push auf exchange-dashboard.

**2. Eigenen Filing-Cabinet Skill erstellen**
Mit dem skill-creator Skill eine SKILL.md bauen, die die komplette Filing-Cabinet-Generierung beschreibt (DB-Abfragen, OV-Array-Format 13 Elemente, Factsheet-Struktur, Pre-Filter $500M/10%/10%, HTML-Generierung). Dann reicht künftig "aktualisiere das Filing Cabinet" als Anweisung.

**Why:** Aktuell muss Claude jedes Mal den gesamten Kontext aus dem Code und der Session-History rekonstruieren. Ein Skill macht das reproduzierbar.
**How to apply:** skill-creator Skill nutzen, SKILL.md unter .claude/skills/ anlegen.

**3. MCP/Plugin-Strategie für Trading-System**
Evaluieren ob ein eigener MCP-Server sinnvoll wäre (z.B. für direkte SQL-Abfragen auf feiertag_trading.db/sec_data.db). Connectors für GitHub und Gmail sind bereits aktiv. Ein gebündeltes "Trading Plugin" wäre erst sinnvoll wenn mehrere Skills + Connectors zusammenkommen.

**Why:** Dieter fragte nach dem Unterschied Skills vs. Connectors vs. Plugins. Empfehlung: Skill zuerst (einfachster Mehrwert), MCP-Server für DB-Zugriff als Phase-2-Projekt, Plugin erst bei Reife.
**How to apply:** Morgen mit Skill starten, MCP-Server als separates Thema planen.
