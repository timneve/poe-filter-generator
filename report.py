"""out/report.html: every priced item replayed through the built filter, shown or hidden.

Uses filtersim, so the verdict is what the filter text actually does, not what the pricing
code meant. Open the html in a browser: search, filter by category / shown / hidden.
Items are dropped unidentified (uniques) or as single stacks (stackables).
"""
import base64
import html
import json
import shlex
from datetime import datetime
from pathlib import Path

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
               "Scarab": "Map Fragments", "Invitation": "Misc Map Items", "Wombgift": "Wombgifts",
               "Corpse": "Corpses", "Incubator": "Incubators", "Memory": "Memories"}
BASE_FEEDS = ("BaseType", "Flask")  # = build_filter.BASE_TYPES (no import: build_filter imports us)
ASSETS = Path(__file__).parent / "assets"
# in-game default text colours when no rule sets one
DEFAULT_TEXT = {"Unique": "175 96 37", "Rare": "255 255 119", "Magic": "136 136 255"}


def unique_class(line, t):
    if t == "UniqueMap":
        return "Maps"
    if t == "UniqueRelic":
        return "Relics"
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
    for line in (l for t in BASE_FEEDS for l in data["stash"].get(t, {}).get("lines", [])):
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


def unique_ev(data, blocks, r):
    """[uniques.ev] bases -> [{base, ev, tier, cheapest, shown, rule, line, look, uniques}], EV desc.
    uniques = [{name, p (drop share 0..1), c (avg chaos or None = unlisted), t (drop tier)}]."""
    cls = {}
    for t in (t for t in data["stash"] if t.startswith("Unique")):
        for line in data["stash"][t].get("lines", []):
            if line.get("baseType"):
                cls.setdefault(line["baseType"], unique_class(line, t))
    out = []
    for base, parts in r.get("unique_ev", {}).items():
        tier, cheapest, *_, ev = r["ubases"].get(base, ("unpriced", None, 0, "", None))
        item = {"rarity": "Unique", "basetype": base, "class": cls.get(base), "ilvl": 84}
        b, style = fs.evaluate(blocks, item)
        out.append({"base": base, "ev": ev, "tier": tier, "cheapest": cheapest,
                    "shown": b is None or b.action != "Hide",
                    "rule": f"{b.action} # {b.comment}" if b else "(no rule matched: shown)",
                    "line": b.line_no if b else 0, "look": look(style, item),
                    "uniques": [{"name": n, "p": round(share, 4), "c": c, "t": t} for n, share, c, t in parts]})
    out.sort(key=lambda x: -(x["ev"] or 0))
    return out


def content_modules(cfg, data, blocks):
    """[content.*] modules -> [{mod, on, sources, bases: [{base, look, shown, rule, uniques}]}].
    Each base dropped as an unidentified unique, so `look` is what the filter really shows."""
    lines = {}  # base -> poe.ninja unlinked, non-Foulborn unique lines (any listing)
    for t in [t for t in data["stash"] if t.startswith("Unique")]:
        for line in data["stash"][t].get("lines", []):
            if line.get("baseType") and not line.get("links") and not line["name"].startswith("Foulborn "):
                lines.setdefault(line["baseType"], []).append((t, line))
    out = []
    for mod, by_base in data.get("content", {}).items():
        c = cfg["content"][mod]
        bases = []
        for base, names in sorted(by_base.items()):
            cls = next((unique_class(l, t) for t, l in lines.get(base, [])), None)
            item = {"rarity": "Unique", "basetype": base, "class": cls, "ilvl": 84}
            b, style = fs.evaluate(blocks, item)
            uniques = []
            for name in sorted(names):
                prices = [l["chaosValue"] for _, l in lines.get(base, []) if l["name"] == name]
                uniques.append({"name": name, "c": min(prices) if prices else None})
            bases.append({"base": base, "look": look(style, item), "shown": b is None or b.action != "Hide",
                          "rule": f"{b.action} # {b.comment}" if b else "(no rule matched: shown)",
                          "line": b.line_no if b else 0, "uniques": uniques})
        out.append({"mod": mod, "on": bool(c.get("enabled")), "sources": c.get("sources", []), "bases": bases})
    return out


