"""Build a PoE1 loot filter where visibility is driven by poe.ninja prices.

Usage:  python build_filter.py [--refresh] [--league NAME]

Layout of the generated filter:
  defaults                  no borders, gear text colour (Continue blocks)
  rules/top.filter          hand-written (quest items, gold, 6L, ...)
  leveling                  NeverSink campaign rules from reference/, AreaLevel <= 67 only
  overrides                 config [overrides]
  exchange stackables       currency, cards, scarabs, ... (stack-size aware)
  uniques                   tiered by CHEAPEST unique on the base, + variable bases;
                            Foulborn priced separately (Foulborn True blocks, never hidden)
  crafting bases            ilvl / influence aware
  rules/bottom.filter       hand-written (maps, gems, hide gear, pink safety net)
"""
import argparse
import html
import json
import math
import re
import shutil
import sys
import time
import tomllib
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import report

ROOT = Path(__file__).resolve().parent
NINJA = "https://poe.ninja/poe1/api"
WIKI = "https://www.poewiki.net/w/api.php"
UA = {"User-Agent": "price-filter-builder/1.0 (personal loot filter script)"}

EXCHANGE_TYPES = [
    "Currency", "Fragment", "Scarab", "Essence", "Fossil", "Resonator", "Oil",
    "DeliriumOrb", "Tattoo", "Omen", "DivinationCard", "Artifact", "Runegraft",
    "AllflameEmber", "Astrolabe",
]
# Stash (listing-priced) types that are plain BaseType items, not uniques
STASH_STACKABLE_TYPES = ["Invitation", "Vial", "Wombgift"]
UNIQUE_TYPES = [
    "UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask",
    "UniqueJewel", "UniqueMap", "UniqueTincture",
]
# Unpriced stackable fallbacks: (classes, minimap shape)
CURRENCY_CLASSES = [
    (["Stackable Currency", "Delve Stackable Socketable Currency"], "Circle"),
    (["Map Fragments", "Misc Map Items"], "Hexagon"),
    (["Wombgifts"], "Moon"),
]
HIDDEN_STYLE = ["SetFontSize 18", "DisableDropSound True"]
# Minimap icon shape = item category, colour/size = price tier.
# Star only for uniques and tink (top tier); unknown / bases get Diamond.
SHAPE = {
    "Currency": "Circle", "DivinationCard": "Circle",
    "Fragment": "Hexagon", "Scarab": "Hexagon", "Invitation": "Hexagon",
    "Essence": "Moon", "Fossil": "Moon", "Resonator": "Moon", "Oil": "Moon",
    "DeliriumOrb": "Moon", "Tattoo": "Moon", "Omen": "Moon", "Artifact": "Moon",
    "Runegraft": "Moon", "AllflameEmber": "Moon", "Astrolabe": "Moon", "Vial": "Moon",
    "Wombgift": "Moon",
}
UNIQUE_SHAPE, BASE_SHAPE, MAP_SHAPE = "Star", "Diamond", "Square"
# Normal/magic/rare stuff that gets config gear_text_color instead of rarity colour
GEAR_CLASSES = [
    "Abyss Jewels", "Amulets", "Belts", "Body Armours", "Boots", "Bows", "Claws", "Daggers",
    "Gloves", "Blueprints", "Chart", "Heist Brooches", "Heist Cloaks",
    "Contracts", "Heist Gear", "Heist Tools", "Helmets", "Hybrid Flasks", "Idols", "Jewels",
    "Life Flasks", "Mana Flasks", "Maps", "One Hand Axes", "One Hand Maces", "One Hand Swords",
    "Quivers", "Rings", "Rune Daggers", "Sceptres", "Shields", "Staves", "Thrusting One Hand Swords",
    "Tinctures", "Two Hand Axes", "Two Hand Maces", "Two Hand Swords", "Utility Flasks", "Wands",
    "Warstaves", "Trinkets", "Fishing Rods",
]


# ---------------------------------------------------------------- fetching

def fetch_json(url, cache_file, max_age_min, refresh):
    if not refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age_min * 60:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def detect_league(cfg, args):
    if args.league:
        return args.league
    if cfg["league"] != "auto":
        return cfg["league"]
    data = fetch_json(f"{NINJA}/data/index-state", ROOT / "cache" / "index-state.json", 60, args.refresh)
    for lg in data["economyLeagues"]:
        name = lg["name"]
        if name in ("Standard", "Hardcore") or "Hardcore" in name or "SSF" in name or "Ruthless" in name:
            continue
        return name
    return "Standard"


def fetch_all(league, cfg, refresh):
    cache = ROOT / "cache" / league
    age = cfg["cache_minutes"]
    q = lambda t: urllib.parse.urlencode({"league": league, "type": t})
    out = {"exchange": {}, "stash": {}}
    for t in EXCHANGE_TYPES:
        out["exchange"][t] = fetch_json(f"{NINJA}/economy/exchange/current/overview?{q(t)}",
                                        cache / f"ex_{t}.json", age, refresh)
    for t in STASH_STACKABLE_TYPES + UNIQUE_TYPES + ["BaseType"]:
        out["stash"][t] = fetch_json(f"{NINJA}/economy/stash/current/item/overview?{q(t)}",
                                     cache / f"st_{t}.json", age, refresh)
    wiki = fetch_wiki_uniques(cfg, refresh)
    out["nomap"] = non_map_drops(wiki, cfg)
    out["wiki_bases"] = wiki_unique_bases(wiki)
    out["content"] = content_bases(wiki, cfg)
    out["drop_anywhere"] = {r["name"] for r in wiki if r["enabled"] and not r["restricted"]}
    return out


