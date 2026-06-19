import time, csv, os, json
from datetime import datetime, timedelta, timezone
import requests
import pmwxval3 as W

LOOP_MIN = 12
HIST = "wxhist.csv"
BEAT = "wxheartbeat.txt"
GAMMA = "https://gamma-api.polymarket.com"
DAYS_AHEAD = 3   # marche du jour + 2 jours suivants (le filtre 20-80% ecarte le reste)
HEADER = ["ts_utc", "end", "token", "question", "city", "bucket",
          "price", "model", "edge", "max_obs", "nobs", "nfut"]

MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]

BASE_CITIES = ["hong-kong", "london", "paris", "tokyo", "beijing", "shanghai", "chongqing",
               "chengdu", "guangzhou", "wuhan", "qingdao", "busan", "seoul", "singapore",
               "kuala-lumpur", "manila", "taipei", "tel-aviv", "jeddah", "karachi",
               "wellington", "madrid", "munich", "new-york", "los-angeles", "miami",
               "chicago", "moscow", "dubai", "sydney", "delhi", "mumbai", "bangkok"]


def cities():
    found = set(BASE_CITIES)
    try:
        with open(HIST) as f:
            for row in csv.DictReader(f):
                c = (row.get("city") or "").strip().lower().replace(" ", "-")
                if c:
                    found.add(c)
    except FileNotFoundError:
        pass
    return sorted(found)


def date_variants(d):
    m = MONTHS[d.month - 1]
    return list(dict.fromkeys(["%s-%d-%d" % (m, d.day, d.year),
                               "%s-%02d-%d" % (m, d.day, d.year)]))


def event_markets(slug):
    try:
        r = W.S.get(GAMMA + "/events", params={"slug": slug}, timeout=20)
        r.raise_for_status()
        d = r.json()
    except Exception:
        return []
    if isinstance(d, list) and d:
        return d[0].get("markets", []) or []
    return []


def cycle():
    rows = []
    now = datetime.now(timezone.utc)
    seen_tok = set()
    events_ok = 0
    for c in cities():
        for off in range(DAYS_AHEAD):
            day = now + timedelta(days=off)
            mk = []
            for slug in ("highest-temperature-in-%s-on-%s" % (c, dv) for dv in date_variants(day)):
                mk = event_markets(slug)
                if mk:
                    events_ok += 1
                    break
            for m in mk:
                toks = W.aslist(m.get("clobTokenIds"))
                tok = toks[0] if toks else None
                if not tok or tok in seen_tok:
                    continue
                seen_tok.add(tok)
                q = m.get("question", "")
                try:
                    p = float(W.jget(W.CLOB + "/midpoint", token_id=tok)["mid"])
                except Exception:
                    continue
                if not (W.LIVE_LO <= p <= W.LIVE_HI):
                    continue
                kind, city, lo, hi, label = W.parse_bucket(q)
                end = (m.get("endDate", "") or "")[:10]
                if not (kind and city and lo is not None and end):
                    continue
                geo = W.geocode(city)
                if not geo or geo[0] is None:
                    continue
                try:
                    samples, nobs, nfut, omax = W.day_samples(geo[0], geo[1], end, kind)
                except Exception:
                    continue
                mprob = W.prob_bucket(samples, lo, hi)
                rows.append([now.isoformat(timespec="seconds"), end, tok, q[:90], city, label,
                             round(p, 4), round(mprob, 4), round(mprob - p, 4),
                             ("" if omax is None else round(omax, 1)), nobs, nfut])
    new = not os.path.exists(HIST)
    with open(HIST, "a", newline="") as f:
        wr = csv.writer(f)
        if new:
            wr.writerow(HEADER)
        wr.writerows(rows)
    return events_ok, len(rows)


def main():
    print("Collecteur meteo v2 (decouverte par event, cycle %d min, sortie %s)." % (LOOP_MIN, HIST))
    print("Heartbeat dans %s a chaque cycle." % BEAT)
    while True:
        W.HOURLY_CACHE.clear()
        W.SAMPLE_CACHE.clear()
        t0 = datetime.now(timezone.utc)
        try:
            ev, n = cycle()
            msg = "%s UTC | events OK: %d | marches logges: %d" % (t0.strftime("%H:%M:%S"), ev, n)
        except Exception as e:
            msg = "%s UTC | CYCLE ERREUR: %r" % (t0.strftime("%H:%M:%S"), e)
        print(msg, flush=True)
        try:
            with open(BEAT, "w") as f:
                f.write(msg + "\n")
        except Exception:
            pass
        time.sleep(LOOP_MIN * 60)


if __name__ == "__main__":
    main()
