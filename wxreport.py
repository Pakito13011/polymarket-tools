# BILAN GLOBAL du paper-trading meteo, a partir de l'archive permanente.
# Croise resolutions.csv (resultat fige) avec wxhist*.csv (dernier snapshot avant cloture
# = prix d'entree + cote du pari). Calcule : nb resolutions, win rate, P&L, ROI,
# et la ventilation par ville (qui rapporte / qui coute).
import csv, glob
from collections import defaultdict

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
EDGE_MIN = 0.08      # on ne "parie" que les marches ou |modele - prix| >= 8 pts (comme wxsettle)
STAKE = 10.0


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

    total_bets = 0
    wins = 0
    pnl = 0.0
    sum_cost = 0.0
    sum_model = 0.0
    by_city = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
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
        edge = model - price
        if abs(edge) < EDGE_MIN:
            continue
        side = "YES" if model > price else "NO"
        bet_won = (won == 1) if side == "YES" else (won == 0)
        cost = price if side == "YES" else (1.0 - price)
        if cost <= 0 or cost >= 1:
            continue
        city = (row.get("city") or "?").strip()
        total_bets += 1
        sum_cost += cost
        sum_model += (model if side == "YES" else 1.0 - model)
        by_city[city]["n"] += 1
        if bet_won:
            wins += 1
            gain = STAKE * (1.0 / cost - 1.0)
            pnl += gain
            by_city[city]["w"] += 1
            by_city[city]["pnl"] += gain
        else:
            pnl -= STAKE
            by_city[city]["pnl"] -= STAKE

    print("=" * 60)
    print("BILAN PAPER-TRADING METEO (archive permanente)")
    print("=" * 60)
    print("Resolutions gravees au total      : %d" % len(results))
    print("  dont exploitables (entree connue + edge>=%.0fpts) : %d" % (EDGE_MIN * 100, total_bets))
    if no_entry:
        print("  (%d resolutions sans snapshot d'entree dans wxhist -> ignorees)" % no_entry)
    if total_bets == 0:
        print("\nAucun pari exploitable (il faut que wxhist contienne le snapshot d'entree des tokens resolus).")
        return
    wr = 100.0 * wins / total_bets
    imp = 100.0 * sum_cost / total_bets
    mod = 100.0 * sum_model / total_bets
    roi = 100.0 * pnl / (STAKE * total_bets)
    print("\nPARIS              : %d (gagnes %d, perdus %d)" % (total_bets, wins, total_bets - wins))
    print("WIN RATE REEL      : %.1f%%" % wr)
    print("Implicite marche   : %.1f%%  (moyenne du prix paye)" % imp)
    print("Proba modele moy.  : %.1f%%" % mod)
    print("P&L paper          : %+.1f EUR  (mise %.0f/pari)" % (pnl, STAKE))
    print("ROI                : %+.1f%%" % roi)
    if wr > imp:
        print(">> Win rate AU-DESSUS du marche de %.1f pts." % (wr - imp))
    else:
        print(">> Win rate au niveau/sous le marche.")

    print("\n" + "-" * 60)
    print("VENTILATION PAR VILLE (triee par P&L)")
    print("-" * 60)
    print("%-16s %4s %4s %9s %8s" % ("ville", "n", "win", "P&L EUR", "ROI%"))
    rows = []
    for city, d in by_city.items():
        r = 100.0 * d["pnl"] / (STAKE * d["n"]) if d["n"] else 0.0
        rows.append((d["pnl"], city, d["n"], d["w"], r))
    rows.sort(reverse=True)
    for pnl_c, city, n, w, r in rows:
        print("%-16s %4d %4d %+9.1f %+7.1f" % (city, n, w, pnl_c, r))

    if len(rows) >= 2:
        print("\nVilles les + RENTABLES :", ", ".join("%s (%+.0f)" % (c, p) for p, c, n, w, r in rows[:3] if p > 0))
        losers = [(p, c) for p, c, n, w, r in rows if p < 0]
        print("Villes les + COUTEUSES :", ", ".join("%s (%+.0f)" % (c, p) for p, c in sorted(losers)[:3]))
    print("\nNB: P&L paper, mise fixe, hors slippage (qui amputerait encore ~3-5%/pari).")
    print("Plus l'archive grandit (cron 2x/jour), plus ces chiffres deviennent fiables.")


if __name__ == "__main__":
    main()
