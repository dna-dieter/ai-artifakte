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

## Feedback & Präferenzen (was Claude sich merken soll)

- **Konsistenz über 2 Rechner:** Dieter bevorzugt strikte Konsistenz. Alles Projektrelevante in diese CLAUDE.md, nicht nur ins Auto-Memory.
- **Iterativ arbeiten:** Nicht alles auf einmal, sondern Schritt für Schritt. Claude fragt nach, wenn etwas unklar ist.
- **CLAUDE.md ins Hauptverzeichnis:** Keine Unterordner für Steuerungsdateien. CLAUDE.md gehört direkt ins Root des Projektordners.

## Entscheidungslog

| Datum | Entscheidung | Begründung |
|---|---|---|
| 28.03.2026 | CLAUDE.md ins Root verschoben | Unterordner "Claude Steuerung" war unnötig, Claude findet CLAUDE.md am besten im Hauptverzeichnis |
| 28.03.2026 | Zweiter Ordner für CoWork-Learnings | Meta-Learnings über CoWork getrennt vom Projekt halten, projektübergreifend wiederverwendbar |
| 28.03.2026 | CLAUDE.md als zentrale Wahrheitsquelle | Auto-Memory ist rechner-spezifisch, CLAUDE.md synct über iCloud auf beide Rechner |
| 28.03.2026 | Umbenennung auf "AI Artifakte" | Dieters eigenes Unternehmen, Feiertag Academy ist nur eine von mehreren Lernquellen |