"""out/report.html: every priced item replayed through the built filter, shown or hidden.

Uses filtersim, so the verdict is what the filter text actually does, not what the pricing
code meant. Open the html in a browser: search, filter by category / shown / hidden.
Items are dropped unidentified (uniques) or as single stacks (stackables).
"""
import html
import json
from datetime import datetime

import filtersim as fs

# poe.ninja itemType -> in-game Class (close enough for the filter's class rules)
NINJA_CLASS = {
    "Two Handed Sword": "Two Hand Swords", "Two Handed Axe": "Two Hand Axes", "Staff": "Staves",
    "Bow": "Bows", "Wand": "Wands", "One Handed Axe": "One Hand Axes",
    "One Handed Sword": "One Hand Swords", "Fishing Rod": "Fishing Rods", "Claw": "Claws",
    "Two Handed Mace": "Two Hand Maces", "One Handed Mace": "One Hand Maces", "Dagger": "Daggers",
    "Shield": "Shields", "Body Armour": "Body Armours", "Boots": "Boots", "Helmet": "Helmets",
    "Gloves": "Gloves", "Quiver": "Quivers", "Belt": "Belts", "Ring": "Rings", "Amulet": "Amulets",
    "Utility Flask": "Utility Flasks", "Mana Flask": "Mana Flasks", "Hybrid Flask": "Hybrid Flasks",
    "Life Flask": "Life Flasks", "Jewel": "Jewels", "Cluster Jewel": "Jewels", "Tincture": "Tinctures",
}
STACK_CLASS = {"DivinationCard": "Divination Cards", "Fragment": "Map Fragments",
               "Scarab": "Map Fragments", "Invitation": "Misc Map Items", "Wombgift": "Wombgifts"}
# in-game default text colours when no rule sets one
DEFAULT_TEXT = {"Unique": "175 96 37", "Rare": "255 255 119", "Magic": "136 136 255"}


def unique_class(line, t):
    if t == "UniqueMap":
        return "Maps"
    return NINJA_CLASS.get(line.get("itemType"), "Jewels" if t == "UniqueJewel" else None)


def look(style, item):
    """Last-wins colours from the applied style lines -> css-ish dict."""
    got = {}
    for s in style:
        w = s.split()
        if w[0] in ("SetTextColor", "SetBorderColor", "SetBackgroundColor"):
            got[w[0]] = [int(x) for x in w[1:5]] + [255] * (4 - len(w[1:5]))
        elif w[0] == "SetFontSize":
            got["size"] = int(w[1])
        elif w[0] == "PlayEffect":
            got["beam"] = w[1].lower()
        elif w[0] == "PlayAlertSound":
            got["sound"] = True
    text = got.get("SetTextColor") or [int(x) for x in DEFAULT_TEXT.get(item.get("rarity"), "200 200 200").split()] + [255]
    rgba = lambda c: f"rgba({c[0]},{c[1]},{c[2]},{c[3] / 255:.2f})"
    out = {"fg": rgba(text), "size": got.get("size", 32)}
    if "SetBackgroundColor" in got:
        out["bg"] = rgba(got["SetBackgroundColor"])
    if "SetBorderColor" in got and got["SetBorderColor"][3] > 0:
        out["bd"] = rgba(got["SetBorderColor"])
    if "beam" in got:
        out["beam"] = got["beam"]
    if got.get("sound"):
        out["snd"] = 1
    return out