def fetch_wiki_uniques(cfg, refresh):
    """poewiki unique drop info (league independent): [{name, base, restricted, enabled, source}].
    One row per (name, base): a unique like Precursor's Emblem exists on several bases."""
    cache_file = ROOT / "cache" / "wiki_uniques.json"
    age = cfg["uniques"]["wiki_cache_days"] * 1440
    if not refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime < age * 60:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        if not rows or "base" in rows[0]:  # older cache has no base: refetch
            return rows
    rows = []
    try:
        while True:
            qs = urllib.parse.urlencode({
                "action": "cargoquery", "format": "json", "tables": "items", "limit": 500,
                "offset": len(rows), "where": 'rarity_id="unique"', "group_by": "name,base_item",
                "fields": "name,base_item,drop_enabled,is_drop_restricted,drop_monsters,drop_areas,drop_text"})
            req = urllib.request.Request(f"{WIKI}?{qs}", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                page = [x["title"] for x in json.loads(r.read().decode("utf-8"))["cargoquery"]]
            rows += [{"name": html.unescape(x["name"]), "base": html.unescape(x["base item"] or ""),
                      "restricted": x["is drop restricted"] == "1",
                      "enabled": x["drop enabled"] == "1",
                      "source": html.unescape(" | ".join(x[k] or "" for k in ("drop monsters", "drop areas", "drop text")))}
                     for x in page]
            if len(page) < 500:
                break
    except (OSError, KeyError, ValueError) as e:
        if cache_file.exists():
            print(f"poewiki fetch failed ({e}), using old cache", file=sys.stderr)
            return json.loads(cache_file.read_text(encoding="utf-8"))
        print(f"poewiki fetch failed ({e}), boss-only uniques NOT skipped", file=sys.stderr)
        return []
    cache_file.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def non_map_drops(rows, cfg):
    """name -> why it can't drop in a normal endgame map (boss / encounter / recipe only).
    These are left out of unique pricing: one boss-only chase unique must not make a junk
    base blue (Serpentine Staff: Cane of Kulemak vs 1c Sire of Shards)."""
    u = cfg["uniques"]
    if not u["skip_non_map_drops"]:
        return {}
    keep = [k.lower() for k in u["map_sources"]]
    out = {}
    for r in rows:
        if not r["enabled"]:
            out[r["name"]] = "no longer drops"
        elif r["restricted"] and not any(k in r["source"].lower() for k in keep):
            out[r["name"]] = r["source"].strip(" |") or "drop restricted (upgrade / recipe / encounter)"
    for name, drops in u.get("map_drop", {}).items():
        if drops:
            out.pop(name, None)
        else:
            out[name] = "config [uniques.map_drop]"
    return out


def wiki_unique_bases(rows):
    """base -> {unique names that can still drop on it} (wiki drop_enabled)."""
    out = {}
    for r in rows:
        if r["enabled"] and r.get("base"):
            out.setdefault(r["base"], set()).add(r["name"])
    return out


def content_bases(rows, cfg):
    """[content.<name>] modules, on or off -> {module: {base: {unique names}}}.
    Drop-restricted uniques whose wiki drop source contains one of the module's sources."""
    out = {}
    for mod, c in cfg.get("content", {}).items():
        keys = [k.lower() for k in c["sources"]]
        for r in rows:
            if r["enabled"] and r["restricted"] and r.get("base")                     and any(k in r["source"].lower() for k in keys):
                out.setdefault(mod, {}).setdefault(r["base"], set()).add(r["name"])
    return out


def no_map_drop(data, name):
    return (name[9:] if name.startswith("Foulborn ") else name) in data.get("nomap", {})


# ---------------------------------------------------------------- pricing

class Tiers:
    def __init__(self, cfg):
        # [(name, chaos)] highest first
        self.list = sorted(cfg["tiers"].items(), key=lambda kv: -kv[1])
        self.names = [n for n, _ in self.list]

    def of(self, chaos):
        for name, thr in self.list:
            if chaos >= thr:
                return name
        return "hide"

    def shown_floor(self, cfg):
        # cheapest chaos value that still gets shown
        return min((thr for n, thr in self.list if n not in cfg.get("hide_tiers", [])), default=math.inf)

    def rank(self, tier):
        # lower = better; variable best, hide worst
        order = ["variable"] + self.names + ["unknown", "hide"]
        return order.index(tier)


def apply_divine_tiers(cfg, divine_chaos):
    """tiers_follow_divine: a tier's `div` = fraction of the current divine price (top = 1 div).
    Rewrites cfg["tiers"] so every later reader sees the same numbers. Off or no divine
    price: the fixed `chaos` values stay."""
    if not cfg.get("tiers_follow_divine") or not divine_chaos:
        return
    for name, frac in cfg.get("tiers_divine", {}).items():
        cfg["tiers"][name] = round(frac * divine_chaos, 1)


def price_stackables(data, cfg, tiers):
    """name -> (chaos, ninja type). Exchange first, then listing-priced stackables."""
    ex = cfg["exchange"]
    shown_floor = tiers.shown_floor(cfg)
    prices = {}
    divine_chaos = None
    for t, d in data["exchange"].items():
        items = {i["id"]: i for i in d.get("items", [])}
        primary = d.get("core", {}).get("primary", "chaos")
        rates = d.get("core", {}).get("rates", {})
        if primary == "chaos" and rates.get("divine"):
            divine_chaos = 1 / rates["divine"]
        for line in d.get("lines", []):
            it = items.get(line["id"])
            if not it:
                continue
            value = line["primaryValue"]
            if primary != "chaos":  # never seen, but don't silently mis-tier
                continue
            # thin volume: trust it to show (safe), not to hide; hiding falls back to unpriced rules
            if line.get("volumePrimaryValue", 0) < ex["min_volume"] and value < shown_floor:
                continue
            prices[it["name"]] = (value, t)
    prices.setdefault("Chaos Orb", (1.0, "Currency"))
    if divine_chaos:
        prices["Divine Orb"] = (divine_chaos, "Currency")
    for t in STASH_STACKABLE_TYPES:
        for line in data["stash"][t].get("lines", []):
            if line.get("listingCount", 0) >= cfg["uniques"]["min_listings"]:
                prices.setdefault(line.get("baseType") or line["name"], (line["chaosValue"], t))
    for name, (whole, count) in ex.get("splinters", {}).items():
        if whole in prices:
            prices[name] = (prices[whole][0] / count, prices[whole][1])
    return prices, divine_chaos or 0


def jackpot_chaos(cfg, divine_chaos):
    """Any item worth this much is never hidden (config jackpot_divine)."""
    return cfg["jackpot_divine"] * divine_chaos if divine_chaos else math.inf


def never_hide_floor(cfg, jackpot):
    """Hidden unique base with any unique >= this goes "variable". Late league
    (uniques.variable_jackpot_only): only jackpots, not every never_hide_tier roll."""
    return jackpot if cfg["uniques"].get("variable_jackpot_only") else cfg["tiers"][cfg["uniques"]["never_hide_tier"]]


def small_loot(cfg):
    """[small_loot] wrist saver: (min tier's chaos, poe.ninja types) or None when off."""
    sl = cfg.get("small_loot", {})
    return (cfg["tiers"][sl["min_tier"]], set(sl.get("types", []))) if sl.get("enabled") else None


def min_shown_rank(cfg, tiers, min_tier):
    """Worst tier rank still shown for non-stackable loot: min_tier, or stricter small_loot."""
    rank = tiers.rank(min_tier)
    sl = small_loot(cfg)
    if sl:
        rank = min(rank, tiers.rank(tiers.of(sl[0])))
    return rank


def unique_drop_weights(data, cfg):
    """name -> relative drop weight of a drop-anywhere unique: its tier weight / number of
    drop-anywhere uniques in that tier (a drop picks a tier, then any unique in it evenly).
    Tiers from unique_tiers.toml, missing ones get [uniques.ev] default_tier."""
    ev = cfg["uniques"]["ev"]
    tier_of = {n: cfg["unique_tiers"].get(n, ev["default_tier"])
               for n in data.get("drop_anywhere", ()) if not no_map_drop(data, n)}
    count = {}
    for t in tier_of.values():
        count[t] = count.get(t, 0) + 1
    return {n: ev["tier_weights"][str(t)] / count[t] for n, t in tier_of.items()}


def price_unique_bases(data, cfg, tiers, divine_chaos):
    """base -> (tier, cheapest_chaos, best_chaos, best_name, ev_chaos or None).

    [uniques.ev] on: a base with drop-anywhere uniques is tiered by the expected value of one
    unidentified drop (drop weights x price, see unique_drop_weights). Below min_tier: hidden,
    even with a jackpot on it, unless in always_show_bases. Shown but its cheapest unique is
    below min_tier: "variable" (worth it on average, most drops are junk). The rest below.

    cheapest only from confident prices (>= min_listings), per unique its cheapest variant.
    best from any listing and the BEST variant: the variant can't be seen unidentified, so a
    jackpot roll (Voices 1 passive, Mageblood) makes the base worth checking. Linked lines
    are skipped above, so 6L prices never count.
    A base that would be hidden but has any unique >= never_hide_tier goes "variable".
    Boss / encounter-only uniques still drop, so they count for cheapest (a tier must hold
    for anything on the base) but never for best (no Cane of Kulemak -> blue Serpentine Staff).
    """
    u = cfg["uniques"]
    confident, any_listed = {}, {}  # (base, name) -> cheapest variant / best variant
    variants = {}  # (base, name) -> [sum chaos * listings, listings]: one unID drop, rolls by supply
    boss_only = set()  # bases with a boss / encounter-only unique
    seen, linked = set(), set()  # (base, name) on poe.ninja unlinked (any listing count) / linked
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            name, base = line["name"], line.get("baseType")
            if not base or name.startswith("Foulborn "):  # Foulborn: see price_foulborn_bases
                continue
            if line.get("links"):
                linked.add((base, name))  # Tabula Rasa only exists linked: priced, not unknown
                continue
            boss = no_map_drop(data, name)  # boss / encounter only, see non_map_drops
            if boss:
                boss_only.add(base)
            if name.startswith("Replica ") and not u["include_replicas"]:
                continue
            seen.add((base, name))
            listings = line.get("listingCount", 0)
            if listings < 1:
                continue
            key = (base, name)
            if not boss:
                any_listed[key] = max(any_listed.get(key, 0), line["chaosValue"])
                v = variants.setdefault(key, [0, 0])
                v[0] += line["chaosValue"] * listings
                v[1] += listings
            if listings >= u["min_listings"]:
                confident[key] = min(confident.get(key, math.inf), line["chaosValue"])

    cheap_by_base, best_by_base = {}, {}
    for (base, name), v in confident.items():
        cheap_by_base[base] = min(cheap_by_base.get(base, math.inf), v)
    for (base, name), v in any_listed.items():
        best_by_base[base] = max(best_by_base.get(base, (0, "")), (v, name))

    jackpot = jackpot_chaos(cfg, divine_chaos)
    min_rank = min_shown_rank(cfg, tiers, u["min_tier"])
    result = {}
    # uniques on a base with no confident poe.ninja price: thin listings, or not listed at all
    # although the wiki says they still drop (boss-only too: they drop, value unknown)
    unknown = {}
    # content-module uniques never count: their module shows them (small) while farming
    content = {n for by_base in data.get("content", {}).values() for ns in by_base.values() for n in ns}
    # boss / recipe / removed uniques (non_map_drops) never count: they can't be the drop
    for (base, name) in seen - confident.keys():
        if name not in content and not no_map_drop(data, name):
            unknown.setdefault(base, set()).add(name)
    for base, names in data.get("wiki_bases", {}).items():
        for name in names:
            if (base, name) not in seen | linked and name not in content and not no_map_drop(data, name) \
                    and not (name.startswith("Replica ") and not u["include_replicas"]):
                unknown.setdefault(base, set()).add(name)

    ev_by_base = {}  # base -> (ev, unpriced chase uniques, best non-pool unique)
    ev = u.get("ev", {})
    if ev.get("enabled"):
        weights = unique_drop_weights(data, cfg)
        pool = {}  # base -> drop-anywhere uniques on it, priced or not
        for base, name in seen | {(b, n) for b, ns in data.get("wiki_bases", {}).items() for n in ns}:
            if name in weights:
                pool.setdefault(base, set()).add(name)
        for base, names in pool.items():
            total = sum(weights[n] for n in names)
            value = sum(weights[n] * variants[(base, n)][0] / variants[(base, n)][1]
                        for n in names if (base, n) in variants)
            chase = sorted(n for n in names if (base, n) not in variants
                           and cfg["unique_tiers"].get(n, ev["default_tier"]) <= ev["unknown_chase_tier"])
            other = max(((v, n) for (b, n), v in any_listed.items() if b == base and n not in weights),
                        default=(0, ""))
            ev_by_base[base] = (value / total, chase, other)

    for base, (value, chase, other) in ev_by_base.items():
        cheapest = cheap_by_base.get(base)
        best = best_by_base.get(base, (0, ""))
        tier = tiers.of(value)
        if tiers.rank(tier) > min_rank:
            tier = "hide"
        elif cheapest is None or tiers.rank(tiers.of(cheapest)) > min_rank:
            tier = "variable"
        if hidden(cfg, tier) and other[0] >= jackpot:
            tier = "variable"  # league-content jackpot outside the drop pool
        if cfg.get("unknown_as_variable") and chase:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(chase))
        result[base] = (tier, cheapest, best[0], best[1], value)

    for base, cheapest in cheap_by_base.items():
        if base in ev_by_base:
            continue
        best = best_by_base.get(base, (0, ""))
        tier = tiers.of(cheapest)
        # known >= top tier stays a tink; only cheaper bases with a big unique go "variable"
        if best[0] >= jackpot and tier != tiers.names[0]:
            tier = "variable"
        if tiers.rank(tier) > min_rank:
            tier = "hide"
        if hidden(cfg, tier) and best[0] >= never_hide_floor(cfg, jackpot):
            tier = "variable"
        if cfg.get("unknown_as_variable") and base in unknown:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(sorted(unknown[base])))
        result[base] = (tier, cheapest, best[0], best[1], None)
    wiki_bases = data.get("wiki_bases", {})
    boss_only_bases = {
        base for base, names in wiki_bases.items()
        if names and all(no_map_drop(data, name) for name in names)
    }
    map_drop_bases = {
        base for base, names in wiki_bases.items()
        if any(not no_map_drop(data, name) for name in names)
    }
    boss_only_bases.update(boss_only - {b for b, _ in any_listed} - map_drop_bases)
    unique_map_bases = {
        line.get("baseType") for line in data["stash"].get("UniqueMap", {}).get("lines", [])
        if line.get("baseType")
    }
    boss_only_bases.difference_update(unique_map_bases)
    for base in boss_only_bases:
        result[base] = ("variable", None, 0, "boss / encounter-only uniques", None)
    for base in u.get("always_show_bases", []):
        if base in result and hidden(cfg, result[base][0]):
            result[base] = ("variable",) + result[base][1:]
    for base, tier in cfg.get("unique_overrides", {}).items():
        old = result.get(base, (None, 0, 0, "", None))
        result[base] = (tier,) + old[1:]
    return result


