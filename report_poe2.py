"""Writes out/report_poe2.html: tier values in exalts, divine rates, every priced item and its fate."""
import html
import json
from datetime import datetime

import build_filter_poe2 as bf
import filtersim as fs

# Item class per poe.ninja feed, only so the simulator can replay NeverSink rules. Our price
# blocks match BaseType alone, so a wrong guess only matters for NeverSink-tiered (thin) items.
FEED_CLASS = {"Runes": "Augment", "SoulCores": "Augment", "Idols": "Augment", "Ritual": "Omen",
              "UncutGems": "Uncut Skill Gems", "LineageSupportGems": "Support Gems"}


def collect(cfg, blocks, r):
    tiers, deferred = r["tiers"], set(r["deferred"])
    rows = []
    for name, (div, feed, volume) in r["prices"].items():
        base, level = bf.item_key(name, feed)
        item = {"class": FEED_CLASS.get(feed, "Stackable Currency"), "basetype": base}
        if level:
            item["gem_level"] = level
        block, _ = fs.evaluate(blocks, item)
        trusted = bf.reliable(cfg, div, volume)
        tier = ("pinned" if name in bf.PINNED_TOP else tiers.of(div) if trusted
                else "neversink" if name in deferred else "unknown")
        rows.append({"name": name, "feed": feed, "div": div, "vol": volume, "tier": tier,
                     "trusted": trusted, "shown": block is None or block.action != "Hide",
                     "rule": block.comment if block else "(no rule: shown)"})
    return rows


