"""
AI Artifakte — Gewichtetes YoY-Wachstum
=========================================
Wiederverwendbare Funktion fuer gewichtetes Revenue/Net-Income-Wachstum
basierend auf den juengsten 2 echten 10-Q Berichten.

Regel:
  - Nur echte 10-Q Filings (kein c-sec, kein 'd')
  - Juengster 10-Q: Gewichtung W1 = 0.67
  - Vorletzter 10-Q: Gewichtung W2 = 0.33
  - YoY: Vergleich mit dem gleichen Quartal im Vorjahr
  - Turnaround (Verlust → Gewinn): wird als +999% gewertet

USAGE:
  from calc_weighted_growth import calc_weighted_growth

  rev_w, net_w = calc_weighted_growth(cursor, 'AAPL')
  # rev_w = gewichtetes Revenue-Wachstum in % (oder None)
  # net_w = gewichtetes Net-Income-Wachstum in % (oder None)
"""


# Gewichtung: juengster 10-Q 67%, vorletzter 33%
W1 = 0.67
W2 = 0.33

# Turnaround-Cap: Verlust → Gewinn wird als dieser %-Wert gewertet
TURNAROUND_PCT = 999


def calc_weighted_growth(cur, sym, w1=W1, w2=W2):
    """Berechne gewichtetes YoY-Wachstum fuer Revenue und Net Income.

    Verwendet die 2 juengsten echten 10-Q Berichte und vergleicht
    jedes Quartal mit dem gleichen Quartal im Vorjahr.

    Args:
        cur: sqlite3 Cursor (feiertag_trading.db)
        sym: Ticker-Symbol (z.B. 'AAPL')
        w1:  Gewichtung juengster 10-Q (default 0.67)
        w2:  Gewichtung vorletzter 10-Q (default 0.33)

    Returns:
        (rev_w, net_w) — jeweils float (gerundet auf 1 Dezimale) oder None
        rev_w: gewichtetes Revenue-Wachstum YoY in %
        net_w: gewichtetes Net-Income-Wachstum YoY in %
    """
    # Juengste 2 echte 10-Q Berichte mit gueltigen Daten
    frows = cur.execute("""
        SELECT fin_qtr, fin_qtr_rev, fin_qtr_net
        FROM t_fin_financials
        WHERE fin_sym = ?
          AND fin_filed_10q IS NOT NULL AND fin_filed_10q != ''
          AND fin_qtr_rev IS NOT NULL AND fin_qtr_rev != 0
          AND fin_qtr_net IS NOT NULL AND fin_qtr_net != 0
        ORDER BY fin_qtr DESC
        LIMIT 2
    """, (sym,)).fetchall()

    if len(frows) < 2:
        return None, None

    q1, rv1, nt1 = frows[0]   # juengster
    q2, rv2, nt2 = frows[1]   # vorletzter

    # Vorjahresquartale berechnen (z.B. '2025-Q3' → '2024-Q3')
    yq1 = str(int(q1[:4]) - 1) + q1[4:]
    yq2 = str(int(q2[:4]) - 1) + q2[4:]

    # Vorjahresdaten laden
    y1 = cur.execute(
        "SELECT fin_qtr_rev, fin_qtr_net FROM t_fin_financials WHERE fin_sym=? AND fin_qtr=?",
        (sym, yq1)
    ).fetchone()
    y2 = cur.execute(
        "SELECT fin_qtr_rev, fin_qtr_net FROM t_fin_financials WHERE fin_sym=? AND fin_qtr=?",
        (sym, yq2)
    ).fetchone()

    if not y1 or not y2:
        return None, None

    yr1 = y1[0] or 0   # Revenue Vorjahr Q1
    yr2 = y2[0] or 0   # Revenue Vorjahr Q2
    yn1 = y1[1] or 0   # Net Income Vorjahr Q1
    yn2 = y2[1] or 0   # Net Income Vorjahr Q2

    # Revenue-Wachstum (gewichtet)
    rev_w = None
    if yr1 != 0 and yr2 != 0:
        rev_g1 = (rv1 / yr1 - 1) * 100
        rev_g2 = (rv2 / yr2 - 1) * 100
        rev_w = round(rev_g1 * w1 + rev_g2 * w2, 1)

    # Net-Income-Wachstum (gewichtet, mit Turnaround-Logik)
    net_w = None
    if yn1 != 0 and yn2 != 0:
        # Turnaround: Verlust im Vorjahr → Gewinn jetzt = +999%
        g1 = TURNAROUND_PCT if (yn1 < 0 and nt1 > 0) else (nt1 / yn1 - 1) * 100
        g2 = TURNAROUND_PCT if (yn2 < 0 and nt2 > 0) else (nt2 / yn2 - 1) * 100
        net_w = round(g1 * w1 + g2 * w2, 1)

    return rev_w, net_w


def calc_market_cap_sec(cur, sym, kurs):
    """Berechne Market Cap aus SEC-Daten.

    Prioritaet:
    1. Shares Outstanding (SEC DEI) × aktueller Kurs
    2. Public Float aus 10-K (bereits in USD, als Proxy)

    Args:
        cur: sqlite3 Cursor (feiertag_trading.db)
        sym: Ticker-Symbol
        kurs: Aktueller Aktienkurs in USD

    Returns:
        float — Market Cap in USD (0 wenn nicht berechenbar)
    """
    if kurs <= 0:
        return 0

    shr_row = cur.execute("""
        SELECT fin_qtr_shr_sec, fin_ann_public_float
        FROM t_fin_financials
        WHERE fin_sym = ?
          AND ((fin_qtr_shr_sec IS NOT NULL AND fin_qtr_shr_sec > 0)
               OR (fin_ann_public_float IS NOT NULL AND fin_ann_public_float > 0))
        ORDER BY fin_qtr DESC
        LIMIT 1
    """, (sym,)).fetchone()

    if not shr_row:
        return 0

    shr = shr_row[0] if shr_row[0] and shr_row[0] > 0 else 0
    pf = shr_row[1] if shr_row[1] and shr_row[1] > 0 else 0

    if shr > 0:
        return shr * kurs
    return pf  # Public Float ist bereits ein USD-Wert