# Example ingredient for a [vendor_recipes.*] entry without `bases`: one cheap base per class
RECIPE_BASE = {"Skill Gems": "Fireball", "Support Gems": "Added Fire Damage Support",
               "Life Flasks": "Divine Life Flask", "Mana Flasks": "Divine Mana Flask",
               "Hybrid Flasks": "Hallowed Hybrid Flask", "Utility Flasks": "Quicksilver Flask"}
RECIPE_CLASS = {"Plate Vest": "Body Armours"}


def recipe_sample(conds):
    """Item fields that satisfy `conds` ('SocketGroup "RGB"', "Sockets >= 6", "Quality >= 20")."""
    item = {}
    for cond in conds:
        key, *rest = shlex.split(cond)
        vals = rest[1:] if rest and rest[0] in fs.OPS else rest
        if key == "SocketGroup":
            item["socket_group"] = vals[0]
            item.setdefault("sockets", len(vals[0]))
        elif key in fs.NUMERIC:
            item[fs.NUMERIC[key]] = int(vals[0])
        elif key in fs.BOOL:
            item[fs.BOOL[key]] = vals[0] == "True"
    return item


def vendor_recipes(cfg, blocks, data=None):
    """[vendor_recipes.<key>] -> [{key, name, on, tier, note, items: [{base, how, look, shown, rule}]}].
    One item per base x `any` condition x rarity (normal .. unidentified unique), replayed through
    the built filter, so `look` / `rule` show what that drop really gets (a better price tier may win).
    `uniques` recipes (vendor value, no blocks): one unidentified unique per base they roll on."""
    out = []
    for key, rec in cfg.get("vendor_recipes", {}).items():
        if rec.get("uniques"):
            out.append(unique_vendor_recipe(key, rec, blocks, data or {}))
            continue
        items = []
        classes = [rec["class"]] if isinstance(rec.get("class"), str) else rec.get("class") or [None]
        sample = recipe_sample(rec.get("conds", []))
        if rec.get("per_quality"):  # tier = "price" quality recipe: best quality below full_quality
            sample.setdefault("quality", rec["full_quality"] - 1 if rec.get("full_quality") else 20)
        for cond in rec.get("any") or [""]:
            flag = cond.split()[0] if cond else ""
            for rarity in rec.get("rarity") or ("Normal", "Magic", "Rare", "Unique"):
                for base in rec.get("bases") or [RECIPE_BASE.get(classes[0], "Plate Vest")]:
                    item = dict(sample, **{"class": classes[0] or RECIPE_CLASS.get(base), "basetype": base,
                                           "rarity": rarity, "ilvl": 84})
                    if flag in fs.BOOL and cond.split()[1:] == ["True"]:
                        item[fs.BOOL[flag]] = True
                    b, style = fs.evaluate(blocks, item)
                    items.append({"base": base, "how": f"{flag.lower()} {rarity.lower()}".strip(),
                                  "look": look(style, item), "shown": b is None or b.action != "Hide",
                                  "rule": f"{b.action} # {b.comment}" if b else "(no rule matched: shown)",
                                  "line": b.line_no if b else 0})
        out.append({"key": key, "name": key.replace("_", " ").title(), "on": bool(rec.get("enabled")),
                    "tier": f"by price of {rec['reward']}" if rec.get("tier") == "price" else rec.get("tier"), "note": rec.get("note", ""),
                    "conds": rec.get("any") or [], "needs": rec.get("conds", []),
                    "rarity": [r.lower() for r in rec.get("rarity") or ("Normal", "Magic", "Rare", "Unique")],
                    "items": items})
    return out


