import json, math, re
import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
GEO = "https://geocoding-api.open-meteo.com/v1/search"
WX = "https://api.open-meteo.com/v1/forecast"
N_FETCH = 3000
SIGMA = 1.5        # ecart-type suppose de l'erreur de prevision du max (deg C)
KELLY_FRAC = 0.5   # demi-Kelly
EDGE_MIN = 0.05    # n'agir que si |edge| >= 5 points de proba
BUDGET = 500.0

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
S.headers.update({"User-Agent": "pm-wxval/2.0"})


def jget(url, **p):
    r = S.get(url, params=p, timeout=25)
    r.raise_for_status()
    return r.json()


def aslist(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


KIND_HI = ["highest", "high temperature", "max temperature", "hottest", "warmest"]
KIND_LO = ["lowest", "low temperature", "min temperature", "coldest"]


def parse_market(q):
    ql = q.lower()
    kind = "high" if any(k in ql for k in KIND_HI) else ("low" if any(k in ql for k in KIND_LO) else None)
    mc = re.search(r"\bin\s+([a-z][a-z .'\-]+?)\s+(?:be|reach|reaches|exceed|hit|will|on\b|to\b)", ql)
    city = mc.group(1).strip() if mc else None
    mv = re.search(r"\b(?:be|reach|reaches|exceed|hit|of)\s+(\d+(?:\.\d+)?)", ql)
    if not mv:
        mv = re.search(r"\b(\d+(?:\.\d+)?)\s*[^\w]*[cf]\b", ql)
    val = float(mv.group(1)) if mv else None
    mu = re.search(r"\d+\s*[^\w]*([cf])\b", ql)
    unit = mu.group(1).upper() if mu else "C"
    return kind, city, val, unit


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
                out.append({"q": q, "tok": tok, "desc": m.get("description", "") or "",
                            "end": m.get("endDate", "") or ""})
        offset += len(raw)
        if new == 0:
            break
    return out


def geocode(city):
    d = jget(GEO, name=city, count=1, language="en", format="json")
    r = (d.get("results") or [None])[0]
    if not r:
        return None
    return r.get("latitude"), r.get("longitude")


def forecast_temp(lat, lon, date_str, kind):
    var = "temperature_2m_max" if kind == "high" else "temperature_2m_min"
    d = jget(WX, latitude=lat, longitude=lon, daily=var, forecast_days=4, timezone="auto")
    daily = d.get("daily", {})
    times = daily.get("time", [])
    vals = daily.get(var, [])
    for t, v in zip(times, vals):
        if t == date_str:
            return v
    return vals[0] if vals else None


def model_prob_bucket(tf, x, sigma):
    return phi((x + 0.5 - tf) / sigma) - phi((x - 0.5 - tf) / sigma)


def kelly(m, p):
    if m > p:
        f = (m - p) / (1.0 - p) if p < 1.0 else 0.0
        return "YES", max(0.0, f)
    mn, pn = 1.0 - m, 1.0 - p
    f = (mn - pn) / (1.0 - pn) if pn < 1.0 else 0.0
    return "NO", max(0.0, f)


def main():
    mk = fetch_meteo()
    print("Marches meteo actifs : %d\n" % len(mk))
    value_found = 0
    for m in mk:
        kind, city, val, unit = parse_market(m["q"])
        p = None
        try:
            p = float(jget(CLOB + "/midpoint", token_id=m["tok"])["mid"])
        except Exception:
            pass
        print("=" * 70)
        print("Q : %s" % m["q"][:84])
        print("  parse: kind=%s ville=%s seuil=%s%s | prix(YES)=%s | fin=%s"
              % (kind, city, ("%g" % val) if val is not None else "?", unit,
                 ("%.3f" % p) if p is not None else "?", m["end"][:10] if m["end"] else "?"))
        if m["desc"]:
            print("  resolution: %s" % " ".join(m["desc"][:240].split()))
        if not (kind and city and val is not None and p is not None and m["end"]):
            print("  -> parse/prix incomplet, marche ignore pour le calcul")
            continue
        try:
            geo = geocode(city)
            if not geo or geo[0] is None:
                print("  -> geocodage echoue pour '%s'" % city)
                continue
            tf = forecast_temp(geo[0], geo[1], m["end"][:10], kind)
            if tf is None:
                print("  -> pas de prevision pour %s" % m["end"][:10])
                continue
            x = val if unit == "C" else (val - 32.0) * 5.0 / 9.0
            mprob = model_prob_bucket(tf, x, SIGMA)
            edge = mprob - p
            print("  modele: prev_%s=%.1fC | P(bucket %g+-0.5)=%.1f%% | prix=%.1f%% | edge=%+.1f pts"
                  % ("max" if kind == "high" else "min", tf, x, mprob * 100, p * 100, edge * 100))
            if abs(edge) >= EDGE_MIN:
                side, f = kelly(mprob, p)
                stake = BUDGET * KELLY_FRAC * f
                value_found += 1
                print("  -> VALEUR: parier %s | demi-Kelly f=%.1f%% | mise indicative %.1f EUR" % (side, f * 100, stake))
            else:
                print("  -> pas d'ecart significatif (marche efficient sur ce seuil)")
        except Exception as e:
            print("  -> erreur modele: %r" % (e,))
    print("\n%d marche(s) avec ecart exploitable (>= %.0f pts)." % (value_found, EDGE_MIN * 100))
    print("Hypothese de proba : 'seuil = max arrondi +-0.5C', erreur ~N(0,%.1fC)." % SIGMA)
    print("Verifie le texte 'resolution' ci-dessus : si la regle differe, on corrige le mappage.")


if __name__ == "__main__":
    main()
