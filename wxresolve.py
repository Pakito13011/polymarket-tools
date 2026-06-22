# Enregistreur PERMANENT de resolutions Polymarket meteo.
# Lit wxhist*.csv -> pour chaque token pas encore grave dans resolutions.csv,
# interroge Gamma par token direct -> si fige a 1/0, grave la resolution DEFINITIVEMENT.
# Idempotent : chaque token n'est grave qu'une fois. A lancer en cron (toutes les 12h).
import csv, glob, json, os
from datetime import datetime, timezone
import requests

GAMMA = "https://gamma-api.polymarket.com"
HIST_GLOB = "wxhist*.csv"
OUT = "resolutions.csv"
OUT_HEADER = ["resolved_ts", "token", "city", "end", "bucket", "question", "yes_price", "won"]
S = requests.Session()
S.headers.update({"User-Agent": "wx-resolve/1.0"})


def jget(u, **p):
    try:
        r = S.get(u, params=p, timeout=20)
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


def load_done():
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for row in csv.DictReader(f):
                t = row.get("token")
                if t:
                    done.add(t)
    return done


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


def main():
    done = load_done()
    last = last_per_token()
    todo = [(t, row) for t, row in last.items() if t not in done]
    print("Tokens connus: %d | deja graves: %d | a verifier: %d" % (len(last), len(done), len(todo)))
    new_rows = []
    checked = 0
    for t, row in todo:
        checked += 1
        d = jget(GAMMA + "/markets", clob_token_ids=t)
        if not (isinstance(d, list) and d):
            continue  # archive ou introuvable -> on ne grave pas (re-tentera tant que pas grave)
        pr = aslist(d[0].get("outcomePrices"))
        if not pr:
            continue
        try:
            y = float(pr[0])
        except Exception:
            continue
        if y >= 0.99 or y <= 0.01:   # marche FIGE = resolu
            new_rows.append([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             t, row.get("city", ""), (row.get("end", "") or "")[:10],
                             row.get("bucket", ""), (row.get("question", "") or "")[:90],
                             round(y, 4), 1 if y >= 0.99 else 0])
    is_new_file = not os.path.exists(OUT)
    if new_rows:
        with open(OUT, "a", newline="") as f:
            w = csv.writer(f)
            if is_new_file:
                w.writerow(OUT_HEADER)
            w.writerows(new_rows)
    total = len(done) + len(new_rows)
    print("Verifies: %d | NOUVELLES resolutions gravees: %d | total archive permanent: %d"
          % (checked, len(new_rows), total))
    if new_rows:
        won = sum(r[7] for r in new_rows)
        print("  (dont %d YES gagnants / %d graves ce passage)" % (won, len(new_rows)))


if __name__ == "__main__":
    main()