def price_foulborn_bases(data, cfg, tiers, divine_chaos):
    """base -> (tier, cheapest_chaos or None, best_chaos, best_label). Foulborn uniques only.

    Mutated mods vary per drop and the filter can't see them, so a base gets the cheapest
    variant of any confident Foulborn unique on it (listings summed over its variants).
    best = best variant with any listing. Below min_tier / small_loot: hidden, unless jackpot
    or never_hide_tier. No confident price: foulborn.unpriced.
    """
    f, u = cfg["foulborn"], cfg["uniques"]
    per = {}  # (base, name) -> [listings over all variants, cheapest variant, (best, label)]
    boss_only = set()
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            name, base = line["name"], line.get("baseType")
            if not name.startswith("Foulborn ") or not base or line.get("links"):
                continue
            boss = no_map_drop(data, name)  # counts for cheapest, never for best
            if boss:
                boss_only.add(base)
            listings = line.get("listingCount", 0)
            if listings < 1:
                continue
            e = per.setdefault((base, name), [0, math.inf, (0, ""), boss])
            e[0] += listings
            e[1] = min(e[1], line["chaosValue"])
            if not boss:
                label = name + (f" [{line['variant']}]" if line.get("variant") else "")
                e[2] = max(e[2], (line["chaosValue"], label))

    cheap_by_base, best_by_base = {}, {}
    map_bases = set()  # bases with a Foulborn unique that drops in maps
    unknown = {}  # base -> Foulborn uniques listed too thin to price
    for (base, name), (listings, cheapest, best, boss) in per.items():
        if listings >= f["min_listings"]:
            cheap_by_base[base] = min(cheap_by_base.get(base, math.inf), cheapest)
        else:
            unknown.setdefault(base, []).append(name)
        best_by_base[base] = max(best_by_base.get(base, (0, "")), best)
        if not boss:
            map_bases.add(base)

    jackpot = jackpot_chaos(cfg, divine_chaos)
    min_rank = min_shown_rank(cfg, tiers, f["min_tier"])
    result = {}
    for base, best in best_by_base.items():
        cheapest = cheap_by_base.get(base)
        tier = tiers.of(cheapest) if cheapest is not None else f["unpriced"]
        if best[0] >= jackpot and tier != tiers.names[0]:
            tier = "variable"
        if cheapest is not None and tiers.rank(tier) > min_rank:
            tier = "hide"
        if hidden(cfg, tier) and best[0] >= never_hide_floor(cfg, jackpot):
            tier = "variable"
        if cfg.get("unknown_as_variable") and cheapest is not None and base in unknown:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(sorted(unknown[base])))
        result[base] = (tier, cheapest, best[0], best[1])
    for base in boss_only - map_bases:
        result[base] = ("hide", None, 0, "boss / encounter-only uniques")
    return result


