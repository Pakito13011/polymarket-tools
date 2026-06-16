import time, csv, os
from datetime import datetime, timezone
import pmwxval2 as W

LOOP_MIN = 12
HIST = "wxhist.csv"
HEADER = ["ts_utc", "end", "token", "question", "city", "bucket",
          "price", "model", "edge", "max_obs", "nobs", "nfut"]


def cycle():
    rows = []
    for m in W.fetch_meteo():
        try:
            p = float(W.jget(W.CLOB + "/midpoint", token_id=m["tok"])["mid"])
        except Exception:
            continue
        if not (W.LIVE_LO <= p <= W.LIVE_HI):
            continue
        kind, city, lo, hi, label = W.parse_bucket(m["q"])
        if not (kind and city and lo is not None and m["end"]):
            continue
        geo = W.geocode(city)
        if not geo or geo[0] is None:
            continue
        try:
            samples, nobs, nfut, omax = W.day_samples(geo[0], geo[1], m["end"][:10], kind)
        except Exception:
            continue
        mprob = W.prob_bucket(samples, lo, hi)
        rows.append([datetime.now(timezone.utc).isoformat(timespec="seconds"), m["end"][:10],
                     m["tok"], m["q"][:90], city, label, round(p, 4), round(mprob, 4),
                     round(mprob - p, 4), ("" if omax is None else round(omax, 1)), nobs, nfut])
    new = not os.path.exists(HIST)
    with open(HIST, "a", newline="") as f:
        wr = csv.writer(f)
        if new:
            wr.writerow(HEADER)
        wr.writerows(rows)
    return len(rows)


def main():
    print("Collecteur meteo demarre (cycle %d min, sortie %s)." % (LOOP_MIN, HIST))
    print("Detache tmux avec Ctrl+B puis D ; rattache avec 'tmux attach -t wx'.")
    while True:
        W.HOURLY_CACHE.clear()
        W.SAMPLE_CACHE.clear()
        try:
            n = cycle()
            print("%s UTC | %d marches vivants logges" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), n), flush=True)
        except Exception as e:
            print("cycle erreur: %r" % (e,), flush=True)
        time.sleep(LOOP_MIN * 60)


if __name__ == "__main__":
    main()
