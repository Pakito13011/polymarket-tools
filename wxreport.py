# BILAN GLOBAL du paper-trading meteo (archive permanente) AVEC slippage.
# Croise resolutions.csv (resultat) x wxhist*.csv (snapshot d'entree = prix + cote).
# Affiche ROI BRUT (prix midpoint) et ROI NET a plusieurs niveaux de slippage.
import csv, glob
from collections import defaultdict

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
EDGE_MIN = 0.08
STAKE = 10.0
SLIPPAGE_LEVELS = [0.0, 0.03, 0.04, 0.05, 0.08]   # 0 = brut ; puis friction croissante
REPORT_SLIP = 0.04   # niveau utilise pour la ventilation par ville


def last_per_token():
    last = {}
    for path in glob.glob(HIST_GLOB):
        try:
            with open(path) as f:
                for row in csv.DictReader(f):
                    t = row.get("token")
                    if not t:
                        continue
                    if t not in last or row.get("ts_utc", "") > last[t].get("ts_utc", ""):
                        last[t] = row
        except Exception:
            pass
    return last


def pnl_one(cost, won_bet, slip):
    # cost = prix paye pour 1 part (YES: prix ; NO: 1-prix). slip degrade le cout d'entree.
    eff = cost * (1.0 + slip)
    if eff >= 1.0:
        eff = 0.999   # securite : on ne peut pas payer >= 1 par part
    if won_bet:
        return STAKE * (1.0 / eff - 1.0)
    return -STAKE


def main():
    results = {}
    try:
        with open(RES) as f:
            for row in csv.DictReader(f):
                t = row.get("token")
                if t:
                    try:
                        results[t] = int(row.get("won", "0"))
                    except Exception:
                        pass
    except FileNotFoundError:
        print("resolutions.csv introuvable. Lance d'abord wxresolve.py.")
        return
    if not results:
        print("Aucune resolution gravee pour l'instant.")
        return
    hist = last_per_token()

    bets = []   # (city, cost, bet_won)
    wins = 0
    sum_cost = sum_model = 0.0
    no_entry = 0
    for t, won in results.items():
        row = hist.get(t)
        if not row:
            no_entry += 1
            continue
        try:
            price = float(row.get("price"))
            model = float(row.get("model"))
        except Exception:
            continue
        if abs(model - price) < EDGE_MIN:
            continue
        side = "YES" if model > price else "NO"
        bet_won = (won == 1) if side == "YES" else (won == 0)
        cost = price if side == "YES" else (1.0 - price)
        if cost <= 0 or cost >= 1:
            continue
        city = (row.get("city") or "?").strip()
        bets.append((city, cost, bet_won))
        if bet_won:
            wins += 1
        sum_cost += cost
        sum_model += (model if side == "YES" else 1.0 - model)

    n = len(bets)
    print("=" * 64)
    print("BILAN PAPER-TRADING METEO (archive permanente)")
    print("=" * 64)
    print("Resolutions gravees au total : %d" % len(results))
    print("  exploitables (entree connue + edge>=%.0fpts) : %d" % (EDGE_MIN * 100, n))
    if no_entry:
        print("  (%d resolutions sans snapshot d'entree -> ignorees)" % no_entry)
    if n == 0:
        print("\nAucun pari exploitable.")
        return
    wr = 100.0 * wins / n
    imp = 100.0 * sum_cost / n
    mod = 100.0 * sum_model / n
    print("\nPARIS            : %d (gagnes %d, perdus %d)" % (n, wins, n - wins))
    print("WIN RATE REEL    : %.1f%%  | implicite marche : %.1f%%  | modele moy : %.1f%%" % (wr, imp, mod))
    print("Win rate %s le marche de %.1f pts."
          % ("AU-DESSUS" if wr > imp else "SOUS/AU NIVEAU", abs(wr - imp)))

    print("\n" + "-" * 64)
    print("RENTABILITE selon le SLIPPAGE (mise %.0f/pari, %d paris)" % (STAKE, n))
    print("-" * 64)
    print("%-22s %12s %9s" % ("slippage / friction", "P&L EUR", "ROI%"))
    for slip in SLIPPAGE_LEVELS:
        tot = sum(pnl_one(c, w, slip) for _, c, w in bets)
        roi = 100.0 * tot / (STAKE * n)
        tag = "BRUT (theorique)" if slip == 0 else "%.0f%% par pari" % (slip * 100)
        print("%-22s %+12.1f %+8.1f" % (tag, tot, roi))
    print("(le slippage degrade le prix d'entree ; mesure dans wxdepth ~3-5%% cote temperature)")

    by_city = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for city, cost, won_bet in bets:
        d = by_city[city]
        d["n"] += 1
        d["w"] += 1 if won_bet else 0
        d["pnl"] += pnl_one(cost, won_bet, REPORT_SLIP)
    print("\n" + "-" * 64)
    print("VENTILATION PAR VILLE (P&L NET a %.0f%% slippage, triee)" % (REPORT_SLIP * 100))
    print("-" * 64)
    print("%-16s %4s %4s %10s %8s" % ("ville", "n", "win", "P&L EUR", "ROI%"))
    rows = []
    for city, d in by_city.items():
        r = 100.0 * d["pnl"] / (STAKE * d["n"]) if d["n"] else 0.0
        rows.append((d["pnl"], city, d["n"], d["w"], r))
    rows.sort(reverse=True)
    for pnl_c, city, nn, w, r in rows:
        print("%-16s %4d %4d %+10.1f %+7.1f" % (city, nn, w, pnl_c, r))
    if len(rows) >= 2:
        pos = [(p, c) for p, c, nn, w, r in rows if p > 0]
        neg = [(p, c) for p, c, nn, w, r in rows if p < 0]
        print("\n+ RENTABLES (net):", ", ".join("%s (%+.0f)" % (c, p) for p, c in pos[:3]))
        print("+ COUTEUSES (net):", ", ".join("%s (%+.0f)" % (c, p) for p, c in sorted(neg)[:3]))
    print("\nNB: slippage forfaitaire = APPROXIMATION. Sur carnets tres fins (cote YES souvent")
    print("quasi vide), le slippage reel serait pire, voire le pari impossible. Net = encore optimiste.")


if __name__ == "__main__":
    main()
