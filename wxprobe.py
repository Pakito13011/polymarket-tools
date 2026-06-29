# Sonde de reconnaissance : les donnees portent-elles l'info temporelle pour un test de timing ?
# Verifie, pour chaque token : combien de snapshots, est-ce que le prix bouge, est-ce que 'end' est rempli.
import csv, glob, statistics
from collections import defaultdict
from datetime import datetime

snaps = defaultdict(list)
for path in glob.glob("wxhist*.csv"):
    try:
        with open(path) as f:
            for row in csv.DictReader(f):
                t = row.get("token")
                if not t:
                    continue
                snaps[t].append((row.get("ts_utc", ""), row.get("end", ""),
                                 row.get("price", ""), row.get("model", "")))
    except Exception:
        pass

if not snaps:
    print("Aucun snapshot trouve.")
    raise SystemExit

counts = [len(v) for v in snaps.values()]
print("=== STRUCTURE TEMPORELLE DES DONNEES ===")
print("tokens distincts        : %d" % len(snaps))
print("snapshots par token     : min=%d  median=%d  max=%d"
      % (min(counts), int(statistics.median(counts)), max(counts)))
multi = sum(1 for c in counts if c >= 3)
print("tokens avec >=3 snapshots : %d (%.0f%%)" % (multi, 100.0 * multi / len(snaps)))

moves = []
end_ok = 0
for t, lst in snaps.items():
    if lst[0][1]:
        end_ok += 1
    prices = []
    for ts, end, pr, mo in lst:
        try:
            prices.append(float(pr))
        except Exception:
            pass
    if len(prices) >= 2:
        moves.append(max(prices) - min(prices))
print("tokens avec champ 'end' rempli : %d (%.0f%%)" % (end_ok, 100.0 * end_ok / len(snaps)))
if moves:
    print("amplitude prix intra-token : median=%.3f  moy=%.3f  (0=prix fige, >0.1=bouge bien)"
          % (statistics.median(moves), sum(moves) / len(moves)))

rich = sorted(snaps.items(), key=lambda kv: -len(kv[1]))[0]
t, lst = rich
lst = sorted(lst)
print("\n=== EXEMPLE : token %s (%d snapshots, end=%s) ===" % (t[:10], len(lst), lst[0][1][:16]))
end_dt = None
try:
    end_dt = datetime.fromisoformat(lst[0][1].replace("Z", "+00:00"))
except Exception:
    pass
step = max(1, len(lst) // 10)
for ts, end, pr, mo in lst[::step]:
    h_before = ""
    if end_dt:
        try:
            cur = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            h_before = "%.1fh avant cloture" % ((end_dt - cur).total_seconds() / 3600.0)
        except Exception:
            pass
    print("  price=%-5s model=%-5s  %s" % (pr, mo, h_before))

print("\n=== VERDICT ===")
if int(statistics.median(counts)) >= 4 and moves and statistics.median(moves) > 0.03 and end_ok > 0.5 * len(snaps):
    print("DONNEES OK pour un test de timing : assez de snapshots, prix qui bougent, 'end' rempli.")
    print("=> on peut coder wxtiming.py (entree a 6/12/24/36/48h avant cloture).")
else:
    print("DONNEES LIMITEES pour le timing :")
    if int(statistics.median(counts)) < 4:
        print(" - pas assez de snapshots par token (mediane < 4).")
    if not moves or statistics.median(moves) <= 0.03:
        print(" - le prix bouge peu entre snapshots (peu de 'bon moment' a chercher).")
    if end_ok <= 0.5 * len(snaps):
        print(" - champ 'end' souvent vide (impossible de calculer la distance a la cloture).")