def price_linked_jackpots(data, cfg, divine_chaos):
    """links -> {bases}: a linked unique (5L/6L, any variant, Foulborn too) >= jackpot.
    Unlinked pricing skips linked lines, so without this a 5L jackpot on a junk base hides.
    Boss / encounter-only uniques are skipped as in the other unique pricing."""
    jackpot = jackpot_chaos(cfg, divine_chaos)
    out = {}
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            if line.get("links") and line.get("baseType") and line.get("listingCount", 0) >= 1 \
                    and line["chaosValue"] >= jackpot and not no_map_drop(data, line["name"]):
                out.setdefault(line["links"], set()).add(line["baseType"])
    return out


def price_crafting_bases(data, cfg, tiers, divine_chaos):
    """[(tier, ilvl_min, ilvl_max or None, influence or None, base, chaos)]

    Each poe.ninja entry covers its ilvl up to the next listed ilvl. Value at an ilvl is
    the cheapest price at that ilvl or any higher one (higher ilvl is never worth less),
    which kills outliers like a 445c ilvl82 base next to a 9c ilvl85 one.
    Exception: a confident entry worth >= jackpot is shown "variable" whatever the floor.
    """
    b = cfg["bases"]
    if not b["enabled"]:
        return []
    min_rank = tiers.rank(b["min_tier"])
    jackpot = jackpot_chaos(cfg, divine_chaos)
    by_base = {}  # (name, infl) -> [(ilvl, chaos, confident)]
    for line in data["stash"]["BaseType"].get("lines", []):
        infl = line.get("variant")
        if infl and "/" in infl and not b["include_dual_influence"]:
            continue
        confident = line.get("listingCount", 0) >= b["min_listings"] and line.get("count", 0) >= b["min_samples"]
        by_base.setdefault((line["name"], infl), []).append(
            (line.get("levelRequired", 0), line["chaosValue"], confident))

    out = []
    for (name, infl), entries in by_base.items():
        entries.sort(key=lambda e: -e[0])
        floor, upper = math.inf, None  # running min from higher ilvls; next ilvl above
        for ilvl, chaos, confident in entries:
            floor = min(floor, chaos)  # cheap evidence counts even if low confidence
            if confident:
                tier = tiers.of(floor)
                if tiers.rank(tier) <= min_rank:
                    out.append((tier, ilvl, upper - 1 if upper else None, infl, name, floor))
                elif chaos >= jackpot:
                    out.append(("variable", ilvl, upper - 1 if upper else None, infl, name, chaos))
            upper = ilvl
    return out


def reference_card_tiers(cfg, text):
    """card -> our tier, from the NeverSink divination tiers in reference/league.filter.
    Fallback for cards poe.ninja doesn't price (it only has exchange-traded cards)."""
    mapping = cfg["exchange"]["reference_card_tiers"]
    out = {}
    for blk in re.split(r"\n(?=(?:Show|Hide|Minimal)\b)", text):
        m = re.search(r"\$type->divination \$tier->(\S+)", blk.split("\n", 1)[0])
        if not m or m.group(1) not in mapping:
            continue
        for conds in re.findall(r"^\s*BaseType ==? (.*)$", blk, re.M):
            for name in re.findall(r'"([^"]+)"', conds):
                out.setdefault(name, mapping[m.group(1)])  # first (best) tier wins
    return out


def reference_currency_tiers(cfg, text):
    """currency name -> our tier, from NeverSink's currency tiers (t1 best .. t9) in
    reference/league.filter, by tier number. Fallback while poe.ninja has no confident
    price (league start). Stack-size blocks skipped; first (best) tier wins."""
    mapping = cfg["exchange"].get("reference_currency_tiers", {})
    out = {}
    for blk in re.split(r"\n(?=(?:Show|Hide|Minimal)\b)", text):
        m = re.search(r"\$type->currency\S* \$tier->t(\d+)", blk.split("\n", 1)[0])
        if not m or m.group(1) not in mapping or re.search(r"^\s*StackSize", blk, re.M):
            continue
        for conds in re.findall(r"^\s*BaseType == (.*)$", blk, re.M):
            for name in re.findall(r'"([^"]+)"', conds):
                out.setdefault(name, mapping[m.group(1)])
    return out


# ---------------------------------------------------------------- emitting

def q(names):
    return " ".join(f'"{n}"' for n in sorted(names))


def block(action, conds, style, comment=""):
    head = action + (f" # {comment}" if comment else "")
    return "\n".join([head] + [f"\t{c}" for c in conds] + [f"\t{s}" for s in style]) + "\n"


def hidden(cfg, tier):
    return tier == "hide" or tier in cfg.get("hide_tiers", [])


def style_for(cfg, tier, shape=BASE_SHAPE):
    if hidden(cfg, tier):
        return HIDDEN_STYLE
    lines = cfg["style"][tier]["lines"]
    if tier in cfg.get("quiet_tiers", []):
        # quiet style, but keep the tier's own font size
        lines = [l for l in lines if l.startswith("SetFontSize")] + cfg["style"]["quiet"]["lines"]
    if tier == max(cfg["tiers"], key=cfg["tiers"].get):
        shape = UNIQUE_SHAPE  # tink
    # MinimapIcon <size> <colour> <shape>: keep tier size/colour, swap shape
    return [" ".join(l.split()[:3] + [shape]) if l.startswith("MinimapIcon") else l for l in lines]


def action_for(cfg, tier):
    return "Hide" if hidden(cfg, tier) else "Show"


def section(title):
    bar = "#" + "=" * 78
    return f"\n{bar}\n# {title}\n{bar}\n\n"


def emit_defaults(cfg):
    # Continue blocks: style applies, later blocks can still override or hide
    out = section("Defaults: no borders, gear text colour (config.toml gear_text_color)")
    out += block("Show", [], ["SetBorderColor 0 0 0 0", "Continue"], "no borders unless a style sets one")
    # campaign ([leveling] on): gear keeps its rarity colour
    lv = cfg.get("leveling", {})
    camp = [f"AreaLevel > {lv.get('area_level_max', 67)}"] if lv.get("enabled") else []
    out += block("Show", ["Rarity <= Rare"] + camp + [f"Class == {q(GEAR_CLASSES)}"],
                 [f"SetTextColor {cfg['gear_text_color']}", "Continue"], "gear text colour, not rarity colour")
    if lv.get("enabled") and cfg.get("campaign_white_text_color"):
        out += block("Show", ["Rarity Normal", f"AreaLevel <= {lv.get('area_level_max', 67)}", f"Class == {q(GEAR_CLASSES)}"],
                     [f"SetTextColor {cfg['campaign_white_text_color']}", "Continue"], "campaign white gear: grey text")
    return out


def emit_overrides(cfg, prices):
    groups = {}
    for name, tier in cfg.get("overrides", {}).items():
        shape = SHAPE.get(prices.get(name, (0, None))[1], BASE_SHAPE)
        groups.setdefault((tier, shape), []).append(name)
    out = section("Overrides (config.toml [overrides])")
    for (tier, shape), names in groups.items():
        out += block(action_for(cfg, tier), [f"BaseType == {q(names)}"], style_for(cfg, tier, shape), f"override {tier}")
    return out


