# Biais grille<->station par ville, a partir de NOS observations loggees (wxhist*.csv)
# + resolution par TOKEN DIRECT (pas de pagination) + verite grille jour entier via Open-Meteo.
import csv, glob, json, re
from collections import defaultdict
import requests

GAMMA = "https://gamma-api.polymarket.com"
WX = "https://api.open-meteo.com/v1/forecast"
HIST_GLOB = "wxhist*.csv"
OUT = "wxbias.json"
MIN_N = 5
S = requests.Session()
S.headers.update({"User-Agent": "wx-bias3/1.0"})


def jget(u, **p):
    try:
        r = S.get(u, params=p, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def aslist(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def resolve_token(tok):
    d = jget(GAMMA + "/markets", clob_token_ids=tok)
    if isinstance(d, list) and d:
        pr = aslist(d[0].get("outcomePrices"))
        if pr:
            try:
                return float(pr[0])
            except Exception:
                return None
    return None


def bucket_center_c(label):
    s = (label or "").strip()
    if not s:
        return None
    unit = "F" if s.upper().endswith("F") else "C"
    body = s[:-1] if s[-1] in "CFcf" else s
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


def kind_of(label, question):
    q = (question or "").lower()
    if any(k in q for k in ("lowest", "low temperature", "min temperature", "coldest")):
        return "low"
    return "high"


GEO_CACHE = {}
GRID_CACHE = {}


def geocode(city):
    if city in GEO_CACHE:
        return GEO_CACHE[city]
    d = jget("https://geocoding-api.open-meteo.com/v1/search", name=city, count=1, language="en", format="json")
    res = None
    if d:
        r = (d.get("results") or [None])[0]
        if r:
            res = (r.get("latitude"), r.get("longitude"))
    GEO_CACHE[city] = res
    return res


def grid_series(lat, lon, kind):
    key = (round(lat, 2), round(lon, 2), kind)
    if key in GRID_CACHE:
        return GRID_CACHE[key]
    var = "temperature_2m_max" if kind == "high" else "temperature_2m_min"
    d = jget(WX, latitude=lat, longitude=lon, daily=var, past_days=14, forecast_days=1, timezone="auto")
    series = {}
    if d:
        daily = d.get("daily", {})
        series = dict(zip(daily.get("time", []), daily.get(var, [])))
    GRID_CACHE[key] = series
    return series


def main():
    rows = []
    files = glob.glob(HIST_GLOB)
    for path in files:
        try:
            with open(path) as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        except Exception:
            pass
    print("Fichiers historiques lus : %s (%d lignes)" % (", ".join(sorted(files)), len(rows)))
    last = {}
    for row in rows:
        t = row.get("token")
        if t and (t not in last or row.get("ts_utc", "") > last[t].get("ts_utc", "")):
            last[t] = row
    groups = defaultdict(list)
    for t, row in last.items():
        city = (row.get("city") or "").strip()
        date = (row.get("end") or "")[:10]
        if not city or not date:
            continue
        k = kind_of(row.get("bucket"), row.get("question"))
        groups[(city, date, k)].append((t, row))
    diffs = defaultdict(list)
    detail = []
    n_groups = len(groups)
    n_resolved = 0
    for (city, date, kind), items in groups.items():
        truth = None
        for t, row in items:
            y = resolve_token(t)
            if y is not None and y >= 0.99:
                truth = bucket_center_c(row.get("bucket"))
                break
        if truth is None:
            continue
        n_resolved += 1
        geo = geocode(city)
        if not geo or geo[0] is None:
            continue
        series = grid_series(geo[0], geo[1], kind)
        g = series.get(date)
        if g is None:
            continue
        diffs[city].append(truth - g)
        detail.append((city, date, kind, round(truth, 1), round(g, 1), round(truth - g, 1)))
    print("Groupes (ville,date,type) : %d | resolus exploitables : %d\n" % (n_groups, n_resolved))
    if not diffs:
        print("Aucun point exploitable (marches peut-etre deja archives). ")
        print("Les marches archives ne repondent plus par token : seules les resolutions RECENTES sont lisibles.")
        return
    bias = {}
    print("%-16s %5s %8s %9s" % ("ville", "n", "biais", "ecart-type"))
    for city, ds in sorted(diffs.items()):
        n = len(ds)
        mean = sum(ds) / n
        sd = (sum((x - mean) ** 2 for x in ds) / n) ** 0.5 if n > 1 else 0.0
        flag = "" if n >= MIN_N else "  (peu de points)"
        print("%-16s %5d %+7.2f %9.2f%s" % (city, n, mean, sd, flag))
        if n >= MIN_N:
            bias[city] = round(mean, 2)
    with open(OUT, "w") as f:
        json.dump({"bias_c": bias, "min_n": MIN_N}, f, indent=1)
    print("\nBiais fiables (>= %d points) -> %s : %s" % (MIN_N, OUT, bias if bias else "(aucun encore)"))
    print("biais = T_station_resolue - max_grille_jour_entier. Positif = station plus chaude que la grille.")
    print("\nDetail (ville, date, type, T_station, max_grille, ecart) :")
    for d in sorted(detail):
        print("  ", d)


if __name__ == "__main__":
    main()
