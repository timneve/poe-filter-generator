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
            volume = r.get("card_volumes", {}).get(name, 0)
            if volume >= cfg["exchange"]["card_fallback_min_volume"]:
                note = (f"no reliable buy-order price; exchange activity {volume:.1f}c meets "
                        "threshold, so kept unknown instead of using NeverSink fallback")
            else:
                note = (f"no reliable buy-order or currency-recipe price; low activity "
                        f"({volume:.1f}c), regular NeverSink fallback tier {tier}")
            add("Card", name, "", None, None, {"class": "Divination Cards", "basetype": name},
                note)

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
            tier, cheapest, best, best_name, *ev = (r["fbases"] if foul else r["ubases"]).get(base, ("unpriced", None, 0, ""))
            note = f"base tier {tier}"
            if nomap:
                note = f"not priced, can't drop in maps ({nomap[:80]}); " + note
            if cheapest is not None:
                note += f": cheapest {cheapest:.0f}c, best {best:.0f}c {best_name}"
            if ev and ev[0] is not None:
                note += f", EV per drop {ev[0]:.1f}c"
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


def browser_rules(blocks):
    """Serialize parsed filter rules for the offline item checker in report.html."""
    return [{
        "action": b.action,
        "comment": b.comment,
        "line": b.line_no,
        "continue": b.cont,
        "conditions": [{"key": key, "op": op, "values": values}
                       for key, op, values, _ in b.conds],
    } for b in blocks]