def unique_vendor_recipe(key, rec, blocks, data):
    """vendor_recipes row for a `uniques` recipe: each base (wiki, else poe.ninja) as an unID unique."""
    names = set(rec["uniques"])
    bases, cls = {}, {}
    for t in (t for t in data.get("stash", {}) if t.startswith("Unique")):
        for line in data["stash"][t].get("lines", []):
            if line.get("baseType"):
                cls.setdefault(line["baseType"], unique_class(line, t))
                if line["name"] in names:
                    bases.setdefault(line["baseType"], set()).add(line["name"])
    for base, ns in data.get("wiki_bases", {}).items():
        if ns & names:
            bases.setdefault(base, set()).update(ns & names)
    items = []
    for base in sorted(bases):
        item = {"rarity": "Unique", "basetype": base, "class": cls.get(base), "ilvl": 84}
        b, style = fs.evaluate(blocks, item)
        items.append({"base": base, "how": "unid unique: " + ", ".join(sorted(bases[base])),
                      "look": look(style, item), "shown": b is None or b.action != "Hide",
                      "rule": f"{b.action} # {b.comment}" if b else "(no rule matched: shown)",
                      "line": b.line_no if b else 0})
    reward = f"{rec.get('reward_count', 1)}x {rec['reward']}"
    return {"key": key, "name": key.replace("_", " ").title(), "on": bool(rec.get("enabled")),
            "tier": "vendor value " + reward, "note": rec.get("note", ""), "conds": [], "needs": [],
            "rarity": ["unique"], "items": items}


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


def tier_strip(cfg, tiers):
    """[{name, chaos, div, hidden, quiet, look}] best first, for the report header."""
    divs = cfg.get("tiers_divine", {})
    styles = cfg.get("style", {})
    quiet = cfg.get("quiet_tiers", [])

    def lines(n):
        own = styles.get(n, {}).get("lines", [])
        own = own + styles.get("quiet", {}).get("lines", []) if n in quiet else own
        # config style lines name a [colors] entry ("SetTextColor red") -> its value
        named = lambda w: [w[0], cfg["colors"][w[1]]] if w[0].endswith("Color") and w[1:] and w[1] in cfg.get("colors", {}) else w
        return [" ".join(named(l.split())) for l in own]
    return [{"name": n, "chaos": v, "div": divs.get(n), "hidden": n in cfg.get("hide_tiers", []),
             "quiet": n in quiet, "look": look(lines(n), {})} for n, v in tiers.list]


def unique_tier_strip(cfg, tiers):
    """[{name, shown, why}] best first: [uniques] show toggles, plus a stricter small_loot floor."""
    sl = cfg.get("small_loot", {})
    floor = tiers.names.index(sl["min_tier"]) if sl.get("enabled") else len(tiers.names)
    out = []
    for i, n in enumerate(tiers.names):
        on = bool(cfg["uniques"].get("show", {}).get(n))
        why = "" if on and i <= floor else f"show.{n} = false" if not on else "[small_loot] min_tier"
        out.append({"name": n, "shown": not why, "why": why})
    return out


def icon(name):
    """assets/<name>.png as a data URI, so the report works offline."""
    return "data:image/png;base64," + base64.b64encode((ASSETS / f"{name}.png").read_bytes()).decode()


