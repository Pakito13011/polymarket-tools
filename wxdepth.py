import json
import requests
import pmwxval3 as W   # reutilise classify/fetch_meteo/parse_bucket/jget/CLOB

CLOB = "https://clob.polymarket.com"
LIVE_LO = 0.10
LIVE_HI = 0.90
SLIP = [0.01, 0.03, 0.05]   # paliers de slippage vs midpoint
S = requests.Session()
S.headers.update({"User-Agent": "wx-depth/1.0"})


def jget(u, **p):
    r = S.get(u, params=p, timeout=25)
    r.raise_for_status()
    return r.json()


def book(token):
    return jget(CLOB + "/book", token_id=token)


def depth_side(levels, mid, side):
    rows = []
    for lv in levels:
        try:
            px = float(lv["price"]); sz = float(lv["size"])
        except Exception:
            continue
        rows.append((px, sz))
    if side == "buy_yes":
        rows.sort(key=lambda x: x[0])
        unit = lambda px: px
        ref = mid
    else:
        rows.sort(key=lambda x: -x[0])
        unit = lambda px: 1.0 - px
        ref = 1.0 - mid
    caps = {s: 0.0 for s in SLIP}
    cum_cost = 0.0
    cum_shares = 0.0
    for px, sz in rows:
        c = unit(px)
        if c <= 0 or c >= 1:
            continue
        cum_cost += c * sz
        cum_shares += sz
        avg = cum_cost / cum_shares if cum_shares else c
        for s in SLIP:
            if avg <= ref * (1.0 + s):
                caps[s] = cum_cost
    return caps


def main():
    mk = W.fetch_meteo()
    print("Profondeur des carnets (marches meteo vivants %.0f-%.0f%%)\n" % (LIVE_LO * 100, LIVE_HI * 100))
    print("Pour chaque cote : $ engageables avant +1%% / +3%% / +5%% de slippage vs midpoint.\n")
    n = 0
    agg = {("buy_yes", s): [] for s in SLIP}
    agg.update({("buy_no", s): [] for s in SLIP})
    for m in mk:
        try:
            mid = float(jget(CLOB + "/midpoint", token_id=m["tok"])["mid"])
        except Exception:
            continue
        if not (LIVE_LO <= mid <= LIVE_HI):
            continue
        try:
            b = book(m["tok"])
        except Exception:
            continue
        asks = b.get("asks", []) or []
        bids = b.get("bids", []) or []
        cy = depth_side(asks, mid, "buy_yes")
        cn = depth_side(bids, mid, "buy_no")
        n += 1
        for s in SLIP:
            agg[("buy_yes", s)].append(cy[s])
            agg[("buy_no", s)].append(cn[s])
        print("=" * 64)
        print("Q : %s" % m["q"][:62])
        print("  mid=%.2f | YES $: +1%%=%.0f +3%%=%.0f +5%%=%.0f | NO $: +1%%=%.0f +3%%=%.0f +5%%=%.0f"
              % (mid, cy[0.01], cy[0.03], cy[0.05], cn[0.01], cn[0.03], cn[0.05]))
    print("\n%d marches vivants avec carnet." % n)
    if n:
        def med(xs):
            xs = sorted(xs)
            return xs[len(xs) // 2] if xs else 0.0
        print("\nCapacite MEDIANE par marche (le chiffre qui compte pour dimensionner) :")
        for s in SLIP:
            ys = med(agg[("buy_yes", s)]); ns = med(agg[("buy_no", s)])
            print("  slippage < %.0f%% : YES ~%.0f $ | NO ~%.0f $ par marche" % (s * 100, ys, ns))
        tot1 = sum(agg[("buy_yes", 0.03)])
        print("\nCapacite totale a <3%% slippage (somme cote YES, tous marches) : ~%.0f $" % tot1)
        print("=> c'est l'ordre de grandeur deployable en un passage sans trop bouger les prix.")
    print("\nNote: profondeur = instantanee (a cette heure). Elle varie ; relancer a differents moments.")


if __name__ == "__main__":
    main()