def collect(cfg, data, blocks, r):
    rows = []

    def add(cat, name, base, chaos, listings, item, note=""):
        b, style = fs.evaluate(blocks, item)
        rows.append({
            "cat": cat, "name": name, "base": base, "c": chaos, "n": listings, "note": note,
            "shown": b is None or b.action != "Hide",
            "rule": f"{b.action} # {b.comment}" if b else "(no rule matched: shown)",
            "line": b.line_no if b else 0, "look": look(style, item), "nomap": cat == "No map drop",
        })

    for name, (v, t) in r["prices"].items():
        add("Card" if t == "DivinationCard" else t, name, "", v, None,
            {"class": STACK_CLASS.get(t, "Stackable Currency"), "basetype": name, "stack": 1})
    for name, tier in r["ref_cards"].items():
        if name not in r["prices"]:
            add("Card", name, "", None, None, {"class": "Divination Cards", "basetype": name},
                f"no poe.ninja price, NeverSink tier -> {tier}")

    for t in [t for t in data["stash"] if t.startswith("Unique")]:
        for line in data["stash"][t].get("lines", []):
            name, base = line["name"], line.get("baseType")
            if not base or line.get("listingCount", 0) < 1:
                continue
            foul = name.startswith("Foulborn ")
            nomap = data.get("nomap", {}).get(name[9:] if foul else name)
            cat = "No map drop" if nomap else "Foulborn" if foul else "Replica" if name.startswith("Replica ") else "Unique"
            label = name + (f" [{line['variant']}]" if line.get("variant") else "")
            if line.get("links"):
                label += f" ({line['links']}L)"
            tier, cheapest, best, best_name = (r["fbases"] if foul else r["ubases"]).get(base, ("unpriced", None, 0, ""))
            note = f"base tier {tier}"
            if nomap:
                note = f"not priced, can't drop in maps ({nomap[:80]}); " + note
            if cheapest is not None:
                note += f": cheapest {cheapest:.0f}c, best {best:.0f}c {best_name}"
            add(cat, label, base, line["chaosValue"], line.get("listingCount"),
                {"rarity": "Unique", "basetype": base, "class": unique_class(line, t), "ilvl": 84,
                 "foulborn": foul, "links": line.get("links") or 0}, note)

    # every confident poe.ninja base entry worth >= top tier, as it drops (its ilvl + influence),
    # so hidden ones (dual influence, outlier-floored) show up too
    b = cfg["bases"]
    top = max(cfg["tiers"].values())
    for line in data["stash"]["BaseType"].get("lines", []):
        if line["chaosValue"] < top or line.get("listingCount", 0) < b["min_listings"] \
                or line.get("count", 0) < b["min_samples"]:
            continue
        infl, ilvl = line.get("variant"), line.get("levelRequired", 0)
        if infl and "/" in infl:
            continue  # dual influence: Awakener's Orb crafts only, never drops
        add("Crafting base", line["name"], f"ilvl {ilvl} {infl or ''}".strip(), line["chaosValue"],
            line.get("listingCount"),
            {"class": NINJA_CLASS.get(line.get("itemType")), "basetype": line["name"], "rarity": "Rare",
             "ilvl": ilvl, "influence": infl.split("/") if infl else []})
    rows.sort(key=lambda x: -(x["c"] or 0))
    return rows