def write(cfg, data, text, r, league, path):
    blocks = fs.parse(text)
    rows = collect(cfg, data, blocks, r)
    meta = {"league": league, "divine": r["divine"], "when": f"{datetime.now():%Y-%m-%d %H:%M}",
            "safety": cfg["tiers"][cfg["uniques"]["never_hide_tier"]], "jackpot": cfg["jackpot_divine"],
            "review": cfg["tiers"][cfg.get("report", {}).get("review_tier", "mid")]}
    payload = json.dumps({"meta": meta, "rows": rows, "rules": browser_rules(blocks)},
                         separators=(",", ":")).replace("</", "<\\/")
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
textarea{display:block;width:100%;min-height:130px;resize:vertical;background:#0e0e0e;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:8px;font:13px/1.45 Consolas,monospace}
button{background:#333;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:7px 12px;font:inherit;cursor:pointer}
button:hover{background:#444}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0 20px}
.paste-controls{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:end;margin:8px 0}
.paste-controls label{display:grid;gap:3px;color:var(--dim);font-size:12px}
.paste-controls input[type=number]{width:110px}
#item-result{margin-top:10px}
.rule-hit{background:#111;border-left:3px solid var(--line);padding:8px 10px;margin:6px 0}
.rule-hit.decision{border-left-color:var(--ok)}
.rule-hit.hide{border-left-color:var(--warn)}
.rule-hit.uncertain{border-left-color:#ec3}
.rule-hit b{font-family:Consolas,monospace}
.rule-conds{color:var(--dim);font:12px/1.5 Consolas,monospace;margin-top:3px;white-space:pre-wrap;overflow-wrap:anywhere}
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
#lk{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
#lk li{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:6px;padding:8px 12px}
#lk li.bad{border-left-color:#e33}#lk li.ok{border-left-color:var(--ok)}
#lk .t{font-weight:600}#lk .t b{color:var(--warn)}
#lk .ex{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;font-size:12px}
.jp{display:inline-block;margin-left:6px;padding:0 5px;border-radius:4px;background:#5a3fd0;color:#fff;font-size:10px;font-weight:700;letter-spacing:.04em;vertical-align:middle}
</style></head><body>
<header>
<h1>Filter report <small>__LEAGUE__ · <span id="meta"></span></small></h1>
</header>
<main>
<section class="panel" id="item-check">
<h2>Check an item <small>· paste the in-game item text</small></h2>
<p class="note">Copy an item in Path of Exile and paste it here. Rules are checked in order: matching Continue rules apply style and keep checking; the first matching non-Continue rule decides. Area level is not in copied item text, so set it to the zone where it dropped (83 for maps).</p>
<textarea id="item-paste" spellcheck="false" placeholder="Paste copied item text here…"></textarea>
<div class="paste-controls">
<label>Area level<input type="number" id="item-area" min="1" max="100" value="83"></label>
<label>Corrupted implicit count<input type="number" id="item-corrupted-mods" min="0" max="10" value="0"></label>
<button id="analyze-item" type="button">Check rules</button>
<span class="note">Ctrl+Enter also checks. Set corrupted implicit count only when relevant.</span>
</div>
<details>
<summary>Optional item properties not included in copied text</summary>
<div class="paste-controls">
<label>Width<input type="number" id="item-width" min="1" max="4"></label>
<label>Height<input type="number" id="item-height" min="1" max="4"></label>
<label>Drop level<input type="number" id="item-drop-level" min="1"></label>
<label>Base armour<input type="number" id="item-base-armour" min="0"></label>
<label>Base evasion<input type="number" id="item-base-evasion" min="0"></label>
<label>Base energy shield<input type="number" id="item-base-es" min="0"></label>
</div>
<p class="note">These values are not reliably available from the clipboard. If a matching rule depends on one you left blank, the analyzer reports it as unresolved rather than guessing.</p>
</details>
<div id="item-result" aria-live="polite"></div>
</section>
<h2>Look at these first <small>· hidden and worth ≥ safety, grouped by why</small></h2>
<ul id="lk"></ul>
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
const D=__DATA__, M=D.meta, R=D.rows, RULES=D.rules;
const BEAM={red:"#e33",yellow:"#ec3",blue:"#38f",white:"#eee",grey:"#999",brown:"#a63",pink:"#f6c",green:"#4c4",orange:"#f93",purple:"#a5f",cyan:"#3dd"};
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt=v=>v==null?"–":v>=100?Math.round(v).toLocaleString():v>=1?v.toFixed(1):v.toFixed(2);
const CLASS_ALIASES={
 "Body Armour":"Body Armours","Two Handed Axe":"Two Hand Axes","Two Handed Mace":"Two Hand Maces",
 "Two Handed Sword":"Two Hand Swords","One Handed Axe":"One Hand Axes","One Handed Mace":"One Hand Maces",
 "One Handed Sword":"One Hand Swords","Thrusting One Handed Sword":"Thrusting One Hand Swords",
 "Staff":"Staves","Fishing Rod":"Fishing Rods","Jewel":"Jewels","Cluster Jewel":"Jewels",
 "Life Flask":"Life Flasks","Mana Flask":"Mana Flasks","Hybrid Flask":"Hybrid Flasks",
 "Utility Flask":"Utility Flasks","Skill Gem":"Skill Gems","Support Gem":"Support Gems",
 "Divination Card":"Divination Cards","Map":"Maps"
};
const RARITY_RANK={Normal:0,Magic:1,Rare:2,Unique:3};
const NUM_FIELDS={
 StackSize:"stack",ItemLevel:"ilvl",Quality:"quality",LinkedSockets:"links",
 CorruptedMods:"corrupted_mods",Sockets:"sockets",DropLevel:"drop_level",
 Width:"width",Height:"height",AreaLevel:"area_level",BaseArmour:"armour",
 BaseEvasion:"evasion",BaseEnergyShield:"es"
};
const BOOL_FIELDS={Corrupted:"corrupted",Mirrored:"mirrored",Identified:"identified",Foulborn:"foulborn"};
function parseCopiedItem(raw,areaLevel,corruptedMods,extra){
 const lines=raw.split(/\r?\n/).map(x=>x.trim());
 const classLine=lines.find(x=>/^Item Class:\s*/i.test(x));
 const rarityLine=lines.find(x=>/^Rarity:\s*/i.test(x));
 if(!classLine||!rarityLine)throw new Error("Could not find Item Class and Rarity. Paste the complete copied item text.");
 const rawClass=classLine.replace(/^Item Class:\s*/i,"").trim();
 const rarity=rarityLine.replace(/^Rarity:\s*/i,"").trim();
 if(!(rarity in RARITY_RANK))throw new Error(`Unsupported item rarity: ${rarity}`);
 const rarityIndex=lines.indexOf(rarityLine),header=[];
 for(let i=rarityIndex+1;i<lines.length&&!/^-{3,}$/.test(lines[i]);i++)if(lines[i])header.push(lines[i]);
 if(!header.length)throw new Error("Could not identify the item base type in the copied text.");
 const item={
  "class":CLASS_ALIASES[rawClass]||rawClass,basetype:header[header.length-1],rarity,
  area_level:areaLevel,corrupted_mods:corruptedMods,quality:0,identified:!lines.some(x=>/^Unidentified$/i.test(x)),
  corrupted:lines.some(x=>/^Corrupted$/i.test(x)),mirrored:lines.some(x=>/^Mirrored$/i.test(x)),
  foulborn:lines.some(x=>/\bFoulborn\b/i.test(x)),mods:[raw]
 };
 const readNumber=(pattern,field)=>{const m=raw.match(pattern);if(m)item[field]=Number(m[1])};
 readNumber(/^\s*Item Level:\s*(\d+)/im,"ilvl");
 readNumber(/^\s*Stack Size:\s*(\d+)(?:\s*\/\s*\d+)?/im,"stack");
 readNumber(/^\s*Quality:\s*\+?(\d+)\s*%/im,"quality");
 const sock=raw.match(/^\s*Sockets:\s*(.+)$/im);
 if(sock){
  const groups=sock[1].trim().split(/\s+/).map(x=>x.replace(/[^RGBWDA]/gi,"")).filter(Boolean);
  item.sockets=groups.reduce((n,x)=>n+x.length,0);
  item.links=groups.reduce((n,x)=>Math.max(n,x.length),0);
  item.socket_group=sock[1].trim();
 }
 item.influence=["Shaper","Elder","Crusader","Redeemer","Hunter","Warlord"]
   .filter(x=>new RegExp(`\\b${x} Item\\b`,"i").test(raw));
 Object.entries(extra).forEach(([field,value])=>{if(value!==null)item[field]=value});
 return item;
}
function compare(a,op,b){
 if(op==="="||op==="==")return a===b;
 if(op==="!="||op==="!")return a!==b;
 if(op==="<")return a<b;if(op==="<=")return a<=b;
 if(op===">")return a>b;if(op===">=")return a>=b;
 throw new Error(`Unsupported rule operator: ${op}`);
}
function matchesCondition(item,c){
 const vals=c.values;
 if(c.key==="Class"||c.key==="BaseType"){
  const value=item[c.key==="Class"?"class":"basetype"]||"";
  const hit=vals.some(x=>c.op==="=="?value===x:value.includes(x));
  return ["!","!="].includes(c.op)?!hit:hit;
 }
 if(c.key==="Rarity"){
  const value=RARITY_RANK[item.rarity]??0;
  if(c.op==="="||c.op==="==")return vals.some(x=>value===RARITY_RANK[x]);
  if(c.op==="!"||c.op==="!=")return vals.every(x=>value!==RARITY_RANK[x]);
  return compare(value,c.op,RARITY_RANK[vals[0]]);
 }
 if(c.key in NUM_FIELDS){
  const value=item[NUM_FIELDS[c.key]];
  return value===undefined?null:compare(value,c.op,Number(vals[0]));
 }
 if(c.key in BOOL_FIELDS)return Boolean(item[BOOL_FIELDS[c.key]])===(vals[0]==="True");
 if(c.key==="SocketGroup")return vals.some(x=>(item.socket_group||"").includes(x));
 if(c.key==="HasExplicitMod")return vals.some(x=>item.mods.some(m=>m.includes(x)));
 if(c.key==="HasInfluence"){
  const infl=new Set(item.influence||[]);
  if(vals.length===1&&vals[0]==="None")return infl.size===0;
  return c.op==="=="?vals.every(x=>infl.has(x)):vals.some(x=>infl.has(x));
 }
 throw new Error(`Unsupported filter condition: ${c.key}`);
}
function traceRules(item,rules=RULES){
 const matched=[];let decision=null,uncertainDecision=null;
 for(const rule of rules){
  const unknown=[];
  let failed=false;
  for(const c of rule.conditions){
   const result=matchesCondition(item,c);
   if(result===false){failed=true;break}
   if(result===null)unknown.push(c.key);
  }
  if(failed)continue;
  const uncertain=unknown.length>0;
  matched.push({rule,uncertain,unknown:[...new Set(unknown)]});
  if(uncertain){
   if(!rule.continue){uncertainDecision=rule;break}
   continue;
  }
  if(!rule.continue){decision=rule;break}
 }
 return {matched,decision,uncertainDecision};
}
function analyzeCopiedItem(){
 const result=$("item-result"),raw=$("item-paste").value;
 try{
  if(!raw.trim())throw new Error("Paste an item first.");
  const area=Number($("item-area").value)||83;
  const corruptedMods=Number($("item-corrupted-mods").value)||0;
  const optional=id=>$(id).value===""?null:Number($(id).value);
  const extra={
   width:optional("item-width"),height:optional("item-height"),drop_level:optional("item-drop-level"),
   armour:optional("item-base-armour"),evasion:optional("item-base-evasion"),es:optional("item-base-es")
  };
  const item=parseCopiedItem(raw,area,corruptedMods,extra);
  const trace=traceRules(item),decision=trace.decision,uncertain=trace.uncertainDecision;
  const shown=uncertain?null:!decision||decision.action!=="Hide";
  const headline=uncertain?`Unresolved — possible ${uncertain.action} #${uncertain.comment} (line ${uncertain.line})`:
   decision?`${decision.action} — ${decision.comment||"rule"} (line ${decision.line})`:
   "Shown by default — no deciding rule matched";
  const details=trace.matched.length?trace.matched.map(hit=>{
   const {rule}=hit;
   const deciding=rule===decision;
   const title=`${rule.action} # ${rule.comment||"(no comment)"}`;
   const state=hit.uncertain?`NEEDS ${hit.unknown.join(", ")}`:deciding?"DECIDES":rule.continue?"Continue — style only":"";
   const conditions=rule.conditions.length?rule.conditions.map(c=>`${c.key} ${c.op} ${c.values.map(x=>JSON.stringify(x)).join(" ")}`).join("\n"):"No conditions";
   return `<div class="rule-hit ${hit.uncertain?"uncertain":deciding?(rule.action==="Hide"?"hide":"decision"):""}"><b>${esc(title)}</b> <span class="note">· line ${rule.line}${state?` · ${state}`:""}</span><div class="rule-conds">${esc(conditions)}</div></div>`;
  }).join(""):`<p class="note">No filter rule matched. Items with no matching rule are shown by default.</p>`;
  const summary=`${item.rarity} · ${item["class"]} · ${item.basetype} · ilvl ${item.ilvl??"not shown"} · ${item.identified?"identified":"unidentified"}${item.corrupted?", corrupted":""}`;
  const note=trace.matched.some(x=>x.uncertain&&x.rule.continue)?"Some matching style rules need optional values, but evaluation continued to the deciding rule.":"";
  result.innerHTML=`<div class="stats"><b class="${shown===null?"":shown?"v s":"v h"}">${esc(headline)}</b><br>${esc(summary)}<br>Assumptions: AreaLevel ${area}; CorruptedMods ${corruptedMods}. Mod conditions are checked against the pasted text.${note?`<br>${esc(note)}`:""}</div><h3>Matching rules, in order</h3>${details}`;
 }catch(e){result.textContent=e.message}
}
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
$("analyze-item").addEventListener("click",analyzeCopiedItem);
$("item-paste").addEventListener("keydown",e=>{if(e.ctrlKey&&e.key==="Enter")analyzeCopiedItem()});
render();
const rev=R.filter(r=>!r.nomap&&!r.shown&&(r.c||0)>=M.review);
$("revsub").textContent=`· ${rev.length} hidden items ≥ ${M.review}c (config [report] review_tier)`;
$("rb").innerHTML=rev.length?rev.map(r=>`<tr class="${r.risk?"risk":""}"><td>${label(r)}</td><td>${esc(r.cat)}</td><td>${esc(r.base)}</td>
<td class="num">${fmt(r.c)}</td><td class="num">${M.divine?fmt(r.c/M.divine):"–"}</td><td class="num">${r.n??"–"}</td>
<td><div class="rule">${esc(r.rule)} <span>:${r.line}</span></div>${r.note?`<div class="note">${esc(r.note)}</div>`:""}</td></tr>`).join("")
 :`<tr><td colspan="7" class="empty">Nothing priced ≥ ${M.review}c is hidden.</td></tr>`;
const unq=r=>["Unique","Foulborn","Replica"].includes(r.cat),lnk=r=>/\(\dL\)$/.test(r.name);
const checks=[
 {sev:"bad",t:`Hidden worth ≥ ${M.jackpot} div`,rows:R.filter(r=>!r.nomap&&!r.shown&&r.jp),
  why:"The jackpot rule should never let these hide: bug in rules or config.",ok:`Nothing worth ≥ ${M.jackpot} div is hidden.`},
 {t:"Linked uniques hidden",rows:R.filter(r=>r.risk&&unq(r)&&lnk(r)),
  why:`The price comes from the links, but the linked rule only fires at ≥ ${M.jackpot} div. Lower jackpot_divine to catch them, or accept.`},
 {t:"Chase uniques on hidden bases",rows:R.filter(r=>r.risk&&unq(r)&&!lnk(r)),
  why:"Unidentified, the filter only sees the base, and the cheapest unique on it is junk. Worth farming? Add the base to [unique_overrides] as \"variable\", or set uniques.variable_jackpot_only = false."},
 {t:"Crafting bases hidden with real volume",rows:R.filter(r=>r.risk&&r.cat==="Crafting base"&&(r.n||0)>=50),
  why:"This high-volume price meets the safety threshold but the item is hidden. Check the matching ilvl/influence rule."},
];
$("lk").innerHTML=checks.filter(k=>k.rows.length||k.ok).map(k=>!k.rows.length?`<li class="ok"><span class="t">✓ ${esc(k.ok)}</span></li>`:
 `<li class="${k.sev||""}"><div class="t"><b>${k.rows.length}</b> ${esc(k.t)}</div><div class="note">${esc(k.why)}</div><div class="ex">`+
 k.rows.slice(0,6).map(r=>`<span>${label(r)} ${fmt(r.c)}c${r.base&&r.cat==="Crafting base"?` · ${esc(r.base)}`:""}${r.n?` · ${r.n} listed`:""}</span>`).join("")+
 (k.rows.length>6?`<span class="note">+${k.rows.length-6} more below</span>`:"")+`</div></li>`).join("");
</script></body></html>
"""
