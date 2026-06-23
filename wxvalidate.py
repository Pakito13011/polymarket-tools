# VALIDATION HORS-ECHANTILLON de la strategie "parier seulement les villes rentables".
# 1) coupe l'historique des paris resolus en 2 par la date (moitie APPRENTISSAGE / moitie TEST)
# 2) sur l'APPRENTISSAGE : identifie les villes rentables (P&L net > 0, n >= MIN_TRAIN)
# 3) sur le TEST (jamais utilise pour choisir) : applique CE filtre de villes et mesure le P&L
# Si les villes choisies sur l'apprentissage gagnent AUSSI sur le test -> edge reel & durable.
# Si elles perdent sur le test -> c'etait du sur-ajustement (bruit).
import csv, glob
from collections import defaultdict

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
EDGE_MIN = 0.08
STAKE = 10.0
SLIP = 0.04
MIN_TRAIN = 2   # nb mini de paris sur l'apprentissage pour retenir une ville


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
    res = {}
    res_ts = {}
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


def city_pnl(bets, slip):
    d = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for _, city, cost, won in bets:
        d[city]["n"] += 1
        d[city]["pnl"] += pnl_one(cost, won, slip)
    return d


def main():
    bets = build_bets()
    if len(bets) < 20:
        print("Pas assez de paris resolus pour une validation hors-echantillon (%d). Reviens plus tard." % len(bets))
        return
    mid = len(bets) // 2
    train = bets[:mid]
    test = bets[mid:]
    d0, d1 = train[0][0][:10], train[-1][0][:10]
    e0, e1 = test[0][0][:10], test[-1][0][:10]

    print("=" * 64)
    print("VALIDATION HORS-ECHANTILLON")
    print("=" * 64)
    print("Apprentissage : %d paris (%s -> %s)" % (len(train), d0, d1))
    print("Test          : %d paris (%s -> %s)" % (len(test), e0, e1))
    print("Slippage applique : %.0f%%\n" % (SLIP * 100))

    tr = city_pnl(train, SLIP)
    selected = sorted([c for c, v in tr.items() if v["pnl"] > 0 and v["n"] >= MIN_TRAIN])
    print("Villes RENTABLES sur l'apprentissage (P&L net>0, n>=%d) : %d" % (MIN_TRAIN, len(selected)))
    print("  ", ", ".join(selected) if selected else "(aucune)")

    print("\n--- REFERENCE : parier TOUTES les villes ---")
    for label, b in (("Apprentissage", train), ("Test", test)):
        n, w, pnl, roi = summarize(b, SLIP)
        print("  %-14s : %3d paris | win %4.1f%% | P&L %+7.1f EUR | ROI %+5.1f%%"
              % (label, n, 100.0 * w / n, pnl, roi))

    test_sel = [b for b in test if b[1] in selected]
    print("\n--- STRATEGIE : parier seulement les villes choisies sur l'apprentissage ---")
    n_tr, w_tr, pnl_tr, roi_tr = summarize([b for b in train if b[1] in selected], SLIP)
    print("  Apprentissage (in-sample, biaise) : %3d paris | win %4.1f%% | ROI %+5.1f%%"
          % (n_tr, (100.0 * w_tr / n_tr if n_tr else 0), roi_tr))
    if test_sel:
        n_te, w_te, pnl_te, roi_te = summarize(test_sel, SLIP)
        print("  >> TEST (hors-echantillon, HONNETE) : %3d paris | win %4.1f%% | P&L %+7.1f EUR | ROI %+5.1f%%"
              % (n_te, 100.0 * w_te / n_te, pnl_te, roi_te))
        print("\n" + "=" * 64)
        if roi_te > 2:
            print("VERDICT : les villes selectionnees RESTENT rentables hors-echantillon (ROI %+.1f%%)." % roi_te)
            print("=> Signe d'un edge geographique REEL et durable (a confirmer sur plus de donnees).")
        elif roi_te > -2:
            print("VERDICT : a l'equilibre hors-echantillon (ROI %+.1f%%). Non concluant." % roi_te)
            print("=> L'edge geographique n'est pas clairement demontre. Plus de donnees necessaires.")
        else:
            print("VERDICT : les villes 'gagnantes' PERDENT hors-echantillon (ROI %+.1f%%)." % roi_te)
            print("=> C'etait du SUR-AJUSTEMENT. Pas d'edge geographique exploitable.")
        print("=" * 64)
    else:
        print("  Aucune ville selectionnee n'apparait dans la periode de test.")
        print("  (les villes ne se recouvrent pas entre les deux periodes -> test impossible pour l'instant)")

    if test_sel:
        print("\nDetail des villes selectionnees, sur le TEST :")
        te = city_pnl(test, SLIP)
        print("%-16s %5s %10s" % ("ville", "n_test", "P&L net"))
        for c in selected:
            if c in te:
                print("%-16s %5d %+10.1f" % (c, te[c]["n"], te[c]["pnl"]))
            else:
                print("%-16s %5s %10s" % (c, "0", "(absente)"))


if __name__ == "__main__":
    main()