def emit_stackables(cfg, tiers, prices, ref_cards, ref_currency):
    ex = cfg["exchange"]
    overridden = set(cfg.get("overrides", {}))
    singles = {}   # (tier, shape) -> [names]
    stacks = {}    # (tier, n, shape) -> [names]
    for name, (v, t) in prices.items():
        if name in overridden or v <= 0:
            continue
        own, shape = tiers.of(v), SHAPE.get(t, BASE_SHAPE)
        sl = small_loot(cfg)
        if sl and t in sl[1] and v < sl[0]:
            singles.setdefault(("hide", shape), []).append(name)  # doesn't stack: wrist saver
            continue
        singles.setdefault((own, shape), []).append(name)
        # cheapest stack size that lifts it into each better tier
        max_stack = max(ex["max_stack"], ex.get("splinters", {}).get(name, [None, 0])[1])
        for tname, thr in tiers.list:
            if tiers.rank(tname) >= tiers.rank(own):
                continue
            need = math.ceil(thr / v - 1e-9)  # exact: stack value >= tier threshold
            if need <= max_stack:
                stacks.setdefault((tname, need, shape), []).append(name)

    out = section("Stackables (Currency Exchange prices)")
    for tname in tiers.names:
        for (t, n, shape), names in sorted(stacks.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if t == tname:
                out += block(action_for(cfg, t), [f"StackSize >= {n}", f"BaseType == {q(names)}"],
                             style_for(cfg, t, shape), f"{t} stack x{n}")
        for (t, shape), names in sorted(singles.items()):
            if t == tname:
                out += block(action_for(cfg, t), [f"BaseType == {q(names)}"], style_for(cfg, t, shape), t)
    hide = [n for (t, _), names in singles.items() if t == "hide" for n in names]
    if hide:
        out += block("Hide", [f"BaseType == {q(hide)}"], HIDDEN_STYLE, "priced below lowest tier")

    def fallback(classes, setting, label, shape):
        if setting == "hide":
            return block("Hide", [f"Class == {q(classes)}"], HIDDEN_STYLE, f"unpriced {label}")
        return block(action_for(cfg, setting), [f"Class == {q(classes)}"], style_for(cfg, setting, shape), f"unpriced {label}")

    def reference(ref, conds, label):
        # unpriced names at their NeverSink reference tier
        groups = {}
        for name, tier in ref.items():
            if name not in prices and name not in overridden:
                groups.setdefault(tier, []).append(name)
        return "".join(block(action_for(cfg, tier), conds + [f"BaseType == {q(groups[tier])}"],
                             style_for(cfg, tier, "Circle"), f"unpriced {label}, reference tier {tier}")
                       for tier in ["variable"] + tiers.names + ["unknown", "hide"] if groups.get(tier))

    if ex["unpriced_currency"] == "reference":
        out += reference(ref_currency, [], "currency")
    for classes, shape in CURRENCY_CLASSES:
        setting = "unknown" if ex["unpriced_currency"] == "reference" else ex["unpriced_currency"]
        out += fallback(classes, setting, classes[0].lower(), shape)
    if ex["unpriced_cards"] == "reference":
        out += reference(ref_cards, ['Class == "Divination Cards"'], "cards")
        out += fallback(["Divination Cards"], "unknown", "cards (not in reference either)", "Circle")
    else:
        out += fallback(["Divination Cards"], ex["unpriced_cards"], "cards", "Circle")
    return out


def emit_uniques(cfg, tiers, bases, fbases, linked, content, map_bases):
    out = section("Uniques (tier = EV of one unID drop, or cheapest unique without drop tiers; variable = gamble; 5L/6L jackpots)")
    # shown tiers first (Foulborn before normal), then corrupted-implicit rescue, then the
    # Foulborn catch-all (so no Foulborn reaches the hidden normal tiers), then hidden tiers
    order = ["variable"] + tiers.names + ["hide"]
    shown = [t for t in order if not hidden(cfg, t)]

    def tier_blocks(tier, by_base, conds, label):
        # unique maps get the map icon shape, everything else the unique star
        out = ""
        for shape, maps in ((MAP_SHAPE, True), (UNIQUE_SHAPE, False)):
            names = [b for b, (t, *_rest) in by_base.items() if t == tier and (b in map_bases) == maps]
            if names:
                out += block(action_for(cfg, tier), conds + [f"BaseType == {q(names)}"],
                             style_for(cfg, tier, shape), f"{label} {tier}" + (" maps" if maps else ""))
        return out

    def unpriced_blocks(setting, conds, label):
        return block(action_for(cfg, setting), conds + ['Class == "Maps"'], style_for(cfg, setting, MAP_SHAPE), label + " maps") + \
            block(action_for(cfg, setting), conds, style_for(cfg, setting, UNIQUE_SHAPE), label)

    foul = ["Rarity Unique", "Foulborn True"]
    if cfg["uniques"].get("hide_maps"):
        out += block("Hide", ["Rarity Unique", 'Class == "Maps"'], HIDDEN_STYLE, "unique maps (uniques.hide_maps)")
    for tier in shown:
        out += tier_blocks(tier, fbases, foul, "foulborn")
        out += tier_blocks(tier, bases, ["Rarity Unique"], "uniques")
    for links in sorted(linked, reverse=True):
        out += block("Show", ["Rarity Unique", f"LinkedSockets >= {links}", f"BaseType == {q(linked[links])}"],
                     style_for(cfg, "variable", UNIQUE_SHAPE), f"linked unique jackpot {links}L")
    out += emit_corrupted_uniques(cfg)
    for tier in order:
        if tier not in shown:
            out += tier_blocks(tier, fbases, foul, "foulborn")
    out += unpriced_blocks(cfg["foulborn"]["unpriced"], foul, "foulborn unpriced")
    out += emit_content(cfg, content)
    for tier in order:
        if tier not in shown:
            out += tier_blocks(tier, bases, ["Rarity Unique"], "uniques")
    out += unpriced_blocks(cfg["uniques"]["unpriced"], ["Rarity Unique"], "unpriced uniques")
    return out


def emit_content(cfg, content):
    """Content you farm ([content.<name>] on): its unique bases that would be hidden show
    small and silent, to loot after the fight. Shown tiers above still win."""
    out = ""
    for mod, by_base in sorted(content.items()):
        if not cfg["content"][mod].get("enabled"):
            continue
        names = ", ".join(sorted(n for ns in by_base.values() for n in ns))
        out += block("Show", ["Rarity Unique", f"BaseType == {q(by_base)}"],
                     cfg["style"]["content"]["lines"], f"content {mod}: {names}")
    return out


def emit_corrupted_uniques(cfg):
    c = cfg.get("corrupted_implicits", {})
    style = style_for(cfg, c.get("style", "variable"), UNIQUE_SHAPE)
    out = ""
    for cond in ([f"Class == {q(c['classes'])}"] if c.get("classes") else []) + \
                ([f"BaseType == {q(c['bases'])}"] if c.get("bases") else []):
        out += block("Show", ["Rarity Unique", "CorruptedMods >= 1", cond], style, "unique with corrupted implicit")
    return out


def emit_crafting_bases(cfg, tiers, entries):
    if not entries:
        return ""
    groups = {}
    for tier, lo, hi, infl, name, _ in entries:
        groups.setdefault((tier, lo, hi, infl), []).append(name)
    out = section("Crafting bases (poe.ninja base prices)")
    keys = sorted(groups, key=lambda k: (tiers.rank(k[0]), -k[1], k[3] or ""))
    unused = league_start_unused_whites(cfg)
    floor = tiers.rank(cfg["bases"].get("config_min_tier", cfg["bases"]["min_tier"]))
    for tier, lo, hi, infl in keys:
        if unused and tiers.rank(tier) > floor:
            out, unused = out + unused, ""
        # dual-influence entries use their first influence (matches any item having it)
        conds = ["Rarity <= Rare", "Corrupted False", f"ItemLevel >= {lo}"]
        if hi:
            conds.append(f"ItemLevel <= {hi}")
        conds += [f"HasInfluence {infl.split('/')[0] if infl else 'None'}",
                  f"BaseType == {q(groups[(tier, lo, hi, infl)])}"]
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        out += block(action_for(cfg, tier), conds, style_for(cfg, tier), f"base {tier} ilvl{span} {infl or 'plain'}")
    return out + unused


def league_start_unused_whites(cfg):
    """league_start + [leveling] build: white crafting bases the build never uses (the build
    module's Hide blocks without an AreaLevel upper limit, made Rarity Normal) stay hidden in maps.
    Goes after the bases at the configured bases.min_tier, so those still show."""
    lv = cfg.get("leveling", {})
    if not (cfg.get("league_start") and lv.get("build") and lv.get("league_start_hide_unused", True)):
        return ""
    text = (ROOT / "rules" / "leveling" / f"{lv['build']}.filter").read_text(encoding="utf-8")
    out = ""
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        lines = [l.strip() for l in blk.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        if not blk.startswith("Hide") or any(l.startswith("AreaLevel <") for l in lines):
            continue  # campaign-only hides (e.g. shields before the RF swap) stay campaign-only
        conds = [l for l in lines[1:] if not l.startswith(("Rarity", "AreaLevel", "Set", "Play", "Minimap", "Disable"))]
        name = lines[0].partition("#")[2].strip()
        out += block("Hide", ["Rarity Normal", f"AreaLevel > {lv.get('area_level_max', 67)}"] + conds,
                     HIDDEN_STYLE, f"league start, white: {name}")
    return out


# NeverSink sections copied for the campaign: (first section, section after it)
LEVELING_SECTIONS = [("2802", "2803"), ("5000", "5406")]  # [[3800]] currency: campaign_unhide instead
# Inventory cells per gear class, highest base size when a class varies (RePoE base_items)
CLASS_CELLS = {
    "Amulets": 1, "Rings": 1, "Jewels": 1, "Abyss Jewels": 1, "Belts": 2,
    "Life Flasks": 2, "Mana Flasks": 2, "Hybrid Flasks": 2, "Utility Flasks": 2, "Tinctures": 2,
    "Wands": 3, "Daggers": 3, "Rune Daggers": 3,
    "Claws": 4, "Thrusting One Hand Swords": 4, "Helmets": 4, "Boots": 4, "Gloves": 4,
    "One Hand Axes": 6, "One Hand Swords": 6, "One Hand Maces": 6, "Sceptres": 6,
    "Body Armours": 6, "Quivers": 6,
    "Bows": 8, "Staves": 8, "Warstaves": 8, "Two Hand Axes": 8, "Two Hand Swords": 8,
    "Two Hand Maces": 8, "Shields": 8,
}
# White gear hidden by [leveling] hide_normal_after (flasks / tinctures stay)
NORMAL_HIDE_CLASSES = [c for c in GEAR_CLASSES if "Flask" not in c and c not in (
    "Tinctures", "Maps", "Blueprints", "Contracts", "Heist Brooches", "Heist Cloaks", "Heist Gear", "Heist Tools")]
WEAPON_CLASSES = ["Bows", "Claws", "Daggers", "One Hand Axes", "One Hand Maces", "One Hand Swords",
                  "Quivers", "Rune Daggers", "Sceptres", "Staves", "Thrusting One Hand Swords",
                  "Two Hand Axes", "Two Hand Maces", "Two Hand Swords", "Wands", "Warstaves"]


def build_magic_weapons(text):
    """Weapon classes the build module Shows at magic rarity (rf: 2H axes / maces)."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        rarity = re.search(r"(?m)^\s*Rarity (.*)$", blk)
        cls = re.search(r"(?m)^\s*Class == (.*)$", blk)
        if blk.startswith("Show") and rarity and cls and ("Magic" in rarity.group(1) or "<= Rare" in rarity.group(1)):
            out += [c for c in re.findall(r'"([^"]+)"', cls.group(1)) if c in WEAPON_CLASSES and c not in out]
    return out


def campaign_unhide(cfg, text):
    """[leveling] show_all_stackables: in the campaign nothing stackable is hidden. Before
    every Hide block goes a campaign-only Show copy in the lowest tier's style; shown
    stackables keep their price tier style."""
    lv = cfg.get("leveling", {})
    if not (lv.get("enabled") and lv.get("show_all_stackables")):
        return text
    lowest = min(cfg["tiers"], key=cfg["tiers"].get)
    style = [f"\t{l}" for l in cfg["style"][lowest]["lines"]]
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        if blk.startswith("Hide"):
            lines = blk.rstrip("\n").splitlines()
            conds = [l for l in lines[1:] if not re.match(r"\s*(Set|Play|Minimap|Disable|Enable|Custom)", l)]
            head = "Show" + (lines[0][4:] if "#" in lines[0] else " #") + " (campaign: never hidden)"
            out.append("\n".join([head, f"\tAreaLevel <= {lv.get('area_level_max', 67)}"] + conds + style) + "\n\n")
        out.append(blk)
    return "".join(out)


GAME_TEXT_COLOR = {"Normal": "200 200 200 255", "Magic": "136 136 255 255", "Rare": "255 255 119 255"}
RARITIES = ["Normal", "Magic", "Rare", "Unique"]


def rarities_of(cond):
    """Rarities a "Rarity ..." condition allows: "Normal Magic", "<= Rare", "== Unique"."""
    m = re.match(r"\s*Rarity\s*(==|=|<=|>=|<|>)?\s*(.*)", cond)
    op, names = m.group(1) or "==", m.group(2).split()
    if op in ("==", "="):
        return set(names)
    i = RARITIES.index(names[0])
    return set({"<=": RARITIES[:i + 1], ">=": RARITIES[i:], "<": RARITIES[:i], ">": RARITIES[i + 1:]}[op])


def hidden_game_colours(text):
    """Hidden gear (Alt view) shows the game's rarity text colour, not gear_text_color from
    the defaults Continue block: each Hide block that can match normal/magic/rare gear gets
    a copy per rarity with SetTextColor, the original block stays last for everything else."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide|Minimal)\b)", text):
        all_lines = blk.splitlines(keepends=True)
        n = 1 + next((i for i, l in enumerate(all_lines[1:]) if not l[:1].isspace() or not l.strip()), len(all_lines) - 1)
        lines, tail = [l.rstrip("\n") for l in all_lines[:n]], "".join(all_lines[n:])
        if not blk.startswith("Hide") or any(l.strip() == "Continue" for l in lines):
            out.append(blk)
            continue
        cls = next((l for l in lines if re.match(r"\s*Class\b", l)), None)
        if cls and not any(n in g for n in re.findall(r'"([^"]+)"', cls) for g in GEAR_CLASSES):
            out.append(blk)
            continue
        rar = next((l for l in lines if re.match(r"\s*Rarity\b", l)), None)
        allowed = rarities_of(rar) if rar else set(RARITIES)
        split = [r for r in GAME_TEXT_COLOR if r in allowed]
        style_at = next((i for i, l in enumerate(lines) if i and re.match(r"\s*(Set|Play|Minimap|Disable|Enable|Custom)", l)),
                        len(lines))
        conds = [l for l in lines[1:style_at] if l is not rar]
        style = [l for l in lines[style_at:] if not re.match(r"\s*SetTextColor\b", l)]
        for r in split:
            out.append("\n".join([lines[0], f"\tRarity {r}"] + conds + style + [f"\tSetTextColor {GAME_TEXT_COLOR[r]}"]) + "\n")
        if not split or allowed - set(split):
            out.append("\n".join(lines) + "\n")
        out.append(tail)
    return "".join(out)


def campaign_only(text, area):
    """Adds "AreaLevel <= area" to every block that has no AreaLevel <= limit of its own."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        limits = [int(n) for n in re.findall(r"^\s*AreaLevel <= (\d+)", blk, re.M)]
        if re.match(r"(Show|Hide)\b", blk) and not any(n <= area for n in limits):
            head, _, rest = blk.partition("\n")
            blk = f"{head}\n\tAreaLevel <= {area}\n{rest}"
        out.append(blk)
    return "".join(out)


def emit_leveling(cfg, ref_text):
    """NeverSink's leveling rules from the reference filter, rebuilt at [leveling] strictness.

    The reference is a Very Strict FilterBlade export with leveling off, so blocks come
    commented out ("#Show # # %D4 ...") or as Hide. Tags: %D<n> = off at strictness >= n,
    %H<n> = Hide at strictness >= n. Other Hides are on-switched-off Shows, except the
    hide layers ("hidelayer" / "!utility_layer", optional magic blockers: strictness >= 3).
    Every block gets AreaLevel <= area_level_max, gear also Rarity <= Rare.
    """
    lv = cfg.get("leveling", {})
    if not lv.get("enabled"):
        return ""
    s, area = lv.get("strictness", 2), lv.get("area_level_max", 67)
    lines = ref_text.splitlines()
    heads = {}  # section number -> line index (last match: the first ones are the TOC)
    for i, l in enumerate(lines):
        m = re.match(r"#\s+\[\[?(\d{4})\]\]?", l)
        if m:
            heads[m.group(1)] = i

    build = lv.get("build")
    out = section(f"Leveling (build {build or 'none'}, NeverSink strictness {s}, AreaLevel <= {area} only)")
    if lv.get("show_jewellery"):
        out += block("Show", ["Rarity <= Rare", f"AreaLevel <= {area}", 'Class == "Amulets" "Belts" "Rings"'],
                     ["SetFontSize 40"], "jewellery, any rarity (show_jewellery)") + "\n"
    if lv.get("show_gems"):
        out += block("Show", [f"AreaLevel <= {area}", 'Class == "Skill Gems" "Support Gems"'],
                     ["SetFontSize 40", "SetTextColor 20 240 240"], "skill / support gems (show_gems)") + "\n"
    text = (ROOT / "rules" / "leveling" / f"{build}.filter").read_text(encoding="utf-8") if build else ""
    # magic gear after hide_magic_after: before vendor fodder and the build module, so only
    # flasks / tinctures, jewellery (show_jewellery) and the kept build weapons stay
    magic_after = lv.get("hide_magic_after")
    kept = build_magic_weapons(text) if lv.get("keep_build_weapons_magic", True) else []
    if magic_after is not None:
        out += block("Hide", ["Rarity Magic", f"AreaLevel > {magic_after}", f"AreaLevel <= {area}",
                              f"Class == {q([c for c in NORMAL_HIDE_CLASSES if c not in kept])}"],
                     HIDDEN_STYLE, f"magic gear after area {magic_after} (hide_magic_after)") + "\n"
    # vendor fodder (currency from the vendor): before the build module, so its Hides don't apply
    cells = lv.get("show_magic_rare_cells", 0)
    if cells:
        small = [c for c, n in CLASS_CELLS.items() if n <= cells]
        out += block("Show", ["Rarity Magic Rare", f"AreaLevel <= {area}", f"Class == {q(small)}"],
                     ["SetFontSize 40"], f"magic / rare, {cells} cells or less, to vendor (show_magic_rare_cells)") + "\n"
    normal_after = lv.get("hide_normal_after")
    if build:
        # "Show # whites": the white item types the build uses, shown until hide_normal_after
        text = re.sub(r"(?m)^(Show # whites.*)$", lambda m: f"{m.group(1)}\n\tAreaLevel <= {normal_after or 0}", text)
        out += campaign_only(text, area) + "\n"
    if magic_after is not None and kept:
        # kept build weapons: only what the build module Shows (rf: 2H axes until the RF swap)
        out += block("Hide", ["Rarity Magic", f"AreaLevel > {magic_after}", f"AreaLevel <= {area}", f"Class == {q(kept)}"],
                     HIDDEN_STYLE, "magic build weapons the module didn't show (keep_build_weapons_magic)") + "\n"
    if build or normal_after is not None:
        # build: every white gear piece its module didn't show; no build: from hide_normal_after on
        after = [] if build else [f"AreaLevel > {normal_after}"]
        out += block("Hide", ["Rarity Normal"] + after + [f"AreaLevel <= {area}", f"Class == {q(NORMAL_HIDE_CLASSES)}"],
                     HIDDEN_STYLE, "white gear (build whites / hide_normal_after)") + "\n"
    for first, after in LEVELING_SECTIONS:
        if first not in heads or after not in heads:
            print(f"Leveling: section [{first}] not found in reference/league.filter", file=sys.stderr)
            continue
        i, end = heads[first], heads[after]
        while i < end:
            m = re.match(r"(#?)(Show|Hide)\b\s*(.*)$", lines[i])
            i += 1
            if not m:
                continue
            commented, action, tag = m.group(1) == "#", m.group(2), m.group(3)
            body = []
            while i < end:
                l = lines[i][1:] if commented and lines[i].startswith("#") else lines[i]
                word = (l.split() or [""])[0]
                if not re.fullmatch(r"[A-Z][A-Za-z]+", word) or word in ("Show", "Hide"):
                    break
                body.append(l.strip())
                i += 1
            d, h = re.search(r"%D(\d)", tag), re.search(r"%H(\d)", tag)
            layer = "hidelayer" in tag or "!utility_layer" in tag
            if commented and ((d and s >= int(d.group(1))) or (layer and s < 3)):
                continue
            if h:
                action = "Hide" if s >= int(h.group(1)) else "Show"
            elif not layer:
                action = "Show"
            gated = any(int(n) <= area for n in re.findall(r"^AreaLevel <= (\d+)", "\n".join(body), re.M))
            conds = [] if gated else [f"AreaLevel <= {area}"]
            if not any(l.startswith("Rarity") or "Stackable Currency" in l for l in body):
                conds.append("Rarity <= Rare")
            body = [l for l in body if not l.startswith(("SetBorderColor", "SetBackgroundColor"))]
            name = re.sub(r"\s*%[DH]\d|^[#\s]+", "", tag).strip()
            out += block(action, conds + body, [], name) + "\n"
    return campaign_icon_sound(out, lv.get("icon_sound", "PlayAlertSound 2 300"))


def campaign_icon_sound(text, sound):
    """Campaign Show blocks with a minimap icon but no alert sound get [leveling] icon_sound."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        if blk.startswith("Show") and "MinimapIcon" in blk and "PlayAlertSound" not in blk:
            blk = re.sub(r"(?m)^\s*DisableDropSound True\n", "", blk)
            blk = re.sub(r"(?m)^(\s*)(MinimapIcon .*)$", lambda m: f"{m.group(1)}{sound}\n{m.group(1)}{m.group(2)}", blk, count=1)
        out.append(blk)
    return "".join(out)


# ---------------------------------------------------------------- main

def load_cfg():
    cfg = split_tiers(tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8")))
    raw = tomllib.loads((ROOT / "unique_tiers.toml").read_text(encoding="utf-8"))
    cfg["unique_tiers"] = {n: int(t) for t, names in raw.items() for n in names}
    return apply_league_start(cfg)


def split_tiers(cfg):
    """tiers.<name> = {div, chaos} -> cfg["tiers"] = {name: chaos}, cfg["tiers_divine"] = {name: div}."""
    raw = cfg["tiers"]
    cfg["tiers"] = {n: t["chaos"] for n, t in raw.items()}
    cfg["tiers_divine"] = {n: t["div"] for n, t in raw.items() if "div" in t}
    return cfg


def apply_league_start(cfg):
    """league_start = true: show (almost) everything, see config.toml."""
    if not cfg.get("league_start"):
        return cfg
    lowest = min(cfg["tiers"], key=cfg["tiers"].get)
    shown = lambda t: lowest if t == "hide" else t
    cfg["hide_tiers"] = []
    cfg.setdefault("small_loot", {})["enabled"] = False
    cfg["uniques"]["variable_jackpot_only"] = False
    cfg["bases"]["config_min_tier"] = cfg["bases"]["min_tier"]
    for sec in ("uniques", "foulborn", "bases"):
        cfg[sec]["min_tier"] = lowest
        if "unpriced" in cfg[sec]:
            cfg[sec]["unpriced"] = shown(cfg[sec]["unpriced"])
    cfg["uniques"]["hide_maps"] = False
    cfg["exchange"]["unpriced_currency"] = shown(cfg["exchange"]["unpriced_currency"])
    cfg["exchange"]["unpriced_cards"] = shown(cfg["exchange"]["unpriced_cards"])
    cfg["exchange"]["reference_card_tiers"] = {k: shown(t) for k, t in cfg["exchange"]["reference_card_tiers"].items()}
    cfg["overrides"] = {k: shown(t) for k, t in cfg.get("overrides", {}).items()}
    for mod in cfg.get("content", {}).values():
        mod["enabled"] = True
    cfg.setdefault("leveling", {})["enabled"] = True
    return cfg


def hand_rules(cfg, name):
    """rules/<name>.filter; league_start turns "Hide # league_start" blocks into Show."""
    text = (ROOT / "rules" / f"{name}.filter").read_text(encoding="utf-8")
    if cfg.get("league_start"):
        text = re.sub(r"^Hide(?= # league_start)", "Show", text, flags=re.M)
    return section(f"Hand-written {name} rules (rules/{name}.filter)") + text


def build_text(cfg, data, league):
    """Whole filter text + pricing results. No network, no file writes (tests use this)."""
    prices, divine = price_stackables(data, cfg, Tiers(cfg))
    apply_divine_tiers(cfg, divine)
    tiers = Tiers(cfg)
    ubases = price_unique_bases(data, cfg, tiers, divine)
    fbases = price_foulborn_bases(data, cfg, tiers, divine)
    linked = price_linked_jackpots(data, cfg, divine)
    cbases = price_crafting_bases(data, cfg, tiers, divine)
    ref_text = (ROOT / "reference/league.filter").read_text(encoding="utf-8")
    ref_cards = reference_card_tiers(cfg, ref_text)
    ref_currency = reference_currency_tiers(cfg, ref_text)

    header = (f"# Price filter - generated {datetime.now():%Y-%m-%d %H:%M}"
              + ("   LEAGUE START (almost nothing hidden)" if cfg.get("league_start") else "") + "\n"
              f"# League: {league}   Divine = {divine:.0f}c\n"
              f"# Tiers (chaos): " + ", ".join(f"{n}>={v}" for n, v in tiers.list) +
              f"   Jackpot (never hidden) >= {cfg['jackpot_divine']} div\n"
              f"# Do not edit - edit config.toml / rules/*.filter and rerun build_filter.py\n")
    text = "\n".join([
        header,
        emit_defaults(cfg),
        hand_rules(cfg, "top"),
        emit_leveling(cfg, ref_text),
        campaign_unhide(cfg, emit_overrides(cfg, prices)),
        campaign_unhide(cfg, emit_stackables(cfg, tiers, prices, ref_cards, ref_currency)),
        emit_uniques(cfg, tiers, ubases, fbases, linked, data.get("content", {}),
                     {l["baseType"] for l in data["stash"]["UniqueMap"].get("lines", []) if l.get("baseType")}),
        emit_crafting_bases(cfg, tiers, cbases),
        hand_rules(cfg, "bottom"),
    ])
    text = hidden_game_colours(text)
    return text, {"tiers": tiers, "prices": prices, "divine": divine, "ubases": ubases,
                  "fbases": fbases, "linked": linked, "cbases": cbases, "ref_cards": ref_cards,
            "ref_currency": ref_currency}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore price cache")
    ap.add_argument("--league", help="override league name")
    args = ap.parse_args()

    cfg = load_cfg()
    league = detect_league(cfg, args)
    print(f"League: {league}")
    data = fetch_all(league, cfg, args.refresh)
    text, r = build_text(cfg, data, league)
    tiers, prices, divine, ubases, cbases = r["tiers"], r["prices"], r["divine"], r["ubases"], r["cbases"]

    out_file = ROOT / "out" / f"{cfg['output_name']}.filter"
    out_file.parent.mkdir(exist_ok=True)
    out_file.write_text(text, encoding="utf-8")
    for d in cfg["output_dirs"]:
        dest = Path(d).expanduser()
        if dest.is_dir():
            shutil.copy(out_file, dest / out_file.name)
            print(f"Copied to {dest / out_file.name}")
        else:
            print(f"Skip missing output dir: {dest}", file=sys.stderr)

    # summary
    def count(tier_of):
        c = {}
        for t in tier_of:
            c[t] = c.get(t, 0) + 1
        return ", ".join(f"{k}:{v}" for k, v in sorted(c.items(), key=lambda kv: tiers.rank(kv[0])))
    print(f"Divine: {divine:.0f}c")
    print(f"Stackables priced: {len(prices)}  ({count(tiers.of(v) for v, _ in prices.values())})")
    print(f"Cards from reference tiers: {sum(1 for n in r['ref_cards'] if n not in prices)}")
    print(f"Currency from reference tiers: {sum(1 for n in r['ref_currency'] if n not in prices)}")
    print(f"Unique bases: {len(ubases)}  ({count(t for t, *_ in ubases.values())})")
    jack = sorted(((b, v) for b, v in ubases.items() if v[0] == 'variable'), key=lambda kv: -kv[1][2])
    print(f"Variable bases ({len(jack)}): " + ", ".join(
        f"{b} ({v[3]} {v[2] / divine:.1f}div" + (f", EV {v[4]:.1f}c)" if v[4] is not None else ")") for b, v in jack))
    gone = sorted(((b, v) for b, v in ubases.items() if v[0] == "hide" and v[4] is not None
                   and v[2] >= jackpot_chaos(cfg, divine)), key=lambda kv: -kv[1][2])
    print(f"Hidden by EV despite a jackpot ({len(gone)}): " + ", ".join(
        f"{b} ({v[3]} {v[2] / divine:.0f}div, EV {v[4]:.1f}c)" for b, v in gone))
    missing = sorted(n for n in data.get("drop_anywhere", ()) if n not in cfg["unique_tiers"])
    if cfg["uniques"].get("ev", {}).get("enabled") and missing:
        print(f"No drop tier in unique_tiers.toml (default_tier used): {', '.join(missing)}")
    print(f"Skipped boss / encounter-only uniques (wiki): {len(data.get('nomap', {}))}")
    for mod, by_base in data.get("content", {}).items():
        if cfg["content"][mod].get("enabled"):
            print(f"Content {mod} (small, silent): " + ", ".join(sorted(by_base)))
    print(f"Foulborn bases: {len(r['fbases'])}  ({count(t for t, *_ in r['fbases'].values())})")
    print(f"Crafting base rules: {len(cbases)} entries")
    print(f"Written: {out_file}")
    print(f"Report:  {report.write(cfg, data, text, r, league, ROOT / 'out' / 'report.html')}")


if __name__ == "__main__":
    main()
