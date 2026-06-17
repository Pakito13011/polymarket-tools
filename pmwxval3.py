import json, math, re, random
from datetime import datetime, timedelta, timezone
import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
GEO = "https://geocoding-api.open-meteo.com/v1/search"
ENS = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENS_MODEL = "gfs025"   # GEFS ~31 membres ; vraie dispersion de prevision
N_FETCH = 3000
LIVE_LO = 0.20         # marches vraiment incertains seulement
LIVE_HI = 0.80
SIGMA_DAY = 1.3        # FALLBACK uniquement (si ensemble indispo)
SIGMA_HOUR = 0.4
N_MC = 2000
EDGE_MIN = 0.08
KELLY_FRAC = 0.5
KELLY_CAP = 0.10
BUDGET = 500.0
STATE = "wxbets.json"

EXCL = [
    "election", "president", "presidential", "senate", "congress", "governor",
    "prime minister", "parliament", "impeach", "nominee", "primary", "cabinet",
    "supreme court", "vote", "voter", "poll", "trump", "biden", "harris", "democrat",
    "republican", "referendum", "coup", "minister", "chancellor", "putin", "zelensky",
    "ukraine", "russia", "russian", "nato", "crimea", "crimean", "war", "troops",
    "military", "regime", "invade", "invasion", "ceasefire", "peace", "israel", "iran",
    "iranian", "gaza", "hamas", "hezbollah", "missile", "nuclear", "sanction", "tariff",
    "bitcoin", "ethereum", "crypto", "solana", "dogecoin", "xrp", "ripple", "stablecoin",
    "binance", "coinbase", "memecoin", "altcoin", "nft", "fed", "gdp", "inflation",
    "recession", "nasdaq", "stock", "stocks", "shares", "earnings", "ipo", "powell",
    "treasury", "unemployment",
    "esports", "esport", "lol", "league of legends", "dota", "counter-strike",
    "counter strike", "cs2", "valorant", "overwatch", "rainbow six", "rocket league",
    "starcraft", "call of duty", "mobile legends", "wild rift", "pubg", "iem",
    "bo3", "bo5", "best of 3", "best of 5", "map handicap", "map 1", "map 2", "map 3",
    "first blood",
]
W_SPORT = [
    "win the", "beat", "beats", "vs", "match", "matches", "cup", "super bowl", "nba",
    "nfl", "nhl", "mlb", "mls", "premier league", "la liga", "serie a", "bundesliga",
    "ligue 1", "champions league", "grand prix", "formula 1", "f1", "ufc", "fight",
    "wimbledon", "us open", "australian open", "roland garros", "masters", "playoff",
    "playoffs", "finals", "goal", "goals", "world cup", "olympic", "olympics", "medal",
    "tournament", "tennis", "golf", "t20", "odi", "test series", "cricket", "rugby",
]
W_METEO = [
    "temperature", "temperatures", "rain", "rains", "rainfall", "snow", "snows",
    "snowfall", "degrees", "fahrenheit", "celsius", "weather", "hurricane", "hurricanes",
    "storm", "storms", "tornado", "tornadoes", "heat wave", "precipitation", "sunny",
    "cloudy", "wind", "warmest", "coldest", "hottest",
]


def _rx(words):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


RX_EXCL = _rx(EXCL)
RX_SPORT = _rx(W_SPORT)
RX_METEO = _rx(W_METEO)


def classify(q):
    if RX_EXCL.search(q):
        return None
    if RX_SPORT.search(q):
        return "SPORT"
    if RX_METEO.search(q):
        return "METEO"
    return None


S = requests.Session()
S.headers.update({"User-Agent": "pm-wxval3/1.0"})