def write(cfg, data, text, r, league, path):
    rows = collect(cfg, data, fs.parse(text), r)
    meta = {"league": league, "divine": r["divine"], "when": f"{datetime.now():%Y-%m-%d %H:%M}",
            "safety": cfg["uniques"]["never_hide_chaos"], "jackpot": cfg["jackpot_divine"],
            "review": cfg.get("report", {}).get("review_chaos", 5)}
    payload = json.dumps({"meta": meta, "rows": rows}, separators=(",", ":")).replace("</", "<\\/")
    path.parent.mkdir(exist_ok=True)
    path.write_text(PAGE.replace("__DATA__", payload).replace("__LEAGUE__", html.escape(league)), encoding="utf-8")
    return path


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Filter Report</title>
<style>
:root{--bg:#121212;--panel:#1c1c1c;--line:#2c2c2c;--fg:#ddd;--dim:#888;--warn:#ff6b4a;--ok:#6fbf73}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--panel);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:16px;margin:0 0 8px;font-weight:600}
h1 small{color:var(--dim);font-weight:400}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
input,select{background:#0e0e0e;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
input[type=search]{flex:1 1 220px;min-width:0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.seg button{background:#0e0e0e;color:var(--dim);border:0;padding:6px 10px;font:inherit;cursor:pointer}
.seg button.on{background:#333;color:var(--fg)}
.stats{color:var(--dim);font-size:12px;margin-top:6px}
.stats b{color:var(--fg)}
.stats .w{color:var(--warn)}
main{padding:0 16px 40px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:760px}
th{position:sticky;top:0;text-align:left;color:var(--dim);font-weight:500;font-size:12px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none;background:var(--bg)}
td{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.lbl{display:inline-block;padding:1px 6px;background:rgba(0,0,0,.85);border:1px solid transparent;font-family:"Fontin SmallCaps",Georgia,serif;white-space:nowrap}
.beam{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:6px;vertical-align:middle}
.snd{color:var(--dim);font-size:11px;margin-left:4px}
.v{font-weight:600}.v.s{color:var(--ok)}.v.h{color:var(--dim)}
tr.risk td{background:rgba(255,107,74,.10)}
tr.risk .v.h{color:var(--warn)}
.rule{color:var(--dim);font-size:12px;font-family:Consolas,monospace}
.note{color:var(--dim);font-size:12px}
.hid .lbl{opacity:.45}
h2{font-size:15px;margin:20px 0 4px;font-weight:600}
h2 small{color:var(--dim);font-weight:400}
#rev{margin-bottom:24px}
details{border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;font-weight:600;margin-bottom:10px}
details .bar{position:sticky;top:0;z-index:2;background:var(--bg);padding:8px 0}
.empty{color:var(--ok);padding:10px 6px}
.jp{display:inline-block;margin-left:6px;padding:0 5px;border-radius:4px;background:#5a3fd0;color:#fff;font-size:10px;font-weight:700;letter-spacing:.04em;vertical-align:middle}
</style></head><body>
<header>
<h1>Filter report <small>__LEAGUE__ · <span id="meta"></span></small></h1>
</header>
<main>
<h2>Hidden, worth a look <small id="revsub"></small></h2>
<p class="note">Items the filter hides even though poe.ninja prices them at or above the review line. Each one is either intended
(e.g. a base tiered by its cheapest unique) or something to fix in config.toml.</p>
<table id="rev"><thead><tr><th>Item</th><th>Category</th><th>Base</th><th class="num">Chaos</th><th class="num">Div</th><th class="num">Listings</th><th>Why hidden</th></tr></thead><tbody id="rb"></tbody></table>
<details id="all"><summary>All items (search / filter)</summary>
<div class="bar">
<input type="search" id="q" placeholder="Search name, base, rule…">
<select id="cat"><option value="">All categories</option></select>
<span class="seg" id="vis"><button data-v="" class="on">All</button><button data-v="1">Shown</button><button data-v="0">Hidden</button><button data-v="risk">Hidden ≥ safety</button><button data-v="jp">Jackpots</button></span>
<label class="note"><input type="number" id="min" min="0" step="1" style="width:80px" placeholder="min c"> min chaos</label>
</div>
<div class="stats" id="stats"></div>
<table><thead><tr>
<th data-k="name">Item (as it drops)</th><th data-k="cat">Category</th><th data-k="base">Base</th>
<th data-k="c" class="num">Chaos</th><th data-k="c" class="num">Div</th><th data-k="n" class="num">Listings</th>
<th data-k="shown">Filter</th><th data-k="rule">Deciding rule / note</th>
</tr></thead><tbody id="tb"></tbody></table></details></main>
<script>
const D=__DATA__, M=D.meta, R=D.rows;
const BEAM={red:"#e33",yellow:"#ec3",blue:"#38f",white:"#eee",grey:"#999",brown:"#a63",pink:"#f6c",green:"#4c4",orange:"#f93",purple:"#a5f",cyan:"#3dd"};
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt=v=>v==null?"–":v>=100?Math.round(v).toLocaleString():v>=1?v.toFixed(1):v.toFixed(2);
$("meta").textContent=`built ${M.when} · divine ${Math.round(M.divine)}c · safety ${M.safety}c · jackpot ≥ ${M.jackpot} div`;
R.forEach(r=>{r.risk=!r.nomap&&!r.shown&&(r.c||0)>=M.safety;r.jp=M.divine>0&&(r.c||0)>=M.jackpot*M.divine});
[...new Set(R.map(r=>r.cat))].sort().forEach(c=>$("cat").insertAdjacentHTML("beforeend",`<option>${esc(c)}</option>`));
let vis="",sortK="c",sortDir=-1;
function store(k,v){try{localStorage.setItem("fr_"+k,v)}catch(e){}}
function load(k){try{return localStorage.getItem("fr_"+k)}catch(e){return null}}
function label(r){const L=r.look;let st=`color:${L.fg};font-size:${Math.max(11,Math.round(L.size*0.33))}px`;
 if(L.bg)st+=`;background:${L.bg}`;if(L.bd)st+=`;border-color:${L.bd}`;
 return `<span class="lbl" style="${st}">${esc(r.name)}</span>`+(L.beam?`<span class="beam" title="beam ${L.beam}" style="background:${BEAM[L.beam]||"#888"}"></span>`:"")+(L.snd?`<span class="snd" title="alert sound">♪</span>`:"")+(r.jp?`<span class="jp" title="≥ ${M.jackpot} div">JACKPOT</span>`:"")}
function render(){
 const q=$("q").value.toLowerCase().trim(),cat=$("cat").value,min=parseFloat($("min").value)||0;
 let rows=R.filter(r=>(!cat||r.cat===cat)&&(r.c||0)>=min&&
  (vis===""||(vis==="risk"?r.risk:vis==="jp"?r.jp:String(+r.shown)===vis))&&
  (!q||(r.name+" "+r.base+" "+r.rule+" "+r.note).toLowerCase().includes(q)));
 rows.sort((a,b)=>{let x=a[sortK],y=b[sortK];if(x==null)x=sortK==="c"||sortK==="n"?-1:"";if(y==null)y=sortK==="c"||sortK==="n"?-1:"";return (x>y?1:x<y?-1:0)*sortDir});
 const sh=rows.filter(r=>r.shown).length,risk=rows.filter(r=>r.risk).length;
 $("stats").innerHTML=`<b>${rows.length}</b> items · <b>${sh}</b> shown · <b>${rows.length-sh}</b> hidden`+(risk?` · <span class="w"><b>${risk}</b> hidden worth ≥ ${M.safety}c</span>`:"");
 $("tb").innerHTML=rows.slice(0,3000).map(r=>`<tr class="${r.risk?"risk":""} ${r.shown?"":"hid"}"><td>${label(r)}</td><td>${esc(r.cat)}</td><td>${esc(r.base)}</td>
<td class="num">${fmt(r.c)}</td><td class="num">${r.c==null||!M.divine?"–":fmt(r.c/M.divine)}</td><td class="num">${r.n??"–"}</td>
<td class="v ${r.shown?"s":"h"}">${r.shown?"Shown":"Hidden"}</td>
<td><div class="rule">${esc(r.rule)}${r.line?` <span title="line in pricefilter.filter">:${r.line}</span>`:""}</div>${r.note?`<div class="note">${esc(r.note)}</div>`:""}</td></tr>`).join("")+
 (rows.length>3000?`<tr><td colspan="8" class="note">…${rows.length-3000} more, narrow the search</td></tr>`:"");
 store("q",$("q").value);store("cat",cat);store("vis",vis);store("min",$("min").value);
}
$("q").value=load("q")||"";$("min").value=load("min")||"";
const c0=load("cat");if(c0&&[...$("cat").options].some(o=>o.value===c0))$("cat").value=c0;
vis=load("vis")||"";
document.querySelectorAll("#vis button").forEach(b=>{b.classList.toggle("on",b.dataset.v===vis);
 b.onclick=()=>{vis=b.dataset.v;document.querySelectorAll("#vis button").forEach(x=>x.classList.toggle("on",x===b));render()}});
document.querySelectorAll("th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=sortK===k?-sortDir:(k==="c"||k==="n"?-1:1);sortK=k;render()});
["q","cat","min"].forEach(id=>$(id).addEventListener("input",render));
render();
const rev=R.filter(r=>!r.nomap&&!r.shown&&(r.c||0)>=M.review);
$("revsub").textContent=`· ${rev.length} hidden items ≥ ${M.review}c (config [report] review_chaos)`;
$("rb").innerHTML=rev.length?rev.map(r=>`<tr class="${r.risk?"risk":""}"><td>${label(r)}</td><td>${esc(r.cat)}</td><td>${esc(r.base)}</td>
<td class="num">${fmt(r.c)}</td><td class="num">${M.divine?fmt(r.c/M.divine):"–"}</td><td class="num">${r.n??"–"}</td>
<td><div class="rule">${esc(r.rule)} <span>:${r.line}</span></div>${r.note?`<div class="note">${esc(r.note)}</div>`:""}</td></tr>`).join("")
 :`<tr><td colspan="7" class="empty">Nothing priced ≥ ${M.review}c is hidden.</td></tr>`;
</script></body></html>
"""