def write(cfg, text, r, league, path):
    prices, tiers = r["prices"], r["tiers"]
    meta = {"league": league, "when": f"{datetime.now():%Y-%m-%d %H:%M}",
            "ex": bf.per_divine(prices, "Exalted Orb"), "chaos": bf.per_divine(prices, "Chaos Orb"),
            "tiers": [{"name": n, "div": v, "hidden": n in cfg["hide_tiers"], "quiet": n in cfg["quiet_tiers"]}
                      for n, v in tiers.ordered]}
    rows = collect(cfg, fs.parse(text), r)
    payload = json.dumps({"meta": meta, "rows": rows}, separators=(",", ":")).replace("</", "<\\/")
    path.parent.mkdir(exist_ok=True)
    path.write_text(PAGE.replace("__DATA__", payload).replace("__LEAGUE__", html.escape(league)),
                    encoding="utf-8")
    return path


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoE2 Filter Report</title>
<style>
:root{--bg:#121212;--panel:#1c1c1c;--line:#2c2c2c;--fg:#ddd;--dim:#888;--ok:#6fbf73}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:16px;margin:0 0 8px;font-weight:600}
h1 small{color:var(--dim);font-weight:400}
.tiers{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.tc{display:inline-flex;gap:6px;align-items:baseline;padding:3px 8px;border:1px solid var(--line);border-radius:6px;background:#0e0e0e;font-size:12px;white-space:nowrap}
.tc b{font-weight:600}.tc i{color:var(--dim);font-style:normal}
.tc.rate{border-color:#555}.tc.off{opacity:.5}.tc.off b{text-decoration:line-through}
.t-top b,.t-high b,.t-pinned b{color:#e33}.t-mid b{color:#ec3}.t-minor b,.t-low b{color:#ddd}
.t-brown b,.t-dust b{color:#d2b286}.t-unknown b,.t-neversink b{color:#38f}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
input,select{background:#0e0e0e;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
input[type=search]{flex:1 1 220px;min-width:0}
.stats{color:var(--dim);font-size:12px;margin-top:6px}.stats b{color:var(--fg)}
main{padding:0 16px 40px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:760px}
th{text-align:left;color:var(--dim);font-weight:500;font-size:12px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none}
td{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.v{font-weight:600}.v.s{color:var(--ok)}.v.h{color:var(--dim)}
.rule{color:var(--dim);font-size:12px;font-family:Consolas,monospace}
tr.hid td:first-child{opacity:.55}
</style></head><body>
<header>
<h1>PoE2 filter report <small>__LEAGUE__ · <span id="meta"></span></small></h1>
<div class="tiers" id="tiers"></div>
<div class="bar">
<input type="search" id="q" placeholder="Search item, feed, tier, rule…">
<select id="feed"><option value="">All feeds</option></select>
<select id="vis"><option value="">Shown + hidden</option><option value="1">Shown</option><option value="0">Hidden</option></select>
</div>
<div class="stats" id="stats"></div>
</header>
<main>
<table><thead><tr>
<th data-k="name">Item</th><th data-k="feed">Feed</th><th data-k="div" class="num">Value</th>
<th data-k="div" class="num">Div</th><th data-k="vol" class="num">Traded (div)</th>
<th data-k="tier">Tier</th><th data-k="shown">Filter</th><th data-k="rule">Deciding rule</th>
</tr></thead><tbody id="tb"></tbody></table>
</main>
<script>
const D=__DATA__, M=D.meta, R=D.rows;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num=v=>v>=100?Math.round(v).toLocaleString():v>=10?v.toFixed(1):v>=1?v.toFixed(2):v.toFixed(3);
// value in the unit players use: div >= 1, else chaos >= 1, else exalted
const val=d=>d>=1?`${num(d)} div`:M.chaos&&d*M.chaos>=1?`${num(d*M.chaos)}c`:M.ex?`${num(d*M.ex)} ex`:`${num(d)} div`;
const ex=d=>M.ex?`${num(d*M.ex)} ex`:val(d);
const frac=d=>d>=1?`${+d.toFixed(2)} div`:`1/${Math.round(1/d)} div`;
{const pts=[];
 if(M.ex)pts.push(`<span class="tc rate"><b>1 div = ${num(M.ex)} ex</b></span>`);
 if(M.chaos)pts.push(`<span class="tc rate"><b>1 div = ${num(M.chaos)}c</b></span>`);
 M.tiers.forEach((t,i)=>{const nxt=M.tiers[i-1];
  const range=t.div>0?`≥ ${ex(t.div)}`:nxt?`< ${ex(nxt.div)}`:"any";
  pts.push(`<span class="tc t-${esc(t.name)}${t.hidden?" off":""}"><b>${esc(t.name)}</b>${range}<i>${t.div>0?frac(t.div):""}${t.hidden?" hidden":t.quiet?" quiet":""}</i></span>`)});
 $("tiers").innerHTML=pts.join("")}
$("meta").textContent=`built ${M.when}`;
[...new Set(R.map(r=>r.feed))].sort().forEach(f=>$("feed").insertAdjacentHTML("beforeend",`<option>${esc(f)}</option>`));
let key="div",dir=-1;
document.querySelectorAll("th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;dir=k===key?-dir:(k==="div"||k==="vol"?-1:1);key=k;draw()});
function draw(){
 const q=$("q").value.toLowerCase(),f=$("feed").value,v=$("vis").value;
 const rows=R.filter(r=>(!f||r.feed===f)&&(v===""||String(+r.shown)===v)&&
   (!q||[r.name,r.feed,r.tier,r.rule].join(" ").toLowerCase().includes(q)))
  .sort((a,b)=>(a[key]>b[key]?1:a[key]<b[key]?-1:0)*dir);
 const sh=rows.filter(r=>r.shown).length;
 $("stats").innerHTML=`<b>${rows.length}</b> items · <b>${sh}</b> shown · <b>${rows.length-sh}</b> hidden · `+
  `<b>${rows.filter(r=>r.tier==="neversink").length}</b> thin market, NeverSink tier`;
 $("tb").innerHTML=rows.map(r=>`<tr class="${r.shown?"":"hid"}"><td>${esc(r.name)}</td><td>${esc(r.feed)}</td>
<td class="num">${val(r.div)}</td><td class="num">${num(r.div)}</td><td class="num">${num(r.vol)}</td>
<td class="tc t-${esc(r.tier)}" style="display:table-cell;border:0;background:none"><b>${esc(r.tier)}</b></td>
<td><span class="v ${r.shown?"s":"h"}">${r.shown?"shown":"hidden"}</span></td><td class="rule">${esc(r.rule)}</td></tr>`).join("");
}
["q","feed","vis"].forEach(id=>$(id).oninput=draw);
draw();
</script></body></html>
"""
