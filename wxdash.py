# Genere un dashboard.html autonome (zero serveur) a partir des donnees locales.
# Lance par cron (ou a la main). On recupere ensuite dashboard.html quand on veut.
import csv, glob, os, html, json
from collections import defaultdict
from datetime import datetime, timezone

RES = "resolutions.csv"
HIST_GLOB = "wxhist*.csv"
BEAT = "wxheartbeat.txt"
OUT = "dashboard.html"
EDGE_MIN = 0.08
STAKE = 10.0
SLIP = 0.04


def last_per_token():
    last = {}
    total_lines = 0
    for path in glob.glob(HIST_GLOB):
        try:
            with open(path) as f:
                for row in csv.DictReader(f):
                    total_lines += 1
                    t = row.get("token")
                    if not t:
                        continue
                    if t not in last or row.get("ts_utc", "") > last[t].get("ts_utc", ""):
                        last[t] = row
        except Exception:
            pass
    return last, total_lines


def pnl_one(cost, won_bet, slip):
    eff = min(cost * (1.0 + slip), 0.999)
    return STAKE * (1.0 / eff - 1.0) if won_bet else -STAKE


def main():
    res = {}
    res_rows = []
    if os.path.exists(RES):
        with open(RES) as f:
            for row in csv.DictReader(f):
                t = row.get("token")
                if not t:
                    continue
                try:
                    res[t] = int(row.get("won", "0"))
                    res_rows.append(row)
                except Exception:
                    pass
    hist, hist_lines = last_per_token()

    bets = []
    for row in res_rows:
        t = row.get("token")
        h = hist.get(t)
        if not h:
            continue
        try:
            price = float(h.get("price")); model = float(h.get("model"))
        except Exception:
            continue
        if abs(model - price) < EDGE_MIN:
            continue
        side = "YES" if model > price else "NO"
        won = res[t]
        won_bet = (won == 1) if side == "YES" else (won == 0)
        cost = price if side == "YES" else (1.0 - price)
        if cost <= 0 or cost >= 1:
            continue
        bets.append((row.get("resolved_ts", ""), (h.get("city") or "?").strip(), cost, won_bet))

    n = len(bets)
    wins = sum(1 for b in bets if b[3])
    pnl_brut = sum(pnl_one(c, w, 0.0) for _, _, c, w in bets)
    pnl_net = sum(pnl_one(c, w, SLIP) for _, _, c, w in bets)
    wr = 100.0 * wins / n if n else 0.0
    roi_brut = 100.0 * pnl_brut / (STAKE * n) if n else 0.0
    roi_net = 100.0 * pnl_net / (STAKE * n) if n else 0.0

    sb = sorted(bets, key=lambda b: b[0])
    curve = []
    cum = 0.0
    for ts, city, cost, won in sb:
        cum += pnl_one(cost, won, SLIP)
        curve.append((ts[:10], round(cum, 1)))

    by_city = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for ts, city, cost, won in bets:
        d = by_city[city]
        d["n"] += 1
        d["w"] += 1 if won else 0
        d["pnl"] += pnl_one(cost, won, SLIP)
    city_rows = sorted(([c, d["n"], d["w"], round(d["pnl"], 1),
                         round(100.0 * d["pnl"] / (STAKE * d["n"]), 1)] for c, d in by_city.items()),
                       key=lambda x: -x[3])

    beat = "inconnu"
    beat_fresh = False
    if os.path.exists(BEAT):
        try:
            beat = open(BEAT).read().strip()
            mtime = datetime.fromtimestamp(os.path.getmtime(BEAT), tz=timezone.utc)
            beat_fresh = (datetime.now(timezone.utc) - mtime).total_seconds() < 1800
        except Exception:
            pass

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def esc(x):
        return html.escape(str(x))

    rows_html = ""
    for c, nn, w, p, r in city_rows:
        color = "#1a7f37" if p > 0 else ("#cf222e" if p < 0 else "#57606a")
        rows_html += "<tr><td>%s</td><td>%d</td><td>%d</td><td style='color:%s;font-weight:600'>%+.1f</td><td style='color:%s'>%+.1f%%</td></tr>" % (
            esc(c), nn, w, color, p, color, r)

    curve_json = json.dumps(curve)
    beat_color = "#1a7f37" if beat_fresh else "#cf222e"
    beat_label = "ACTIF" if beat_fresh else "INACTIF (verifier le collecteur !)"
    roi_net_color = "#1a7f37" if roi_net > 0 else "#cf222e"

    page = """<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Meteo Polymarket</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px} .sub{color:#8b949e;font-size:13px;margin-bottom:24px}
.cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px 20px;flex:1;min-width:150px}
.card .lbl{color:#8b949e;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.card .val{font-size:26px;font-weight:700;margin-top:6px}
.beat{display:inline-block;padding:6px 12px;border-radius:6px;font-weight:600;font-size:13px;margin-bottom:20px}
table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden}
th,td{padding:9px 14px;text-align:left;border-bottom:1px solid #21262d;font-size:14px}
th{background:#1c2128;color:#8b949e;font-size:12px;text-transform:uppercase}
tr:last-child td{border-bottom:none}
.section{font-size:15px;font-weight:600;margin:28px 0 10px}
svg{background:#161b22;border:1px solid #30363d;border-radius:10px}
.foot{color:#6e7681;font-size:12px;margin-top:24px;line-height:1.5}
</style></head><body><div class="wrap">
<h1>Dashboard Meteo Polymarket (paper-trading)</h1>
<div class="sub">Genere le __NOW__ &middot; donnees locales VPS &middot; mise __STAKE__ EUR/pari &middot; slippage __SLIP__%</div>
<div class="beat" style="background:__BEATC__22;color:__BEATC__;border:1px solid __BEATC__">Collecteur : __BEATLBL__</div>
<div style="color:#8b949e;font-size:12px;margin:-12px 0 18px">__BEAT__</div>
<div class="cards">
<div class="card"><div class="lbl">Paris regles</div><div class="val">__N__</div></div>
<div class="card"><div class="lbl">Win rate</div><div class="val">__WR__%</div></div>
<div class="card"><div class="lbl">ROI brut</div><div class="val">__ROIB__%</div></div>
<div class="card"><div class="lbl">ROI net (slippage)</div><div class="val" style="color:__ROINC__">__ROIN__%</div></div>
<div class="card"><div class="lbl">P&amp;L net</div><div class="val" style="color:__ROINC__">__PNLN__ EUR</div></div>
</div>
<div class="section">Evolution du P&amp;L cumule (net)</div>
<div id="chart"></div>
<div class="section">Performance par ville (P&amp;L net, trie)</div>
<table><tr><th>Ville</th><th>Paris</th><th>Gagnes</th><th>P&amp;L EUR</th><th>ROI</th></tr>__ROWS__</table>
<div class="foot">Collecte : __HLINES__ observations loggees &middot; __NRES__ resolutions gravees au total.<br>
NB: paper-trading, donnees non monetisees (Polymarket geobloque en France). Slippage forfaitaire = approximation optimiste sur carnets fins.</div>
</div>
<script>
var data = __CURVE__;
(function(){
 var w=960,h=260,pad=40;
 if(!data.length){document.getElementById('chart').innerHTML='<div style=\"padding:30px;color:#8b949e\">Pas encore de donnees.</div>';return;}
 var vals=data.map(function(d){return d[1]});
 var min=Math.min.apply(null,vals.concat([0])),max=Math.max.apply(null,vals.concat([0]));
 var rng=(max-min)||1;
 function x(i){return pad+(w-2*pad)*(data.length<2?0.5:i/(data.length-1))}
 function y(v){return h-pad-(h-2*pad)*(v-min)/rng}
 var pts=data.map(function(d,i){return x(i)+','+y(d[1])}).join(' ');
 var zeroY=y(0);
 var svg='<svg width=\"100%\" viewBox=\"0 0 '+w+' '+h+'\">';
 svg+='<line x1=\"'+pad+'\" y1=\"'+zeroY+'\" x2=\"'+(w-pad)+'\" y2=\"'+zeroY+'\" stroke=\"#444c56\" stroke-dasharray=\"4\"/>';
 svg+='<polyline points=\"'+pts+'\" fill=\"none\" stroke=\"#2f81f7\" stroke-width=\"2\"/>';
 var last=data[data.length-1][1];
 svg+='<circle cx=\"'+x(data.length-1)+'\" cy=\"'+y(last)+'\" r=\"4\" fill=\"#2f81f7\"/>';
 svg+='<text x=\"'+pad+'\" y=\"'+(pad-14)+'\" fill=\"#8b949e\" font-size=\"12\">P&L net cumule : '+last+' EUR</text>';
 svg+='<text x=\"'+pad+'\" y=\"'+(h-12)+'\" fill=\"#6e7681\" font-size=\"11\">'+data[0][0]+'</text>';
 svg+='<text x=\"'+(w-pad-60)+'\" y=\"'+(h-12)+'\" fill=\"#6e7681\" font-size=\"11\">'+data[data.length-1][0]+'</text>';
 svg+='</svg>';
 document.getElementById('chart').innerHTML=svg;
})();
</script></body></html>"""

    page = (page.replace("__NOW__", esc(now)).replace("__STAKE__", "%.0f" % STAKE)
            .replace("__SLIP__", "%.0f" % (SLIP * 100))
            .replace("__BEATC__", beat_color).replace("__BEATLBL__", beat_label)
            .replace("__BEAT__", esc(beat))
            .replace("__N__", str(n)).replace("__WR__", "%.1f" % wr)
            .replace("__ROIB__", "%+.1f" % roi_brut).replace("__ROIN__", "%+.1f" % roi_net)
            .replace("__ROINC__", roi_net_color).replace("__PNLN__", "%+.1f" % pnl_net)
            .replace("__ROWS__", rows_html if rows_html else "<tr><td colspan=5 style='color:#8b949e'>Pas encore de paris regles.</td></tr>")
            .replace("__HLINES__", str(hist_lines)).replace("__NRES__", str(len(res)))
            .replace("__CURVE__", curve_json))

    with open(OUT, "w") as f:
        f.write(page)
    print("dashboard.html genere : %d paris, win rate %.1f%%, ROI net %+.1f%%" % (n, wr, roi_net))


if __name__ == "__main__":
    main()
