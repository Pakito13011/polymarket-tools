import csv, json, glob
from collections import defaultdict
import requests

GAMMA = "https://gamma-api.polymarket.com"
HIST_GLOB = "wxhist*.csv"
OUT = "wxbias.json"
MIN_N = 5   # nb minimal de points par ville pour juger le biais fiable
S = requests.Session()
S.headers.update({"User-Agent": "wx-bias/1.0"})


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


def build_resolution_map(want):
    m = {}
    for cl in ("true", "false"):
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


def bucket_center(label):
    s = label.strip()
    unit = "F" if s.upper().endswith("F") else "C"
    body = s[:-1] if s and s[-1] in "CFcf" else s
    body = body.replace(">=", "").replace("<=", "")

    def toC(x):
        return x if unit == "C" else (x - 32.0) * 5.0 / 9.0
    if "-" in body:
        a, b = body.split("-", 1)
        try:
            return toC((float(a) + float(b) + 1.0) / 2.0)
        except Exception:
            return None
    try:
        return toC(float(body))
    except Exception:
        return None


def last_per_token(rows):
    last = {}
    for row in rows:
        t = row["token"]
        if t not in last or row["ts_utc"] > last[t]["ts_utc"]:
            last[t] = row
    return last


def main():
    rows = []
    for path in glob.glob(HIST_GLOB):
        with open(path) as f:
            for row in csv.DictReader(f):
                rows.append(row)
    if not rows:
        print("Aucun historique (wxhist*.csv) trouve.")
        return
    last = last_per_token(rows)
    M = build_resolution_map(set(last.keys()))
    by_city_date = defaultdict(list)
    for t, row in last.items():
        by_city_date[(row["city"], row["end"])].append((row["bucket"], t, row.get("max_obs", "")))
    diffs = defaultdict(list)
    detail = []
    for (city, date), items in by_city_date.items():
        truth = None
        our_obs = None
        for label, tok, mobs in items:
            prices = M.get(tok)
            if prices:
                try:
                    if float(prices[0]) >= 0.99:
                        truth = bucket_center(label)
                except Exception:
                    pass
            if mobs not in ("", None):
                try:
                    our_obs = float(mobs)
                except Exception:
                    pass
        if truth is not None and our_obs is not None:
            diffs[city].append(truth - our_obs)
            detail.append((city, date, round(truth, 1), round(our_obs, 1), round(truth - our_obs, 1)))
    if not diffs:
        print("Aucun marche resolu exploitable pour l'instant.")
        print("Laisse le collecteur tourner quelques jours puis relance.")
        return
    bias = {}
    print("%-16s %5s %8s %8s" % ("ville", "n", "biais", "ecart-type"))
    for city, ds in sorted(diffs.items()):
        n = len(ds)
        mean = sum(ds) / n
        var = sum((x - mean) ** 2 for x in ds) / n if n > 1 else 0.0
        sd = var ** 0.5
        flag = "" if n >= MIN_N else "  (peu de points)"
        print("%-16s %5d %+7.2f %8.2f%s" % (city, n, mean, sd, flag))
        if n >= MIN_N:
            bias[city] = round(mean, 2)
    with open(OUT, "w") as f:
        json.dump({"bias_c": bias, "min_n": MIN_N}, f, indent=1)
    print("\nBiais (>= %d points) ecrits dans %s : %s" % (MIN_N, OUT, bias if bias else "(aucun encore fiable)"))
    print("Positif = la station resout PLUS CHAUD que notre grille -> il faudra remonter nos membres.")
    print("\nDetail (ville, date, T_station approx, notre_max_obs, ecart) :")
    for d in sorted(detail):
        print("  ", d)


if __name__ == "__main__":
    main()
