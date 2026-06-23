# VALIDATION HORS-ECHANTILLON + comparatif par ville (ROI apprentissage vs ROI test).
# Coupe les paris resolus en 2 par la date. Montre, pour chaque ville, si sa performance
# TIENT entre la periode d'apprentissage et la periode de test (jamais utilisee pour choisir).
import csv, glob
from collections import defaultdict

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
EDGE_MIN = 0.08
STAKE = 10.0
SLIP = 0.04
MIN_TRAIN = 2


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
    eff = min(cost * (1.0 + slip), 0.999)
    return STAKE * (1.0 / eff - 1.0) if won_bet else -STAKE


def build_bets():
    res, res_ts = {}, {}
    with open(RES) as f:
        for row in csv.DictReader(f):
            t = row.get("token")
            if not t:
                continue
            try:
                res[t] = int(row.get("won", "0"))
                res_ts[t] = row.get("resolved_ts", "")
            except Exception:
                pass
    hist = last_per_token()
    bets = []
    for t, won in res.items():
        h = hist.get(t)
        if not h:
            continue
        try:
            price = float(h.get("price")); model = float(h.get("model"))
        except Exception:
            continue
        if abs(model - price) < EDGE_MIN:
            continue
        side = "YES" if model > price else "NO"
        won_bet = (won == 1) if side == "YES" else (won == 0)
        cost = price if side == "YES" else (1.0 - price)
        if cost <= 0 or cost >= 1:
            continue
        bets.append((res_ts.get(t, ""), (h.get("city") or "?").strip(), cost, won_bet))
    bets.sort(key=lambda b: b[0])
    return bets


def summarize(bets, slip):
    n = len(bets)
    if not n:
        return 0, 0, 0.0, 0.0
    wins = sum(1 for b in bets if b[3])
    pnl = sum(pnl_one(c, w, slip) for _, _, c, w in bets)
    return n, wins, pnl, 100.0 * pnl / (STAKE * n)


def city_stats(bets, slip):
    d = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for _, city, cost, won in bets:
        d[city]["n"] += 1
        d[city]["w"] += 1 if won else 0
        d[city]["pnl"] += pnl_one(cost, won, slip)
    return d


def main():
    bets = build_bets()
    if len(bets) < 20:
        print("Pas assez de paris resolus (%d)." % len(bets))
        return
    mid = len(bets) // 2
    train, test = bets[:mid], bets[mid:]
    print("=" * 72)
    print("VALIDATION HORS-ECHANTILLON  (slippage %.0f%%)" % (SLIP * 100))
    print("=" * 72)
    print("Apprentissage : %d paris (%s -> %s)" % (len(train), train[0][0][:10], train[-1][0][:10]))
    print("Test          : %d paris (%s -> %s)" % (len(test), test[0][0][:10], test[-1][0][:10]))

    days_train = len(set(b[0][:10] for b in train))
    days_test = len(set(b[0][:10] for b in test))
    if days_train <= 2 or days_test <= 2:
        print("\n*** ATTENTION : apprentissage sur %d jour(s), test sur %d jour(s). ***" % (days_train, days_test))
        print("*** Trop peu de jours distincts -> validation NON FIABLE (donnees pas etalees dans le temps). ***")
        print("*** Resultats indicatifs seulement. Laisser accumuler plusieurs semaines. ***")

    trs = city_stats(train, SLIP)
    selected = sorted([c for c, v in trs.items() if v["pnl"] > 0 and v["n"] >= MIN_TRAIN])

    print("\n--- REFERENCE : parier TOUTES les villes ---")
    for label, b in (("Apprentissage", train), ("Test", test)):
        n, w, pnl, roi = summarize(b, SLIP)
        print("  %-14s : %3d paris | win %4.1f%% | P&L %+7.1f | ROI %+6.1f%%" % (label, n, 100.0 * w / n, pnl, roi))

    tes = city_stats(test, SLIP)
    print("\n--- STRATEGIE : villes rentables sur l'apprentissage, mesurees sur le TEST ---")
    n_te, w_te, pnl_te, roi_te = summarize([b for b in test if b[1] in selected], SLIP)
    if n_te:
        print("  TEST hors-echantillon : %d paris | win %4.1f%% | P&L %+7.1f | ROI %+6.1f%%"
              % (n_te, 100.0 * w_te / n_te, pnl_te, roi_te))

    print("\n" + "=" * 72)
    print("COMPARATIF PAR VILLE : performance APPRENTISSAGE vs TEST")
    print("=" * 72)
    print("(une vraie 'bonne' ville reste positive dans les DEUX colonnes)")
    print("%-15s | %-22s | %-22s | %s" % ("ville", "APPRENTISSAGE", "TEST (honnete)", "verdict"))
    print("%-15s | %-22s | %-22s |" % ("", "n  win%   ROI%", "n  win%   ROI%"))
    print("-" * 72)
    all_cities = sorted(set(list(trs.keys()) + list(tes.keys())),
                        key=lambda c: -(trs[c]["pnl"] if c in trs else 0))
    for c in all_cities:
        a = trs.get(c, {"n": 0, "w": 0, "pnl": 0.0})
        t = tes.get(c, {"n": 0, "w": 0, "pnl": 0.0})
        aroi = 100.0 * a["pnl"] / (STAKE * a["n"]) if a["n"] else 0.0
        troi = 100.0 * t["pnl"] / (STAKE * t["n"]) if t["n"] else 0.0
        astr = "%2d %5.0f%% %+6.0f%%" % (a["n"], 100.0 * a["w"] / a["n"], aroi) if a["n"] else " -      -       - "
        tstr = "%2d %5.0f%% %+6.0f%%" % (t["n"], 100.0 * t["w"] / t["n"], troi) if t["n"] else " -      -       - "
        if a["n"] >= MIN_TRAIN and a["pnl"] > 0:
            if t["n"] == 0:
                v = "? pas de test"
            elif t["pnl"] > 0:
                v = "TIENT"
            else:
                v = "S'EFFONDRE"
        else:
            v = ""
        print("%-15s | %-22s | %-22s | %s" % (c, astr, tstr, v))

    print("\nLecture : 'TIENT' = rentable en apprentissage ET en test (candidate serieuse).")
    print("'S'EFFONDRE' = gagnait en apprentissage mais PERD en test = sur-ajustement (mirage).")
    print("Sur peu de jours/paris, meme 'TIENT' reste a confirmer. Le nombre de paris par case est la cle.")


if __name__ == "__main__":
    main()