def jget(url, **p):
    r = S.get(url, params=p, timeout=30)
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
    kind = "high" if any(k in ql for k in KIND_HI) else ("low" if any(k in ql for k in KIND_LO) else None)
    mc = re.search(r"\bin\s+([a-z][a-z .'\-]+?)\s+(?:be|reach|reaches|exceed|hit|will|on\b|to\b)", ql)
    city = mc.group(1).strip() if mc else None
    ge = ("or higher" in ql) or ("or above" in ql)
    le = ("or below" in ql) or ("or lower" in ql)
    mr = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*[^\w]*([cf])\b", ql)
    mv = re.search(r"(\d+(?:\.\d+)?)\s*[^\w]*([cf])\b", ql)
    lo = hi = None
    label = None
    if mr:
        a = float(mr.group(1)); b = float(mr.group(2)); u = mr.group(3)
        lo = toC(a, u); hi = toC(b + 1.0, u)
        label = "%g-%g%s" % (a, b, u.upper())
    elif mv:
        x = float(mv.group(1)); u = mv.group(2)
        if ge:
            lo = toC(x - 0.5, u); hi = float("inf"); label = ">=%g%s" % (x, u.upper())
        elif le:
            lo = float("-inf"); hi = toC(x + 0.5, u); label = "<=%g%s" % (x, u.upper())
        else:
            lo = toC(x - 0.5, u); hi = toC(x + 0.5, u); label = "%g%s" % (x, u.upper())
    return kind, city, lo, hi, label


def fetch_meteo():
    out = []
    seen = set()
    offset = 0
    while len(out) < N_FETCH and offset < 6000:
        raw = jget(GAMMA + "/markets", limit=500, offset=offset, active="true", closed="false",
                   order="volumeNum", ascending="false")
        if not raw:
            break
        new = 0
        for m in raw:
            toks = aslist(m.get("clobTokenIds"))
            tok = toks[0] if toks else None
            if not tok or tok in seen:
                continue
            seen.add(tok)
            new += 1
            q = m.get("question", "")
            if classify(q) == "METEO":
                out.append({"q": q, "tok": tok, "end": m.get("endDate", "") or ""})
        offset += len(raw)
        if new == 0:
            break
    return out


GEO_CACHE = {}
HOURLY_CACHE = {}
SAMPLE_CACHE = {}


def geocode(city):
    if city in GEO_CACHE:
        return GEO_CACHE[city]
    d = jget(GEO, name=city, count=1, language="en", format="json")
    r = (d.get("results") or [None])[0]
    res = (r.get("latitude"), r.get("longitude")) if r else None
    GEO_CACHE[city] = res
    return res


def ensemble(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    if key in HOURLY_CACHE:
        return HOURLY_CACHE[key]
    d = jget(ENS, latitude=lat, longitude=lon, hourly="temperature_2m",
             models=ENS_MODEL, forecast_days=4, timezone="auto")
    off = d.get("utc_offset_seconds", 0)
    h = d.get("hourly", {})
    times = h.get("time", [])
    mkeys = [k for k in h if re.match(r"temperature_2m_member\d+$", k)]
    if not mkeys and "temperature_2m" in h:
        mkeys = ["temperature_2m"]
    members = {k: h.get(k, []) for k in mkeys}
    res = (off, times, members)
    HOURLY_CACHE[key] = res
    return res


def _fromiso(t):
    try:
        return datetime.fromisoformat(t)
    except Exception:
        return None


def day_samples(lat, lon, date_str, kind):
    key = (round(lat, 2), round(lon, 2), date_str, kind)
    if key in SAMPLE_CACHE:
        return SAMPLE_CACHE[key]
    off, times, members = ensemble(lat, lon)
    now_local = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=off)
    idx = [i for i, t in enumerate(times) if t.startswith(date_str)]
    nobs = nfut = 0
    past_idx = []
    for i in idx:
        tt = _fromiso(times[i])
        if tt is None:
            continue
        if tt <= now_local:
            nobs += 1
            past_idx.append(i)
        else:
            nfut += 1
    maxima = []
    for arr in members.values():
        vals = [arr[i] for i in idx if i < len(arr) and arr[i] is not None]
        if not vals:
            continue
        maxima.append(max(vals) if kind == "high" else min(vals))
    omax = None
    if past_idx and members:
        per_hour = []
        for i in past_idx:
            xs = [arr[i] for arr in members.values() if i < len(arr) and arr[i] is not None]
            if xs:
                per_hour.append(sum(xs) / len(xs))
        if per_hour:
            omax = max(per_hour) if kind == "high" else min(per_hour)
    if len(maxima) >= 3:
        out = (maxima, nobs, nfut, omax)
        SAMPLE_CACHE[key] = out
        return out
    # FALLBACK : trace moyenne + biais partage (si ensemble indisponible)
    mean_hour = {}
    for i in idx:
        xs = [arr[i] for arr in members.values() if i < len(arr) and arr[i] is not None]
        if xs:
            mean_hour[i] = sum(xs) / len(xs)
    obs_vals = [mean_hour[i] for i in past_idx if i in mean_hour]
    fut = [mean_hour[i] for i in idx if i not in past_idx and i in mean_hour]
    base = (max(obs_vals) if kind == "high" else min(obs_vals)) if obs_vals else None
    res = []
    for _ in range(N_MC):
        bias = random.gauss(0, SIGMA_DAY)
        if kind == "high":
            m = base if base is not None else -1e9
            for f in fut:
                s = f + bias + random.gauss(0, SIGMA_HOUR)
                if s > m:
                    m = s
        else:
            m = base if base is not None else 1e9
            for f in fut:
                s = f + bias + random.gauss(0, SIGMA_HOUR)
                if s < m:
                    m = s
        res.append(m)
    out = (res, nobs, nfut, omax)
    SAMPLE_CACHE[key] = out
    return out


