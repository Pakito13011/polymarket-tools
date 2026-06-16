import csv, json
import requests

GAMMA = "https://gamma-api.polymarket.com"
EDGE_MIN = 0.08
STAKE = 10.0
HIST = "wxhist.csv"
S = requests.Session()
S.headers.update({"User-Agent": "wx-settle/1.0"})


def jget(u, **p):
    r = S.get(u, params=p, timeout=25)
    r.raise_for_status()
    return r.json()


def aslist(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def build_map(want):
    m = {}
    for cl in ("false", "true"):
        off = 0
        seen = set()
        while off < 6000:
            raw = jget(GAMMA + "/markets", limit=500, offset=off, closed=cl,
                       order="volumeNum", ascending="false")
            if not raw:
                break
            new = 0
            for d in raw:
                toks = aslist(d.get("clobTokenIds"))
                if not toks:
                    continue
                t = toks[0]
                if t not in seen:
                    seen.add(t)
                    new += 1
                if t not in m:
                    m[t] = aslist(d.get("outcomePrices"))
            off += len(raw)
            if new == 0:
                break
        if want and want.issubset(set(m.keys())):
            break
    return m


def last_per_token(path):
    last = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            t = row["token"]
            if t not in last or row["ts_utc"] > last[t]["ts_utc"]:
                last[t] = row
    return last


def yes_price(prices):
    if prices:
        try:
            return float(prices[0])
        except Exception:
            return None
    return None


def main():
    last = last_per_token(HIST)
    bets = []
    for t, row in last.items():
        try:
            price = float(row["price"]); model = float(row["model"]); edge = float(row["edge"])
        except Exception:
            continue
        if abs(edge) < EDGE_MIN:
            continue
        side = "YES" if model > price else "NO"
        bets.append((t, row, side, price, model))
    print("Paris de valeur (dernier instantane avant cloture, |edge| >= %.0f pts) : %d"
          % (EDGE_MIN * 100, len(bets)))
    if not bets:
        print("Rien a regler pour l'instant (laisse tourner le collecteur plusieurs jours).")
        return
    M = build_map(set(t for t, *_ in bets))
    w = l = wait = 0
    real = 0.0
    sum_cost = sum_model = 0.0
    for t, row, side, price, model in bets:
        y = yes_price(M.get(t))
        if y is None or not (y >= 0.99 or y <= 0.01):
            wait += 1
            continue
        cost = price if side == "YES" else (1.0 - price)
        pwin_model = model if side == "YES" else (1.0 - model)
        sum_cost += cost
        sum_model += pwin_model
        win = (y if side == "YES" else 1.0 - y) >= 0.5
        if win:
            w += 1
            real += STAKE * (1.0 / cost - 1.0)
        else:
            l += 1
            real += -STAKE
    done = w + l
    print("Regles : %d (gagnes %d, perdus %d) | en attente : %d" % (done, w, l, wait))
    if done:
        wr = 100.0 * w / done
        imp = 100.0 * sum_cost / done
        mod = 100.0 * sum_model / done
        roi = 100.0 * real / (STAKE * done)
        print("Win rate REEL          : %.0f%%" % wr)
        print("Proba implicite marche : %.0f%%  (moyenne du prix paye)" % imp)
        print("Proba moyenne du modele: %.0f%%" % mod)
        print("-> EDGE reel si le win rate (%.0f%%) depasse nettement l'implicite marche (%.0f%%) sur beaucoup de paris." % (wr, imp))
        print("P&L paper (mise %.0f/parie) : %+.1f EUR | ROI %+.1f%%" % (STAKE, real, roi))
    print("\nRappel: edge un jour = bruit ; il faut 30-50 paris regles pour conclure.")


if __name__ == "__main__":
    main()
