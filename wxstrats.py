# Comparaison de strategies en WALK-FORWARD (chaque decision n'utilise QUE le passe).
# On rejoue les paris resolus dans l'ordre chronologique. Pour chaque pari, on regarde
# le bilan par ville construit avec les paris DEJA resolus AVANT lui, puis on decide la mise.
# 4 strategies tournent en parallele :
#   GLOBALE    : mise fixe sur tout (reference neutre)
#   CONVICTION : mise majoree sur villes a bon bilan passe ; mise normale sinon
#   EXCLUSION  : comme globale mais ne parie PAS les villes a mauvais bilan passe
#   INVERSE    : parie le COTE OPPOSE sur les villes a mauvais bilan passe (test diagnostique)
import csv, glob
from collections import defaultdict

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
EDGE_MIN = 0.08
STAKE = 10.0          # mise de base
BIG = 30.0            # mise "conviction"
SLIP = 0.04
MIN_HIST = 3          # nb mini de paris passes sur une ville pour la "juger"
GOOD_WR = 0.60        # win rate passe au-dessus duquel une ville est "valeur sure"
BAD_WR = 0.40         # win rate passe en-dessous duquel une ville est "a fuir"


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
        cost = price if side == "YES" else (1.0 - price)
        if cost <= 0 or cost >= 1:
            continue
        bets.append({"ts": res_ts.get(t, ""), "city": (h.get("city") or "?").strip(),
                     "cost": cost, "side": side, "won_event": won})
    bets.sort(key=lambda b: b["ts"])
    return bets


def settle(cost, bet_wins, stake):
    eff = min(cost * (1.0 + SLIP), 0.999)
    return stake * (1.0 / eff - 1.0) if bet_wins else -stake


def main():
    bets = build_bets()
    if not bets:
        print("Aucun pari resolu exploitable.")
        return

    seen = defaultdict(lambda: {"n": 0, "w": 0})

    strat = {k: {"n": 0, "w": 0, "stake": 0.0, "pnl": 0.0} for k in
             ("GLOBALE", "CONVICTION", "EXCLUSION", "INVERSE")}

    def record(name, cost, bet_wins, stake):
        s = strat[name]
        s["n"] += 1
        s["w"] += 1 if bet_wins else 0
        s["stake"] += stake
        s["pnl"] += settle(cost, bet_wins, stake)

    for b in bets:
        city = b["city"]
        side = b["side"]
        cost = b["cost"]
        bet_wins = (b["won_event"] == 1) if side == "YES" else (b["won_event"] == 0)

        h = seen[city]
        past_n = h["n"]
        past_wr = (h["w"] / past_n) if past_n else None

        is_good = (past_n >= MIN_HIST and past_wr is not None and past_wr >= GOOD_WR)
        is_bad = (past_n >= MIN_HIST and past_wr is not None and past_wr <= BAD_WR)

        record("GLOBALE", cost, bet_wins, STAKE)
        record("CONVICTION", cost, bet_wins, BIG if is_good else STAKE)
        if not is_bad:
            record("EXCLUSION", cost, bet_wins, STAKE)
        if is_bad:
            inv_wins = not bet_wins
            record("INVERSE", 1.0 - cost, inv_wins, STAKE)

        h["n"] += 1
        h["w"] += 1 if bet_wins else 0

    print("=" * 72)
    print("COMPARAISON DE STRATEGIES (walk-forward, slippage %.0f%%, %d paris au total)" % (SLIP * 100, len(bets)))
    print("=" * 72)
    print("Regles: ville 'sure' = win passe >= %.0f%% sur >= %d paris | 'a fuir' = win passe <= %.0f%%"
          % (GOOD_WR * 100, MIN_HIST, BAD_WR * 100))
    print("Mise base %.0f EUR, mise conviction %.0f EUR.\n" % (STAKE, BIG))
    print("%-12s %6s %7s %10s %9s %8s" % ("strategie", "paris", "win%", "mise tot", "P&L net", "ROI%"))
    print("-" * 60)
    order = ["GLOBALE", "CONVICTION", "EXCLUSION", "INVERSE"]
    for k in order:
        s = strat[k]
        if s["n"] == 0:
            print("%-12s %6d %7s %10s %9s %8s" % (k, 0, "-", "-", "-", "-"))
            continue
        wr = 100.0 * s["w"] / s["n"]
        roi = 100.0 * s["pnl"] / s["stake"] if s["stake"] else 0.0
        print("%-12s %6d %6.1f%% %10.0f %+9.1f %+7.1f" % (k, s["n"], wr, s["stake"], s["pnl"], roi))

    print("\nLecture :")
    print("- Si CONVICTION bat GLOBALE -> surponderer les villes a bon historique a une valeur predictive.")
    print("- Si EXCLUSION bat GLOBALE -> eviter les villes a mauvais historique ameliore le resultat.")
    print("- Si INVERSE est POSITIF -> nos 'perdantes' ont un biais retournable (exploitable en inversant).")
    print("  Si INVERSE est negatif -> nos 'perdantes' sont juste du bruit (a exclure, pas a inverser).")
    print("\nWalk-forward = chaque decision n'a utilise QUE les paris anterieurs (aucune triche par le futur).")
    print("NB: fiabilite croit avec le nombre de paris ET de jours. Encore indicatif sur peu de donnees.")


if __name__ == "__main__":
    main()
