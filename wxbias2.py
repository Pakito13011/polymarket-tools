import json, re
from collections import defaultdict
import requests

GAMMA = "https://gamma-api.polymarket.com"
GEO = "https://geocoding-api.open-meteo.com/v1/search"
WX = "https://api.open-meteo.com/v1/forecast"
OUT = "wxbias.json"
MIN_N = 5
S = requests.Session()
S.headers.update({"User-Agent": "wx-bias2/1.0"})

W_METEO = ["temperature", "temperatures", "weather", "hottest", "coldest", "warmest", "degrees"]
EXCL = ["hurricane", "hurricanes", "tornado", "tornadoes", "year on record", "hottest year",
        "hottest on record", "rank", "category"]


def jget(u, **p):
    r = S.get(u, params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def aslist(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


KIND_HI = ["highest", "high temperature", "max temperature", "hottest", "warmest"]
KIND_LO = ["lowest", "low temperature", "min temperature", "coldest"]


def toC(x, u):
    return x if u == "c" else (x - 32.0) * 5.0 / 9.0


def parse_bucket(q):
    ql = q.lower()
    if not any(w in ql for w in W_METEO):
        return None, None, None
    if any(w in ql for w in EXCL):
        return None, None, None
    kind = "high" if any(k in ql for k in KIND_HI) else ("low" if any(k in ql for k in KIND_LO) else None)
    mc = re.search(r"\bin\s+([a-z][a-z .'\-]+?)\s+(?:be|reach|reaches|exceed|hit|will|on\b|to\b)", ql)
    city = mc.group(1).strip() if mc else None
    ge = ("or higher" in ql) or ("or above" in ql)
    le = ("or below" in ql) or ("or lower" in ql)
    mr = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*[^\w]*([cf])\b", ql)
    mv = re.search(r"(\d+(?:\.\d+)?)\s*[^\w]*([cf])\b", ql)
    center = None
    if mr:
        a = float(mr.group(1)); b = float(mr.group(2)); u = mr.group(3)
        center = toC((a + b + 1.0) / 2.0, u)
    elif mv:
        x = float(mv.group(1)); u = mv.group(2)
        if ge:
            center = toC(x + 0.5, u)
        elif le:
            center = toC(x - 0.5, u)
        else:
            center = toC(x, u)
    return kind, city, center


def fetch_weather():
    out = []
    seen = set()
    for cl in ("true", "false"):
        off = 0
        while off < 8000:
            raw = jget(GAMMA + "/markets", limit=500, offset=off, closed=cl,
                       order="volumeNum", ascending="false")
            if not raw:
                break
            new = 0
            for d in raw:
                toks = aslist(d.get("clobTokenIds"))
                tok = toks[0] if toks else None
                if not tok or tok in seen:
                    continue
                seen.add(tok)
                new += 1
                q = d.get("question", "")
                kind, city, center = parse_bucket(q)
                if kind and city and center is not None:
                    out.append({"q": q, "tok": tok, "kind": kind, "city": city, "center": center,
                                "end": (d.get("endDate", "") or "")[:10],
                                "prices": aslist(d.get("outcomePrices"))})
            off += len(raw)
            if new == 0:
                break
    return out


GEO_CACHE = {}
GRID_CACHE = {}


def geocode(city):
    if city in GEO_CACHE:
        return GEO_CACHE[city]
    d = jget(GEO, name=city, count=1, language="en", format="json")
    r = (d.get("results") or [None])[0]
    res = (r.get("latitude"), r.get("longitude")) if r else None
    GEO_CACHE[city] = res
    return res


def grid_series(lat, lon, kind):
    key = (round(lat, 2), round(lon, 2), kind)
    if key in GRID_CACHE:
        return GRID_CACHE[key]
    var = "temperature_2m_max" if kind == "high" else "temperature_2m_min"
    d = jget(WX, latitude=lat, longitude=lon, daily=var, past_days=7, forecast_days=1, timezone="auto")
    daily = d.get("daily", {})
    series = dict(zip(daily.get("time", []), daily.get(var, [])))
    GRID_CACHE[key] = series
    return series


def main():
    mk = fetch_weather()
    print("Marches meteo (tous, ouverts+fermes) parses : %d" % len(mk))
    groups = defaultdict(list)
    for m in mk:
        if not m["end"]:
            continue
        groups[(m["city"], m["end"], m["kind"])].append(m)
    diffs = defaultdict(list)
    detail = []
    resolved_groups = 0
    for (city, date, kind), items in groups.items():
        truth = None
        for m in items:
            pr = m["prices"]
            if pr:
                try:
                    if float(pr[0]) >= 0.99:
                        truth = m["center"]
                except Exception:
                    pass
        if truth is None:
            continue
        resolved_groups += 1
        geo = geocode(city)
        if not geo or geo[0] is None:
            continue
        try:
            series = grid_series(geo[0], geo[1], kind)
        except Exception:
            continue
        g = series.get(date)
        if g is None:
            continue
        diffs[city].append(truth - g)
        detail.append((city, date, kind, round(truth, 1), round(g, 1), round(truth - g, 1)))
    print("Groupes (ville,date,type) resolus exploitables : %d\n" % resolved_groups)
    if not diffs:
        print("Aucun point exploitable pour l'instant. Relance dans quelques jours.")
        return
    bias = {}
    print("%-16s %5s %8s %8s" % ("ville", "n", "biais", "ecart-type"))
    for city, ds in sorted(diffs.items()):
        n = len(ds)
        mean = sum(ds) / n
        sd = (sum((x - mean) ** 2 for x in ds) / n) ** 0.5 if n > 1 else 0.0
        flag = "" if n >= MIN_N else "  (peu de points)"
        print("%-16s %5d %+7.2f %8.2f%s" % (city, n, mean, sd, flag))
        if n >= MIN_N:
            bias[city] = round(mean, 2)
    with open(OUT, "w") as f:
        json.dump({"bias_c": bias, "min_n": MIN_N}, f, indent=1)
    print("\nBiais fiables (>= %d points) -> %s : %s" % (MIN_N, OUT, bias if bias else "(aucun encore)"))
    print("biais = T_station_resolue - max_grille_journee_entiere (corrige de l'artefact de timing).")
    print("Positif = station plus chaude que notre grille -> remonter les membres de cette ville.")
    print("\nDetail (ville, date, type, T_station, max_grille, ecart) :")
    for d in sorted(detail):
        print("  ", d)


if __name__ == "__main__":
    main()