def write(cfg, data, text, r, league, path):
    blocks = fs.parse(text)
    rows = collect(cfg, data, blocks, r)
    meta = {"league": league, "divine": r["divine"], "when": f"{datetime.now():%Y-%m-%d %H:%M}",
            "safety": cfg["tiers"][cfg["uniques"]["never_hide_tier"]], "jackpot": cfg["jackpot_divine"],
            "review": cfg["tiers"][cfg.get("report", {}).get("review_tier", "mid")],
            "tiers": tier_strip(cfg, r["tiers"]), "unique_tiers": unique_tier_strip(cfg, r["tiers"])}
    payload = json.dumps({"meta": meta, "rows": rows, "rules": browser_rules(blocks),
                          "content": content_modules(cfg, data, blocks),
                          "uev": unique_ev(data, blocks, r),
                          "vendor": vendor_recipes(cfg, blocks, data)},
                         separators=(",", ":")).replace("</", "<\\/")
    path.parent.mkdir(exist_ok=True)
    path.write_text(PAGE.replace("__DATA__", payload).replace("__LEAGUE__", html.escape(league))
                    .replace("__CHAOS__", icon("chaos")).replace("__DIVINE__", icon("divine")), encoding="utf-8")
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
#cm{margin-bottom:12px}
details.cm{padding-top:8px}
details.cm summary{margin-bottom:6px}
details.cm table{margin-bottom:10px}
details{border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;font-weight:600;margin-bottom:10px}
details .bar{position:sticky;top:0;z-index:2;background:var(--bg);padding:8px 0}
.empty{color:var(--ok);padding:10px 6px}
#lk{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
#lk li{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:6px;padding:8px 12px}
#lk li.bad{border-left-color:#e33}#lk li.ok{border-left-color:var(--ok)}
#lk .t{font-weight:600}#lk .t b{color:var(--warn)}
#lk .ex{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;font-size:12px}
.cur{display:inline-block;height:1.25em;width:auto;vertical-align:-.3em;margin-left:2px}
.tiers{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.tc{display:inline-flex;gap:8px;align-items:center;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:#0e0e0e;font-size:15px;line-height:1.3;white-space:nowrap}
.tc b{font-weight:600}.tc i{color:var(--dim);font-style:normal}.tc.tier i{color:inherit;opacity:.7;font-size:.85em}.tc span{display:inline-flex;align-items:center}
#utiers{display:flex;gap:18px;align-items:flex-start;margin-top:8px;font-size:13px}
.ut{list-style:none;margin:0;padding:0;line-height:1.35}.ut .h{color:var(--dim);font-size:12px}
.ut .off{color:var(--dim);text-decoration:line-through}
.tc.rate{border-color:#555}.tc.off{opacity:.5}.tc.off b{text-decoration:line-through}
.jp{display:inline-block;margin-left:6px;padding:0 5px;border-radius:4px;background:#5a3fd0;color:#fff;font-size:10px;font-weight:700;letter-spacing:.04em;vertical-align:middle}
</style></head><body>
<header>
<h1>Filter report <small>__LEAGUE__ · <span id="meta"></span></small></h1>
<div class="tiers" id="tiers"></div>
<div id="utiers"></div>
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
<h2>Unique base EV <small>· [uniques.ev]: value of one unidentified drop = Σ drop chance × price</small></h2>
<p class="note">Drop chance = tier_weights[tier] / drop-anywhere uniques in that tier (unique_tiers.toml), shared among the uniques on the base.
Price = listing-weighted average of its poe.ninja variants; unlisted = 0. Blue "variable" = EV tier shown but the cheapest unique is junk (most drops worthless).</p>
<details id="uevd"><summary id="uevs"></summary>
<div class="bar"><input type="search" id="uq" placeholder="Search base or unique…"></div>
<table><thead><tr><th>Base (unID drop)</th><th class="num">EV</th><th>Tier</th><th class="num">Cheapest</th><th>Uniques: chance · price</th><th>Filter</th><th>Deciding rule</th></tr></thead><tbody id="ub"></tbody></table></details>
<h2>League content modules <small>· [content.*] in config.toml: uniques that only drop from one boss / encounter / instance</small></h2>
<p class="note">On: priced like any unique; a base the price rules would hide shows small + faded when one of its content uniques is in a shown unique tier, so a valuable encounter drop isn't missed.
Off: ignored on shared bases; a base with only that content's uniques stays blue. Label = how an unidentified drop on that base looks now.</p>
<div id="cm"></div>
<h2>Vendor recipes <small>· [vendor_recipes.*] in config.toml; tier = floor, a better price tier wins</small></h2>
<p class="note">Each recipe ingredient dropped as a rare with the recipe's flag (corrupted / mirrored). Label and rule = what the filter really does now; another rule may win before the recipe rule.</p>
<div id="vr"></div>
<h2>Hidden, worth a look <small id="revsub"></small></h2>
<p class="note">Items the filter hides even though poe.ninja prices them at or above the review line. Each one is either intended
(e.g. a base tiered by its cheapest unique) or something to fix in config.toml.</p>
<table id="rev"><thead><tr><th>Item</th><th>Category</th><th>Base</th><th class="num">Chaos</th><th class="num">Div</th><th class="num">Listings</th><th>Why hidden</th></tr></thead><tbody id="rb"></tbody></table>
<div id="rl"></div>
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
<th data-k="c" class="num" id="hc">Chaos</th><th data-k="c" class="num" id="hd">Div</th><th data-k="n" class="num">Listings</th>
<th data-k="shown">Filter</th><th data-k="rule">Deciding rule / note</th>
</tr></thead><tbody id="tb"></tbody></table></details></main>
<script>
const D=__DATA__, M=D.meta, R=D.rows, RULES=D.rules;
const BEAM={red:"#e33",yellow:"#ec3",blue:"#38f",white:"#eee",grey:"#999",brown:"#a63",pink:"#f6c",green:"#4c4",orange:"#f93",purple:"#a5f",cyan:"#3dd"};
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const CI=`<img class="cur" alt="c" title="Chaos Orb" src="__CHAOS__">`;
const DI=`<img class="cur" alt="div" title="Divine Orb" src="__DIVINE__">`;
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
 BaseEvasion:"evasion",BaseEnergyShield:"es",EnchantmentPassiveNum:"cluster_passives"
};
const BOOL_FIELDS={Corrupted:"corrupted",Mirrored:"mirrored",Identified:"identified",Foulborn:"foulborn",FracturedItem:"fractured"};
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
 readNumber(/^\s*Adds (\d+) Passive Skills/im,"cluster_passives");
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
 if(c.key==="EnchantmentPassiveNode")return null; // enchant text != node name: can't tell
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
{const frac=d=>d==null?"":d>=1?`${+d.toFixed(2)}${DI}`:`1/${Math.round(1/d)}${DI}`;
 const pts=[`<span class="tc rate"><span>1${DI}</span><i>=</i><span>${fmt(M.divine)}${CI}</span></span>`];
 M.tiers.forEach((t,i)=>{const nxt=M.tiers[i-1];
  const range=t.chaos>0?`≥ ${fmt(t.chaos)}${CI}`:nxt?`< ${fmt(nxt.chaos)}${CI}`:"any";
  const L=t.look||{};let st=L.fg?`color:${L.fg}`:"";if(L.bg)st+=`;background:${L.bg}`;if(L.bd)st+=`;border-color:${L.bd}`;
  pts.push(`<span class="tc tier${t.hidden?" off":""}" style="${st}" title="${t.hidden?"hidden":t.quiet?"quiet":"shown"}"><b>${esc(t.name)}</b><span>${range}</span><i>${t.chaos>0?frac(t.div):""}${t.hidden?" hidden":t.quiet?" quiet":""}</i></span>`)});
 $("tiers").innerHTML=pts.join("")}
{const U=M.unique_tiers||[],col=(on,title)=>`<ul class="ut"><li class="h">${title}</li>`+
  U.filter(t=>t.shown===on).map(t=>`<li class="${on?"":"off"}" title="${on?"":esc(t.why)}">${esc(t.name)}</li>`).join("")+`</ul>`;
 $("utiers").innerHTML=`<span class="note" title="[uniques] show.<tier> in config.toml; blue variable / jackpot bases always show">Unique tiers</span>`+
  col(true,"Shown")+col(false,"Hidden")}
$("meta").innerHTML=`built ${esc(M.when)} · ${DI} ${Math.round(M.divine)}${CI} · safety ${fmt(M.safety)}${CI} · jackpot ≥ ${M.jackpot}${DI}`;
$("hc").innerHTML=CI;$("hd").innerHTML=DI;
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
 $("stats").innerHTML=`<b>${rows.length}</b> items · <b>${sh}</b> shown · <b>${rows.length-sh}</b> hidden`+(risk?` · <span class="w"><b>${risk}</b> hidden worth ≥ ${fmt(M.safety)}${CI}</span>`:"");
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
const links=r=>(r.name.match(/\((\d)L\)$/)||[])[1];
$("revsub").innerHTML=`· ${rev.length} hidden items ≥ ${fmt(M.review)}${CI} (config [report] review_tier)`;
const revRow=r=>`<tr class="${r.risk?"risk":""}"><td>${label(r)}</td><td>${esc(r.cat)}</td><td>${esc(r.base)}</td>
<td class="num">${fmt(r.c)}</td><td class="num">${M.divine?fmt(r.c/M.divine):"–"}</td><td class="num">${r.n??"–"}</td>
<td><div class="rule">${esc(r.rule)} <span>:${r.line}</span></div>${r.note?`<div class="note">${esc(r.note)}</div>`:""}</td></tr>`;
const revMain=rev.filter(r=>!links(r));
$("rb").innerHTML=revMain.length?revMain.map(revRow).join("")
 :`<tr><td colspan="7" class="empty">Nothing ${rev.length?"unlinked ":""}priced ≥ ${fmt(M.review)}${CI} is hidden.</td></tr>`;
$("rl").innerHTML=["6","5"].map(n=>{const rs=rev.filter(r=>links(r)===n);if(!rs.length)return"";
 const risk=rs.filter(r=>r.risk).length;
 return `<details><summary>${n}L uniques · ${rs.length} hidden${risk?` · <span class="w">${risk} ≥ ${fmt(M.safety)}${CI}</span>`:""}</summary>
<table><thead><tr><th>Item</th><th>Category</th><th>Base</th><th class="num">Chaos</th><th class="num">Div</th><th class="num">Listings</th><th>Why hidden</th></tr></thead><tbody>${rs.map(revRow).join("")}</tbody></table></details>`}).join("");
{const state=b=>!b.shown?"Hidden":b.rule.includes("content override show")?"Faded":"Shown";
 $("cm").innerHTML=(D.content||[]).map(m=>{const n=s=>m.bases.filter(b=>state(b)===s).length;
  return `<details class="cm"><summary>${esc(m.mod)} <span class="v ${m.on?"s":"h"}">${m.on?"on":"off"}</span> <span class="note">· ${m.bases.length} bases · ${n("Shown")} shown · ${n("Faded")} faded · ${n("Hidden")} hidden · source contains ${esc(m.sources.join(", "))}</span></summary>
<table><thead><tr><th>Base (unID drop)</th><th>Uniques from this content</th><th>Filter</th><th>Deciding rule</th></tr></thead><tbody>`+
  m.bases.map(b=>`<tr class="${b.shown?"":"hid"}"><td>${label({name:b.base,look:b.look})}</td>
<td>${b.uniques.map(u=>`${esc(u.name)} <span class="note">${u.c==null?"unlisted":fmt(u.c)+CI}</span>`).join("<br>")}</td>
<td class="v ${b.shown?"s":"h"}">${state(b)}</td>
<td><div class="rule">${esc(b.rule)} <span>:${b.line}</span></div></td></tr>`).join("")+`</tbody></table></details>`}).join("")}
$("vr").innerHTML=(D.vendor||[]).map(v=>{const n=v.items.filter(i=>i.shown).length;
 return `<details class="cm"><summary>${esc(v.name)} <span class="v ${v.on?"s":"h"}">${v.on?"on":"off"}</span> <span class="note">· tier ${esc(v.tier)} · ${v.items.length} ingredients · ${n} shown · ${v.items.length-n} hidden</span></summary>
<p class="note">${v.needs.length?`Needs: ${esc(v.needs.join(" + "))} · `:""}Rarity: ${esc(v.rarity.join(", "))} · state: ${v.conds.length?esc(v.conds.join(" or ")):"any (unidentified / corrupted / split / mirrored all match)"}${v.note?` · ${esc(v.note)}`:""}</p>
<table><thead><tr><th>Ingredient</th><th>As</th><th>Filter</th><th>Deciding rule</th></tr></thead><tbody>`+
 v.items.map(i=>`<tr class="${i.shown?"":"hid"}"><td>${label({name:i.base,look:i.look})}</td><td>${esc(i.how)}</td>
<td class="v ${i.shown?"s":"h"}">${i.shown?"Shown":"Hidden"}</td>
<td><div class="rule">${esc(i.rule)} <span>:${i.line}</span></div></td></tr>`).join("")+`</tbody></table></details>`}).join("")
 ||`<p class="empty">No [vendor_recipes.*] in config.toml.</p>`;
{const U=D.uev||[],pct=p=>p>=0.01?(p*100).toFixed(0)+"%":p>=0.001?(p*100).toFixed(1)+"%":"<0.1%";
 $("uevs").innerHTML=`${U.length} bases · ${U.filter(u=>u.tier==="variable").length} variable · ${U.filter(u=>!u.shown).length} hidden`;
 const draw=()=>{const q=$("uq").value.toLowerCase();
  $("ub").innerHTML=U.filter(u=>!q||(u.base+" "+u.uniques.map(x=>x.name).join(" ")).toLowerCase().includes(q)).slice(0,1500).map(u=>
   `<tr class="${u.shown?"":"hid"}"><td>${label({name:u.base,look:u.look})}</td><td class="num">${fmt(u.ev)}${CI}</td><td>${esc(u.tier)}</td>
<td class="num">${u.cheapest==null?"–":fmt(u.cheapest)+CI}</td>
<td>${u.uniques.map(x=>`${esc(x.name)} <span class="note">T${x.t} · ${pct(x.p)} · ${x.c==null?"unlisted":fmt(x.c)+CI}</span>`).join("<br>")}</td>
<td class="v ${u.shown?"s":"h"}">${u.shown?"Shown":"Hidden"}</td>
<td><div class="rule">${esc(u.rule)} <span>:${u.line}</span></div></td></tr>`).join("")};
 $("uq").addEventListener("input",draw);draw()}
const unq=r=>["Unique","Foulborn","Replica"].includes(r.cat),lnk=r=>/\(\dL\)$/.test(r.name);
const checks=[
 {sev:"bad",t:`Hidden worth ≥ ${M.jackpot}${DI}`,rows:R.filter(r=>!r.nomap&&!r.shown&&r.jp),
  why:"The jackpot rule should never let these hide: bug in rules or config.",ok:`Nothing worth ≥ ${M.jackpot}${DI} is hidden.`},
 {t:"Linked uniques hidden",rows:R.filter(r=>r.risk&&unq(r)&&lnk(r)),
  why:`The price comes from the links, but the linked rule only fires at ≥ ${M.jackpot} div. Lower jackpot_divine to catch them, or accept.`},
 {t:"Chase uniques on hidden bases",rows:R.filter(r=>r.risk&&unq(r)&&!lnk(r)),
  why:"Unidentified, the filter only sees the base, and the cheapest unique on it is junk. Worth farming? Add the base to [unique_overrides] as \"variable\", or set uniques.variable_jackpot_only = false."},
 {t:"Crafting bases hidden with real volume",rows:R.filter(r=>r.risk&&r.cat==="Crafting base"&&(r.n||0)>=50),
  why:"This high-volume price meets the safety threshold but the item is hidden. Check the matching ilvl/influence rule."},
];
$("lk").innerHTML=checks.filter(k=>k.rows.length||k.ok).map(k=>!k.rows.length?`<li class="ok"><span class="t">✓ ${k.ok}</span></li>`:
 `<li class="${k.sev||""}"><div class="t"><b>${k.rows.length}</b> ${k.t}</div><div class="note">${esc(k.why)}</div><div class="ex">`+
 k.rows.slice(0,6).map(r=>`<span>${label(r)} ${fmt(r.c)}${CI}${r.base&&r.cat==="Crafting base"?` · ${esc(r.base)}`:""}${r.n?` · ${r.n} listed`:""}</span>`).join("")+
 (k.rows.length>6?`<span class="note">+${k.rows.length-6} more below</span>`:"")+`</div></li>`).join("");
</script></body></html>
"""