def prob_bucket(samples, lo, hi):
    if not samples:
        return 0.0
    c = sum(1 for s in samples if lo <= s < hi)
    return c / len(samples)


def kelly(m, p):
    if m > p:
        f = (m - p) / (1.0 - p) if p < 1.0 else 0.0
        return "YES", max(0.0, f)
    mn, pn = 1.0 - m, 1.0 - p
    f = (mn - pn) / (1.0 - pn) if pn < 1.0 else 0.0
    return "NO", max(0.0, f)


def main():
    mk = fetch_meteo()
    print("Marches meteo actifs : %d" % len(mk))
    print("Filtre VIVANT %.0f-%.0f%% | modele = ENSEMBLE %s (membres reels) ; fallback sigma si indispo\n"
          % (LIVE_LO * 100, LIVE_HI * 100, ENS_MODEL))
    live = 0
    bets = []
    for m in mk:
        try:
            p = float(jget(CLOB + "/midpoint", token_id=m["tok"])["mid"])
        except Exception:
            continue
        if not (LIVE_LO <= p <= LIVE_HI):
            continue
        kind, city, lo, hi, label = parse_bucket(m["q"])
        if not (kind and city and lo is not None and m["end"]):
            continue
        geo = geocode(city)
        if not geo or geo[0] is None:
            continue
        try:
            samples, nobs, nfut, omax = day_samples(geo[0], geo[1], m["end"][:10], kind)
        except Exception as e:
            print("  (erreur ensemble %s: %r)" % (city, e))
            continue
        live += 1
        nm = len(samples)
        src = "ens(%dm)" % nm if nm < 200 else "fallback-sigma"
        mprob = prob_bucket(samples, lo, hi)
        edge = mprob - p
        info = "%s obs=%dh fut=%dh%s" % (src, nobs, nfut, ("" if omax is None else " max_obs=%.1fC" % omax))
        print("=" * 70)
        print("Q : %s" % m["q"][:80])
        print("  tranche=%s | prix=%.1f%% | modele=%.1f%% | edge=%+.1f pts | %s"
              % (label, p * 100, mprob * 100, edge * 100, info))
        if abs(edge) >= EDGE_MIN:
            side, f = kelly(mprob, p)
            f_used = min(KELLY_FRAC * f, KELLY_CAP)
            stake = round(BUDGET * f_used, 2)
            print("  -> VALEUR: %s | f=%.1f%% | mise %.1f EUR" % (side, f_used * 100, stake))
            bets.append({"q": m["q"], "tok": m["tok"], "side": side, "entry": round(p, 4),
                         "p_model": round(mprob, 4), "edge": round(edge, 4), "stake": stake,
                         "end": m["end"][:10]})
        else:
            print("  -> pas d'ecart significatif")
    print("\n%d marches VIVANTS (20-80%%) analyses | %d paris de valeur (edge >= %.0f pts)."
          % (live, len(bets), EDGE_MIN * 100))
    if bets:
        with open(STATE, "w") as f:
            json.dump({"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bets": bets}, f, indent=1)
        print("Snapshot ecrit dans %s (la mesure continue passe par wxhist via wxcollect)." % STATE)
    print("\nNote: l'ensemble donne la VRAIE dispersion de prevision (calibration honnete).")
    print("L'edge eventuel viendra ensuite du debiaisage par station + METAR, pas de la prevision brute.")


if __name__ == "__main__":
    main()
