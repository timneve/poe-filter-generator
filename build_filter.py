"""Build a PoE1 loot filter where visibility is driven by poe.ninja prices.

Usage:  python build_filter.py [--refresh] [--league NAME] [--config config_standard.toml]

Layout of the generated filter:
  defaults                  no borders, gear text colour (Continue blocks)
  rules/top.filter          hand-written (quest items, gold, 6L, ...)
  leveling                  build module + module leveling (campaign rules), AreaLevel <= 67 only
  overrides                 config [overrides]
  exchange stackables       currency, cards, scarabs, ... (stack-size aware)
  uniques                   tiered by CHEAPEST unique on the base, + variable bases;
                            Foulborn priced separately (Foulborn True blocks, never hidden)
  crafting bases            ilvl / influence aware
  rules/bottom.filter       hand-written (gems, hide gear, blue safety net)
"""
import argparse
import copy
import html
import json
import math
import re
import shutil
import sys
import time
import tomllib
import urllib.error
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
    "AllflameEmber", "Astrolabe", "Ducat", "EnshroudingCrystal", "DjinnCoin", "Thread",
]
# Stash (listing-priced) types that are plain BaseType items, not uniques
STASH_STACKABLE_TYPES = ["Invitation", "Vial", "Wombgift", "Corpse", "Incubator", "Memory"]
UNIQUE_TYPES = [
    "UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask",
    "UniqueJewel", "UniqueMap", "UniqueTincture", "UniqueRelic",
]
# Crafting-base feeds (base + ilvl, BaseType also influence): price_crafting_bases
BASE_TYPES = ["BaseType", "Flask"]
# Coven body parts (3.28 league mechanic, class "Viscera"): price_viscera_bases
VISCERA_TYPES = ["Viscera"]
# poe.ninja Viscera names carry a size prefix the filter can't see (same BaseType, same icon)
VISCERA_PREFIXES = ("Greater ", "Lesser ")
# Fetched but not priced here: tests/test_filter.py replays their valuable items through the
# filter (clusters = NeverSink eco tiers, gems / maps = hand rules, rest = blue safety net).
CHECK_TYPES = ["ClusterJewel", "SkillGem", "ForbiddenJewel", "ShrineBelt", "ScryingOrb",
               "IncursionTemple", "Map", "BlightedMap", "BlightRavagedMap", "ValdoMap"]
# Never fetched: not a ground drop
SKIPPED_TYPES = {"Beast": "captured with Bestiary nets, never a ground item",
                 "ImbuedGem": "Standard-only gem + imbued support, never a ground drop"}
# Every poe.ninja category must be in exactly one list above (ninja_categories warns at build)
NINJA_TYPES = (EXCHANGE_TYPES + STASH_STACKABLE_TYPES + UNIQUE_TYPES + BASE_TYPES + VISCERA_TYPES
               + CHECK_TYPES + list(SKIPPED_TYPES))
STASH_TYPES = STASH_STACKABLE_TYPES + UNIQUE_TYPES + BASE_TYPES + VISCERA_TYPES + CHECK_TYPES
# Unpriced stackable fallbacks: (classes, minimap shape)
CURRENCY_CLASSES = [
    (["Stackable Currency", "Delve Stackable Socketable Currency"], "Circle"),
    (["Map Fragments", "Misc Map Items"], "Hexagon"),
    (["Wombgifts"], "Moon"),
    (["Corpses"], "Moon"),  # league.filter [4106] restex: unpriced corpses shown (bottom.filter hides the rest)
]
HIDDEN_STYLE = ["SetFontSize 18", "DisableDropSound True"]
# Set*Color lines: a config [colors] name, or numbers (NeverSink copies: snapped to the palette)
COLOR_LINE = re.compile(r"^(\s*Set(?:Text|Border|Background)Color) +([a-z_]+|[\d ]+?) *$", re.M)
# palette entries that are never text (nearest-colour snapping for SetTextColor skips them)
NON_TEXT_COLORS = ("tink_bg", "content_bg", "clear", "brown_bg", "dust_bg")
# one filter block: Show / Hide line up to the next blank line or block start
BLOCK_RE = re.compile(r"^(?:Show|Hide)\b.*?(?=^[ \t]*$|^(?:Show|Hide)\b|\Z)", re.M | re.S)
# palette entries only used by name (snapping never picks them: imported whites stay white)
NAME_ONLY_COLORS = ("faded", "brown_dim", "dust", "variable_blue", "brown_bg", "dust_bg")
# rules/top.filter toggle sections: text used instead of the section when the toggle is off
TOGGLE_OFF = {}  # (gold: emit_gold)
# Divine price (chaos) assumed until poe.ninja's is known; tier thresholds are divine fractions.
FALLBACK_DIVINE = 150
# Minimap icon shape = item category, colour/size = price tier.
# Star only for uniques and tink (top tier); unknown / bases get Diamond.
SHAPE = {
    "Currency": "Circle", "DivinationCard": "Circle", "Essence": "Circle",
    "Fossil": "Circle", "Resonator": "Circle", "Oil": "Circle", "Artifact": "Circle",
    "Fragment": "Hexagon", "Scarab": "Hexagon", "Invitation": "Hexagon",
    "DeliriumOrb": "Circle", "Tattoo": "Moon", "Omen": "Moon",
    "Runegraft": "Moon", "AllflameEmber": "Moon", "Astrolabe": "Moon", "Vial": "Moon",
    "Wombgift": "Moon", "Ducat": "Moon", "EnshroudingCrystal": "Circle", "DjinnCoin": "Moon",
    "Corpse": "Moon", "Incubator": "Hexagon", "Memory": "Hexagon", "Thread": "Hexagon",
}
UNIQUE_SHAPE, BASE_SHAPE, MAP_SHAPE = "Star", "Diamond", "Square"
LEAGUE_SHAPE = "Moon"  # [league_mechanic]: new league content without a price
CLUSTER_SHAPE = "Pentagon"  # cluster jewels (poe.ninja prices + module eco tiers)
SPLINTER_SHAPE = "Kite"  # any name containing "Splinter" (breach, timeless, simulacrum, ritual...)
LIFEFORCE_SHAPE = "Moon"  # Harvest "... Crystallised Lifeforce" (poe.ninja type Currency, else Circle)
GEM_SHAPE = "Triangle"  # skill / support gems (price blocks, fallbacks, gem recipes, rules/top.filter)
GEM_CLASSES = {"Skill Gems", "Support Gems"}
PINNED_TOP_STACKABLES = {"Divine Orb", "Hinekora's Lock", "Mirror of Kalandra"}
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
# Endgame rare gear groups (NeverSink's rare hide layer classes): rares.weapons / armour / jewellery
RARE_GROUPS = {
    "weapons": ["Bows", "Claws", "Daggers", "One Hand Axes", "One Hand Maces", "One Hand Swords",
                "Quivers", "Rune Daggers", "Sceptres", "Staves", "Thrusting One Hand Swords",
                "Two Hand Axes", "Two Hand Maces", "Two Hand Swords", "Wands", "Warstaves"],
    "armour": ["Body Armours", "Boots", "Gloves", "Helmets", "Shields"],
    "jewellery": ["Amulets", "Belts", "Rings"],
}


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


def write_league_list(state, path, config_name):
    """poe.ninja index-state -> TOML list of league names (current / old) for picking `league`.
    Written by every build. PoE2 feeds mark unpriced leagues `indexed = false` -> `no_prices`."""
    def names(key, keep=lambda lg: True):
        return [lg["name"] for lg in state.get(key, []) if lg.get("name") and keep(lg)]
    groups = [("current", names("economyLeagues", lambda lg: lg.get("indexed", True))),
              ("no_prices", names("economyLeagues", lambda lg: not lg.get("indexed", True))),
              ("old", names("oldEconomyLeagues"))]
    lines = [f"# Generated from poe.ninja on every build ({datetime.now():%Y-%m-%d %H:%M}). Don't edit.",
             f"# League names you can put in {config_name} `league` (or \"auto\" = current softcore",
             "# trade league). current = poe.ninja has prices, no_prices = listed but not priced yet,",
             "# old = finished leagues.", ""]
    for key, group in groups:
        lines.append(f"{key} = [" + "".join(f"\n  {json.dumps(n, ensure_ascii=False)}," for n in group)
                     + ("\n]" if group else "]"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def detect_league(cfg, args):
    if args.league:
        return args.league
    try:
        data = fetch_json(f"{NINJA}/data/index-state", ROOT / "cache" / "index-state.json", 60, args.refresh)
    except OSError:
        if cfg["league"] != "auto":
            return cfg["league"]
        raise
    write_league_list(data, ROOT / "leagues.toml", "config.toml")
    if cfg["league"] != "auto":
        return cfg["league"]
    for lg in data["economyLeagues"]:
        name = lg["name"]
        if name in ("Standard", "Hardcore") or "Hardcore" in name or "SSF" in name or "Ruthless" in name:
            continue
        return name
    return "Standard"


def fetch_feed(url, cache_file, age, refresh, label):
    """fetch_json, but a feed poe.ninja dropped (HTTP 4xx, e.g. a category removed by a patch,
    like Scarab in the 2026-11-13 patch) -> warning + empty feed {} instead of a crashed build. Every reader
    uses .get("lines", []), so the category just prices nothing. Network down still raises."""
    try:
        return fetch_json(url, cache_file, age, refresh)
    except urllib.error.HTTPError as e:
        if not 400 <= e.code < 500:
            raise
        print(f"WARNING: poe.ninja feed {label} gone (HTTP {e.code}): priced as empty. "
              "If the category was removed from the game, drop it from build_filter.py",
              file=sys.stderr)
        return {}


def fetch_all(league, cfg, refresh):
    cache = ROOT / "cache" / league
    age = cfg["cache_minutes"]
    q = lambda t: urllib.parse.urlencode({"league": league, "type": t})
    out = {"exchange": {}, "stash": {}}
    for t in EXCHANGE_TYPES:
        out["exchange"][t] = fetch_feed(f"{NINJA}/economy/exchange/current/overview?{q(t)}",
                                        cache / f"ex_{t}.json", age, refresh, f"exchange {t}")
    for t in STASH_TYPES:
        out["stash"][t] = fetch_feed(f"{NINJA}/economy/stash/current/item/overview?{q(t)}",
                                     cache / f"st_{t}.json", age, refresh, f"stash {t}")
    wiki = released_wiki_rows(fetch_wiki_uniques(cfg, refresh))
    out["nomap"] = non_map_drops(wiki, cfg)
    out["wiki_bases"] = wiki_unique_bases(wiki)
    out["content"] = content_bases(wiki, cfg)
    out["drop_anywhere"] = {r["name"] for r in wiki if r["enabled"] and not r["restricted"]}
    return out


def ninja_categories(refresh):
    """poe.ninja's PoE1 economy sidebar types, scraped from its site scripts (cached a day).
    None when the page layout changed: the caller only warns."""
    cache = ROOT / "cache" / "ninja_categories.json"
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < 24 * 3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    get = lambda url: urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8")
    todo = re.findall(r"//assets\.poe\.ninja/_astro/([\w.-]+\.mjs)", get("https://poe.ninja/poe1/economy"))
    seen, types = set(), None
    while todo and len(seen) < 1000 and types is None:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        js = get(f"https://assets.poe.ninja/_astro/{name}")
        if "availableViews:[" in js and "type:`DivinationCard`" in js:
            types = sorted(set(re.findall(r"type:`(\w+)`,url:`", js)))
        todo += re.findall(r"\./(a\.[\w-]+\.mjs)", js)
    if types:
        cache.write_text(json.dumps(types), encoding="utf-8")
    return types


def check_ninja_categories(refresh):
    try:
        types = ninja_categories(refresh)
    except Exception as e:  # noqa: BLE001 - site scrape, never fatal
        print(f"WARNING: could not read poe.ninja category list: {e}", file=sys.stderr)
        return
    if types is None:
        print("WARNING: poe.ninja category list not found in its site scripts", file=sys.stderr)
        return
    new = sorted(set(types) - set(NINJA_TYPES))
    if new:
        print(f"WARNING: poe.ninja categories not handled by this filter: {', '.join(new)}. "
              "Add each to EXCHANGE/STASH_STACKABLE/UNIQUE/BASE/CHECK/SKIPPED_TYPES in build_filter.py",
              file=sys.stderr)
    gone = sorted(set(NINJA_TYPES) - set(types))
    if gone:
        print(f"WARNING: categories no longer on poe.ninja: {', '.join(gone)}. "
              "Removed from the game? Drop them from build_filter.py (see docs/ai/RECIPES.md)",
              file=sys.stderr)


def fetch_wiki_uniques(cfg, refresh):
    """poewiki unique drop info (league independent): [{name, base, restricted, enabled, source,
    released}]. One row per (name, base): a unique like Precursor's Emblem exists on several bases.
    released = release date of the unique's wiki release_version ("" unknown), see released_wiki_rows."""
    cache_file = ROOT / "cache" / "wiki_uniques.json"
    age = cfg["uniques"]["wiki_cache_days"] * 1440
    if not refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime < age * 60:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        if not rows or "released" in rows[0]:  # older cache has no release date: refetch
            return rows
    rows = []
    try:
        dates, seen = {}, 0
        while True:  # > 500 versions: page through
            qs = urllib.parse.urlencode({"action": "cargoquery", "format": "json", "tables": "versions",
                                         "limit": 500, "offset": seen, "fields": "version,release_date"})
            with urllib.request.urlopen(urllib.request.Request(f"{WIKI}?{qs}", headers=UA), timeout=30) as r:
                page = [x["title"] for x in json.loads(r.read().decode("utf-8"))["cargoquery"]]
            dates.update({x["version"]: (x["release date"] or "")[:10] for x in page})
            seen += len(page)
            if len(page) < 500:
                break
        while True:
            qs = urllib.parse.urlencode({
                "action": "cargoquery", "format": "json", "tables": "items", "limit": 500,
                "offset": len(rows), "where": 'rarity_id="unique"', "group_by": "name,base_item",
                "fields": "name,base_item,drop_enabled,is_drop_restricted,drop_monsters,drop_areas,drop_text,release_version"})
            req = urllib.request.Request(f"{WIKI}?{qs}", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                page = [x["title"] for x in json.loads(r.read().decode("utf-8"))["cargoquery"]]
            rows += [{"name": html.unescape(x["name"]), "base": html.unescape(x["base item"] or ""),
                      "restricted": x["is drop restricted"] == "1",
                      "enabled": x["drop enabled"] == "1",
                      "source": html.unescape(" | ".join(x[k] or "" for k in ("drop monsters", "drop areas", "drop text"))),
                      "released": dates.get(x["release version"] or "", "")}
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


def released_wiki_rows(rows, today=None):
    """Wiki rows whose patch is out: release date before today (UTC). The wiki adds next league's
    uniques days early; their new base (Putrid Seed on "Mycelium Core", 3.30) is unknown to the
    game client until launch and one unknown BaseType makes the game reject the whole filter.
    Launch day itself counts as unreleased (patch time unknown): rebuild the day after."""
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    return [r for r in rows if r.get("released", "") < today]


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
        elif r["name"].startswith("Replica "):  # Heist Curio Displays only (wiki flag sometimes missing)
            out[r["name"]] = "Replica: Heist only"
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
    Drop-restricted uniques whose wiki drop source contains one of the module's sources.
    Case-sensitive: "Blight" must not hit Brinerot's "Metadata/Monsters/Wb/WbLightning...";
    "Ultimatum" still hits "LeagueUltimatum"."""
    out = {}
    for mod, c in cfg.get("content", {}).items():
        keys = c["sources"]
        for r in rows:
            if r["enabled"] and r["restricted"] and r.get("base") \
                    and any(k in r["source"] for k in keys):
                out.setdefault(mod, {}).setdefault(r["base"], set()).add(r["name"])
    return out


WOMBGIFTS = ["Ancient Wombgift", "Lavish Wombgift", "Mysterious Wombgift", "Provisioning Wombgift"]


def apply_wombgift_choices(cfg):
    """[content.breach.wombgifts] name = "price" | "hide" | tier name -> merged into a copy of
    [overrides] (an explicit [overrides] entry wins). Not tied to [content.breach] enabled."""
    choices = cfg.get("content", {}).get("breach", {}).get("wombgifts", {})
    unknown = set(choices) - set(WOMBGIFTS)
    if unknown:
        raise ValueError(f"Unknown [content.breach.wombgifts] name(s): {', '.join(sorted(unknown))}")
    valid = {"price", "hide", "variable", "unknown", *cfg["tiers"]}
    bad = {n: v for n, v in choices.items() if v not in valid}
    if bad:
        raise ValueError(f"[content.breach.wombgifts] values must be \"price\", \"hide\" or a tier name: {bad}")
    picked = {n: v for n, v in choices.items() if v != "price"}
    if not picked:
        return cfg
    cfg = dict(cfg)
    cfg["overrides"] = {**picked, **cfg.get("overrides", {})}
    return cfg


def content_policy(content, cfg):
    """Resolve enabled content uniques to price, always-show, always-hide and rescue base sets.
    Default / "price": priced normally, and rescue: base shown in [style.content] if price hides it
    but the content unique itself is in a shown tier (valuable_content_bases).
    true: priced too, faded show before every other rule when price hides it. false: base hidden."""
    price_names, show, hide, rescue = set(), {}, {}, {}
    all_names = set()
    for mod, by_base in content.items():
        names = {name for base_names in by_base.values() for name in base_names}
        all_names.update(names)
        settings = cfg.get("content", {}).get(mod, {})
        overrides = settings.get("drops", {})
        unknown = set(overrides) - names
        if unknown:
            raise ValueError(f"Unknown [content.{mod}.drops] unique name(s): {', '.join(sorted(unknown))}")
        if any(not isinstance(value, bool) and value != "price" for value in overrides.values()):
            raise ValueError(
                f"[content.{mod}.drops] values must be true (always show), false (always hide), or \"price\""
            )
        if not settings.get("enabled"):
            continue
        for base, base_names in by_base.items():
            for name in base_names:
                mode = overrides.get(name)
                if mode is not False:
                    price_names.add(name)
                if mode is None or mode == "price":
                    rescue.setdefault(base, set()).add(name)
                else:
                    target = show if mode else hide
                    target.setdefault(base, set()).add(name)
    conflicts = set(show) & set(hide)
    if conflicts:
        raise ValueError(f"Conflicting content drop overrides on shared base(s): {', '.join(sorted(conflicts))}")
    return {"price_names": price_names, "excluded_names": all_names - price_names,
            "show": show, "hide": hide, "rescue": rescue}


def no_map_drop(data, name):
    return (name[9:] if name.startswith("Foulborn ") else name) in data.get("nomap", {})


# ---------------------------------------------------------------- pricing

class Tiers:
    def __init__(self, cfg):
        # [(name, chaos)] highest first
        self.list = sorted(cfg["tiers"].items(), key=lambda kv: -kv[1])
        self.names = [n for n, _ in self.list]
        # variable (blue) sits right after `variable_after` (default minor): top..minor beat it
        after = cfg.get("variable_after", "minor")
        cut = self.names.index(after) + 1 if after in self.names else 0
        self.order = self.names[:cut] + ["variable"] + self.names[cut:] + ["unknown", "hide"]

    def of(self, chaos):
        for name, thr in self.list:
            if chaos >= thr:
                return name
        return "hide"

    def shown_floor(self, cfg):
        # cheapest chaos value that still gets shown
        return min((thr for n, thr in self.list if n not in cfg.get("hide_tiers", [])), default=math.inf)

    def rank(self, tier):
        # lower = better; hide worst
        return self.order.index(tier)


def exchange_divine(data):
    """Divine price in chaos from the (chaos-primary) exchange feeds, or None."""
    for d in data["exchange"].values():
        core = d.get("core", {})
        if core.get("primary", "chaos") == "chaos" and core.get("rates", {}).get("divine"):
            return 1 / core["rates"]["divine"]
    return None


def apply_divine_tiers(cfg, divine_chaos):
    """Tier threshold = its `tiers_divine` fraction x the current divine price (top = 1 div).
    Rewrites cfg["tiers"] (chaos) so every later reader sees the same numbers. No divine price,
    or tests setting tiers_follow_divine = false: cfg["tiers"] stays as it is."""
    if not cfg.get("tiers_follow_divine", True) or not divine_chaos:
        return
    for name, frac in cfg.get("tiers_divine", {}).items():
        cfg["tiers"][name] = round(frac * divine_chaos, 3)


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
            volume = line.get("volumePrimaryValue", 0)
            # cards: active quote prices the card; thin -> NeverSink group (emit_stackables).
            # [exchange.card_rewards] reward price overrides the quote below.
            if t == "DivinationCard":
                if volume >= ex["card_fallback_min_volume"]:
                    prices[it["name"]] = (value, t)
                continue
            # thin volume: trust it to show (safe), not to hide; hiding falls back to unpriced rules
            if volume < ex["min_volume"] and value < shown_floor:
                continue
            prices[it["name"]] = (value, t)
    prices.setdefault("Chaos Orb", (1.0, "Currency"))
    if divine_chaos:
        prices["Divine Orb"] = (divine_chaos, "Currency")
    for t in STASH_STACKABLE_TYPES:
        for line in data["stash"][t].get("lines", []):
            listings = line.get("listingCount", 0)
            # thin listings: trust it to show (safe), not to hide, as for the exchange above
            if listings >= cfg["uniques"]["min_listings"] or listings and line["chaosValue"] >= shown_floor:
                prices.setdefault(line.get("baseType") or line["name"], (line["chaosValue"], t))
    for name, (whole, count) in ex.get("splinters", {}).items():
        prices.pop(name, None)
        if whole in prices:
            prices[name] = (prices[whole][0] / count, prices[whole][1])
    exact_item_prices = {}
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            listings = line.get("listingCount", 0)
            # card rewards are unlinked: a 5/6-link line (often a troll listing) must not price the card
            if listings < cfg["uniques"]["min_listings"] or line.get("links"):
                continue
            name = line["name"]
            total, count = exact_item_prices.get(name, (0.0, 0))
            exact_item_prices[name] = (total + line["chaosValue"] * listings, count + listings)
    exact_item_prices = {name: total / count for name, (total, count) in exact_item_prices.items()}
    pending_rewards = dict(ex.get("card_rewards", {}))
    wait_chain = True  # reward = another reward card: wait for its reward price, not its quote
    while pending_rewards:
        resolved = []
        for name, (reward, quantity, set_size) in pending_rewards.items():
            if quantity <= 0 or set_size <= 0:
                raise ValueError(f"Invalid card reward for {name}: {quantity} / {set_size}")
            if wait_chain and reward in pending_rewards:
                continue
            reward_price = prices.get(reward)
            reward_value = reward_price[0] if reward_price else exact_item_prices.get(reward)
            if reward_value and reward_value > 0:
                prices[name] = (reward_value * quantity / set_size, "DivinationCard")
                resolved.append(name)
        if not resolved:
            if not wait_chain:
                break
            wait_chain = False  # chain end unresolvable: its card quote may price the chain
            continue
        wait_chain = True
        for name in resolved:
            del pending_rewards[name]
    return prices, divine_chaos or 0


def card_trade_volumes(data):
    """Best available poe.ninja exchange volume per card, in primary-currency value."""
    exchange = data["exchange"].get("DivinationCard", {})
    items = {item["id"]: item["name"] for item in exchange.get("items", [])}
    volumes = {}
    for line in exchange.get("lines", []):
        name = items.get(line["id"])
        if name:
            volumes[name] = max(volumes.get(name, 0), line.get("volumePrimaryValue", 0))
    return volumes


def jackpot_chaos(cfg, divine_chaos):
    """Any item worth this much is never hidden (config jackpot_divine)."""
    return cfg["jackpot_divine"] * divine_chaos if divine_chaos else math.inf


def never_hidden(cfg, tiers, tier):
    """Confident (non-variable) price tier at or above [uniques] never_hide_tier: no show toggle /
    min_tier / small_loot hides it. Variable groups (cheap base, pricey roll) use jackpot_divine."""
    return tier in tiers.names and tier != "variable"         and tiers.rank(tier) <= tiers.rank(cfg["uniques"]["never_hide_tier"])


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


def shown_unique_tiers(cfg, tiers):
    """Price tiers [uniques.show] turns on, minus those below a stricter small_loot."""
    sl = small_loot(cfg)
    floor = tiers.rank(tiers.of(sl[0])) if sl else math.inf
    return {t for t in tiers.names if cfg["uniques"]["show"].get(t) and tiers.rank(t) <= floor}


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


def unique_vendor_values(cfg, prices):
    """unique name -> chaos it vendors for: [vendor_recipes.*] entries with `uniques` (enabled),
    reward stackable price x reward_count (Harbinger uniques -> Fracturing Shard). A recipe whose
    reward has no price adds nothing."""
    out = {}
    for rec in cfg.get("vendor_recipes", {}).values():
        if not rec.get("enabled") or not rec.get("uniques"):
            continue
        reward = prices.get(rec["reward"])
        if not reward:
            continue
        value = reward[0] * rec.get("reward_count", 1)
        for n in rec["uniques"]:
            out[n] = max(out.get(n, 0), value)
    return out


def price_unique_bases(data, cfg, tiers, divine_chaos, ev_detail=None, vendor=None):
    """base -> (tier, cheapest_chaos, best_chaos, best_name, ev_chaos or None).
    vendor (unique_vendor_values): name -> guaranteed vendor value. Each of its poe.ninja
    variants counts at least that much (cheapest, best, EV); unlisted / thin it counts as a
    confident price of exactly that (never unknown).
    ev_detail (dict, optional) gets base -> [(name, drop share 0..1, avg chaos or None, drop tier)]
    for the report: what each unique on the base adds to the EV.

    [uniques.ev] on: a base with drop-anywhere uniques is tiered by the expected value of one
    unidentified drop (drop weights x price, see unique_drop_weights). Tier toggled off in
    [uniques.show]: hidden, unless in always_show_bases or a unique on it >= jackpot_divine
    (then "variable", like the cheapest path). A tier >= never_hide_tier is never toggled off. Shown but
    its cheapest unique's tier is off: "variable" (worth it on average, most drops are junk).
    The rest below.

    Tier = [uniques] base_price ("lowest" default / "highest") confident unique on the base.
    cheapest only from confident prices (>= min_listings), per unique its cheapest variant.
    best from any listing and the BEST variant: the variant can't be seen unidentified, so a
    jackpot roll (Voices 1 passive, Mageblood) makes the base worth checking. Linked lines
    are skipped above, so 6L prices never count.
    A base that would be hidden but has any unique >= jackpot_divine goes "variable"; a base
    priced >= never_hide_tier is never hidden (never_hidden).
    Boss / encounter-only uniques (can't drop in a map) count for neither cheapest nor best;
    enabled content modules instead price their restricted uniques normally.
    """
    u = cfg["uniques"]
    vendor = vendor or {}
    content = content_policy(data.get("content", {}), cfg)
    content_prices = content["price_names"]
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
            boss = no_map_drop(data, name) and name not in content_prices
            if boss:
                boss_only.add(base)
            if name.startswith("Replica ") and not u["include_replicas"]:
                continue
            seen.add((base, name))
            listings = line.get("listingCount", 0)
            if listings < 1:
                continue
            key = (base, name)
            chaos = max(line["chaosValue"], vendor.get(name, 0))
            if not boss:
                any_listed[key] = max(any_listed.get(key, 0), chaos)
                v = variants.setdefault(key, [0, 0])
                v[0] += chaos * listings
                v[1] += listings
            if listings >= u["min_listings"] and name not in content["excluded_names"] and not boss:
                confident[key] = min(confident.get(key, math.inf), chaos)
    # vendor value known: thin / unlisted ones are worth exactly that
    for base, name in seen | {(b, n) for b, ns in data.get("wiki_bases", {}).items() for n in ns}:
        if name in vendor and name not in content["excluded_names"]                 and (not no_map_drop(data, name) or name in content_prices):
            key = (base, name)
            confident.setdefault(key, vendor[name])
            any_listed.setdefault(key, vendor[name])
            variants.setdefault(key, [vendor[name], 1])

    mode = u.get("base_price", "lowest")
    if mode not in ("lowest", "highest"):
        raise ValueError(f'[uniques] base_price must be "lowest" or "highest", got {mode!r}')
    pick = min if mode == "lowest" else max
    cheap_by_base, priced_by_base, best_by_base = {}, {}, {}
    for (base, name), v in confident.items():
        cheap_by_base[base] = min(cheap_by_base.get(base, math.inf), v)
        priced_by_base[base] = pick(priced_by_base.get(base, v), v)
    for (base, name), v in any_listed.items():
        best_by_base[base] = max(best_by_base.get(base, (0, "")), (v, name))

    jackpot = jackpot_chaos(cfg, divine_chaos)
    shown = shown_unique_tiers(cfg, tiers)
    off = lambda t: t == "hide" or (t in tiers.names and t not in shown and not never_hidden(cfg, tiers, t))
    result = {}
    # uniques on a base with no confident poe.ninja price: thin listings, or not listed at all
    # although the wiki says they still drop (boss-only too: they drop, value unknown)
    unknown = {}
    # Disabled modules and explicit overrides do not enter normal price/unknown handling.
    excluded_content = content["excluded_names"]
    # boss / recipe / removed uniques (non_map_drops) never count: they can't be the drop
    for (base, name) in seen - confident.keys():
        if name not in excluded_content and (not no_map_drop(data, name) or name in content_prices):
            unknown.setdefault(base, set()).add(name)
    for base, names in data.get("wiki_bases", {}).items():
        for name in names:
            if (base, name) not in seen | linked | confident.keys() and name not in excluded_content \
                    and (not no_map_drop(data, name) or name in content_prices) \
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
            if ev_detail is not None:
                ev_detail[base] = sorted(
                    ((n, weights[n] / total,
                      variants[(base, n)][0] / variants[(base, n)][1] if (base, n) in variants else None,
                      cfg["unique_tiers"].get(n, ev["default_tier"])) for n in names),
                    key=lambda x: -x[1])

    for base, (value, chase, other) in ev_by_base.items():
        cheapest = cheap_by_base.get(base)
        best = best_by_base.get(base, (0, ""))
        tier = tiers.of(value)
        if off(tier):
            tier = "hide"
        elif cheapest is None or off(tiers.of(cheapest)):
            tier = "variable"
        if hidden(cfg, tier) and max(best[0], other[0]) >= jackpot:
            tier = "variable"  # low EV, but some unique on it >= jackpot_divine
        if cfg.get("unknown_as_variable") and chase:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(chase))
        result[base] = (tier, cheapest, best[0], best[1], value)

    for base, cheapest in cheap_by_base.items():
        if base in ev_by_base:
            continue
        best = best_by_base.get(base, (0, ""))
        tier = tiers.of(priced_by_base[base])  # base_price: cheapest or priciest confident unique
        if best[0] >= jackpot:
            tier = jackpot_tier(tiers, tier, lambda t: not off(t))
        if off(tier):
            tier = "hide"
        if hidden(cfg, tier) and best[0] >= jackpot:
            tier = "variable"
        if cfg.get("unknown_as_variable") and base in unknown:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(sorted(unknown[base])))
        result[base] = (tier, cheapest, best[0], best[1], None)
    wiki_bases = data.get("wiki_bases", {})
    boss_only_bases = {
        base for base, names in wiki_bases.items()
        if names and all(no_map_drop(data, name) and name not in content_prices for name in names)
    }
    map_drop_bases = {
        base for base, names in wiki_bases.items()
        if any(not no_map_drop(data, name) or name in content_prices for name in names)
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


def valuable_content_bases(data, cfg, tiers):
    """Enabled-module bases worth the faded show: base -> its most valuable content unique's
    confident price (cheapest variant), kept only when that price's tier is a shown unique tier.
    Normal uniques only: Foulborn ones come from Wombgifts, never from the content itself."""
    rescue = content_policy(data.get("content", {}), cfg)["rescue"]
    shown, min_listings = shown_unique_tiers(cfg, tiers), cfg["uniques"]["min_listings"]
    value, listings = {}, {}
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            base, name = line.get("baseType"), line["name"]
            if name.startswith("Foulborn ") or line.get("links"):
                continue
            n = line.get("listingCount", 0)
            if name in rescue.get(base, ()) and n >= min_listings:
                value.setdefault(base, {})
                value[base][name] = min(value[base].get(name, math.inf), line["chaosValue"])
                listings[base, name] = listings.get((base, name), 0) + n
    value = {b: [c for n, c in v.items() if listings[b, n] >= min_listings] for b, v in value.items()}
    return {b: max(v) for b, v in value.items() if v and tiers.of(max(v)) in shown}


def price_foulborn_bases(data, cfg, tiers, divine_chaos):
    """base -> (tier, cheapest_chaos or None, best_chaos, best_label). Foulborn uniques only.

    Mutated mods vary per drop and the filter can't see them, so a base gets the cheapest
    variant of any confident Foulborn unique on it (listings summed over its variants).
    best = best variant with any listing. Below min_tier / small_loot: hidden, unless jackpot
    ([foulborn] jackpot_divine, own value) -> blue, or priced >= never_hide_tier. No confident price: foulborn.unpriced.
    """
    f, u = cfg["foulborn"], cfg["uniques"]
    # content-module uniques (Breach boss...): Foulborn versions always priced, module on or off.
    # The filter sees "Foulborn True" and Foulborn come from Wombgifts, not the content itself.
    content_prices = {n for by_base in data.get("content", {}).values()
                      for names in by_base.values() for n in names}
    per = {}  # (base, name) -> [listings over all variants, cheapest variant, (best, label)]
    boss_only = set()
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            name, base = line["name"], line.get("baseType")
            if not name.startswith("Foulborn ") or not base or line.get("links"):
                continue
            plain = name[len("Foulborn "):]
            boss = no_map_drop(data, name) and plain not in content_prices  # cheapest only, never best
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

    # own jackpot: Foulborn come from Wombgifts only (few drops), so a lower bar is worth a look
    jackpot = f["jackpot_divine"] * divine_chaos if divine_chaos else math.inf
    min_rank = min_shown_rank(cfg, tiers, f["min_tier"])
    result = {}
    for base, best in best_by_base.items():
        cheapest = cheap_by_base.get(base)
        tier = tiers.of(cheapest) if cheapest is not None else f["unpriced"]
        if best[0] >= jackpot:
            tier = jackpot_tier(tiers, tier, lambda t: not hidden(cfg, t) and tiers.rank(t) <= min_rank)
        if cheapest is not None and tier != "variable" and tiers.rank(tier) > min_rank                 and not never_hidden(cfg, tiers, tier):
            tier = "hide"  # a jackpot (variable) is never hidden by min_tier
        if hidden(cfg, tier) and best[0] >= jackpot:
            tier = "variable"
        if cfg.get("unknown_as_variable") and cheapest is not None and base in unknown:
            tier = "variable"
            best = (best[0], best[1] + " + unknown value: " + ", ".join(sorted(unknown[base])))
        result[base] = (tier, cheapest, best[0], best[1])
    for base in boss_only - map_bases:
        result[base] = ("hide", None, 0, "boss / encounter-only uniques")
    return result


def viscera_base(name):
    """poe.ninja Viscera name -> in-game BaseType ("Greater Sirus' Head" -> "Sirus' Head")."""
    for p in VISCERA_PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return name


def price_viscera_bases(data, cfg, tiers, divine_chaos):
    """base -> (tier, cheapest_chaos or None, best_chaos, best_label). [viscera], class "Viscera".

    The filter sees only the BaseType: not the implicit (one poe.ninja line each) nor the
    Greater / Lesser prefix. So, as Foulborn: base = cheapest confident line (listings >=
    min_listings), best = best line with any listing. Best >= jackpot_divine -> jackpot_tier
    (blue unless top / high / mid). Below min_tier / small_loot ("Viscera" in types) -> hidden,
    unless best >= jackpot_divine -> blue or priced >= never_hide_tier. No confident line: not in result (league_mechanic
    classes blue catches it), except unknown_as_variable thin lines -> blue."""
    v = cfg["viscera"]
    if not v["enabled"]:
        return {}
    cheap, best, thin = {}, {}, {}
    for t in VISCERA_TYPES:
        for line in data["stash"][t].get("lines", []):
            listings = line.get("listingCount", 0)
            if listings < 1:
                continue
            base, chaos = viscera_base(line["name"]), line["chaosValue"]
            label = line["name"] + (f" [{line['variant']}]" if line.get("variant") else "")
            best[base] = max(best.get(base, (0, "")), (chaos, label))
            if listings >= v["min_listings"]:
                cheap[base] = min(cheap.get(base, math.inf), chaos)
            else:
                thin[base] = thin.get(base, 0) + 1
    jackpot = jackpot_chaos(cfg, divine_chaos)
    min_rank = tiers.rank(v["min_tier"])
    sl = small_loot(cfg)
    if sl and "Viscera" in sl[1]:
        min_rank = min_shown_rank(cfg, tiers, v["min_tier"])
    result = {}
    for base, (top, label) in best.items():
        cheapest = cheap.get(base)
        if cheapest is None and not cfg.get("unknown_as_variable"):
            continue
        tier = tiers.of(cheapest) if cheapest is not None else "variable"
        if top >= jackpot:
            tier = jackpot_tier(tiers, tier, lambda t: not hidden(cfg, t) and tiers.rank(t) <= min_rank)
        if tier != "variable" and tiers.rank(tier) > min_rank and not never_hidden(cfg, tiers, tier):
            tier = "hide"
        if hidden(cfg, tier) and top >= jackpot:
            tier = "variable"
        if cfg.get("unknown_as_variable") and base in thin and cheapest is not None                 and (hidden(cfg, tier) or tiers.rank(tier) > tiers.rank("variable")):
            tier = "variable"  # a thin-listed variant has no confident price: blue, not quieter / hidden
            label += f" + {thin[base]} thin-listed variant(s)"
        result[base] = (tier, cheapest, top, label)
    return result


def emit_viscera(cfg, tiers, vbases):
    """[viscera] price blocks: Class "Viscera" + BaseType per tier, Moon icon. Before the stackables
    (whose [league_mechanic] classes blue catches unpriced Viscera), after [overrides]."""
    if not vbases:
        return ""
    out = section("Viscera (poe.ninja price per base, config.toml [viscera])")
    groups = {}
    for base, (tier, *_rest) in vbases.items():
        groups.setdefault("hide" if hidden(cfg, tier) else tier, []).append(base)
    for tier in tiers.order:
        if groups.get(tier):
            conds = ['Class == "Viscera"', f"BaseType == {q(groups[tier])}"]
            if tier == "hide":
                out += block("Hide", conds, HIDDEN_STYLE, "viscera priced below [viscera] min_tier / hidden tier")
            else:
                out += block(action_for(cfg, tier), conds, style_for(cfg, tier, LEAGUE_SHAPE), f"viscera {tier}")
    return out


def price_linked_jackpots(data, cfg, divine_chaos):
    """links -> {bases}: a linked unique (5L/6L, any variant, Foulborn too) >= jackpot.
    Unlinked pricing skips linked lines, so without this a 5L jackpot on a junk base hides.
    Boss / encounter-only uniques are skipped as in the other unique pricing."""
    jackpot = jackpot_chaos(cfg, divine_chaos)
    content_prices = content_policy(data.get("content", {}), cfg)["price_names"]
    out = {}
    for t in UNIQUE_TYPES:
        for line in data["stash"][t].get("lines", []):
            if line.get("links") and line.get("baseType") and line.get("listingCount", 0) >= 1 \
                    and line["chaosValue"] >= jackpot \
                    and (not no_map_drop(data, line["name"]) or line["name"] in content_prices):
                out.setdefault(line["links"], set()).add(line["baseType"])
    return out


def price_crafting_bases(data, cfg, tiers, divine_chaos):
    """[(tier, ilvl_min, ilvl_max or None, influence or None, base, chaos)]

    Each confident poe.ninja entry covers its ilvl up to the next listed ilvl. Keep its own
    price: a higher ilvl can have less crafting demand, so its price must not floor this one.
    A confident entry worth >= jackpot is shown "variable". A price <= [bases] dump_floor
    (chaos) is poe.ninja's bulk-dump floor (everyone lists loot at 1c), not a value: unpriced,
    so the gear modules decide, as for bases below min_tier.
    """
    b = cfg["bases"]
    if not b["enabled"]:
        return []
    min_rank = tiers.rank(b["min_tier"])
    jackpot = jackpot_chaos(cfg, divine_chaos)
    by_base = {}  # (name, infl) -> [(ilvl, chaos, confident)]
    for line in (l for t in BASE_TYPES for l in data["stash"].get(t, {}).get("lines", [])):
        infl = line.get("variant")
        if infl and "/" in infl and not b["include_dual_influence"]:
            continue
        confident = (line.get("listingCount", 0) >= b["min_listings"] and line.get("count", 0) >= b["min_samples"]
                     and line["chaosValue"] > b["dump_floor"])
        by_base.setdefault((line["name"], infl), []).append(
            (line.get("levelRequired", 0), line["chaosValue"], confident))

    out = []
    for (name, infl), entries in by_base.items():
        entries.sort(key=lambda e: -e[0])
        upper = None  # next ilvl above
        for ilvl, chaos, confident in entries:
            if confident:
                if chaos >= jackpot:
                    out.append(("variable", ilvl, upper - 1 if upper else None, infl, name, chaos))
                else:
                    tier = tiers.of(chaos)
                    if tiers.rank(tier) <= min_rank:
                        out.append((tier, ilvl, upper - 1 if upper else None, infl, name, chaos))
            upper = ilvl
    return out


def cheap_influenced_bases(data, cfg):
    """[(ilvl_min, ilvl_max or None, influence, base, chaos)]: influenced base + ilvl lines poe.ninja
    prices confidently (min_listings + min_samples) at <= [bases] dump_floor = known junk (393
    listings at 2c), for cheap_influenced_hides. Ilvl range as price_crafting_bases
    (up to the next listed ilvl). [bases] disabled or dump_floor 0 -> []."""
    b = cfg["bases"]
    if not b["enabled"] or not b["dump_floor"]:
        return []
    by_base = {}
    for line in (l for t in BASE_TYPES for l in data["stash"].get(t, {}).get("lines", [])):
        infl = line.get("variant")
        if not infl or ("/" in infl and not b["include_dual_influence"]):
            continue
        by_base.setdefault((line["name"], infl), []).append(line)
    out = []
    for (name, infl), lines in by_base.items():
        upper = None
        for line in sorted(lines, key=lambda l: -l.get("levelRequired", 0)):
            ilvl = line.get("levelRequired", 0)
            if (line.get("listingCount", 0) >= b["min_listings"] and line.get("count", 0) >= b["min_samples"]
                    and line["chaosValue"] <= b["dump_floor"]):
                out.append((ilvl, upper - 1 if upper else None, infl, name, line["chaosValue"]))
            upper = ilvl
    return out


def is_talisman(line):
    """poe.ninja base line of a talisman (anointed beast amulet, "<beast> Talisman")."""
    return line.get("itemType") == "Amulet" and line["name"].endswith(" Talisman")


def price_talismans(data, cfg, tiers, divine_chaos):
    """[(tier, ilvl_min, ilvl_max or None, influence or None, base, chaos)] for talismans
    ([content.bestiary] talismans): decided by price like crafting bases, but every confident price
    counts (min_listings + min_samples; no [bases] min_tier, no dump_floor: a 1c talisman with
    hundreds of listings is worth 1c, not "some gear module decides"; the only module Show for
    them is the blue anointed-amulet catch-all). [content.bestiary] talisman_min_tier: a confident
    price below it is hidden like a hidden tier (emit_talismans). Each price covers its ilvl up to the next listed ilvl; a
    price cheaper than blue "variable" also covers lower ilvls down to the next confident one
    (thin / unlisted lower ilvls too: a lower ilvl is never worth more, blue would claim more than
    that known ceiling). A thin higher ilvl stays blue. Jackpot ->
    "variable". Unconfident: no entry (anointed amulets blue / NeverSink talisman tiers)."""
    b = cfg["bases"]
    if not (b["enabled"] and cfg["content"]["bestiary"]["talismans"]):
        return []
    jackpot = jackpot_chaos(cfg, divine_chaos)
    by_base = {}  # (name, infl) -> [(ilvl, chaos, confident)]
    for line in (l for t in BASE_TYPES for l in data["stash"].get(t, {}).get("lines", []) if is_talisman(l)):
        infl = line.get("variant")
        if infl and "/" in infl and not b["include_dual_influence"]:
            continue
        confident = line.get("listingCount", 0) >= b["min_listings"] and line.get("count", 0) >= b["min_samples"]
        by_base.setdefault((line["name"], infl), []).append(
            (line.get("levelRequired", 0), line["chaosValue"], confident))
    out = []
    for (name, infl), entries in by_base.items():
        entries.sort(key=lambda e: -e[0])
        upper = None  # next ilvl above (any line: a thin pricier ilvl above stays blue)
        for i, (ilvl, chaos, confident) in enumerate(entries):
            if confident:
                tier = "variable" if chaos >= jackpot else tiers.of(chaos)
                # down to where the next confident price below stops (it covers up to its next listed ilvl)
                j = next((j for j in range(i + 1, len(entries)) if entries[j][2]), None)
                lo = ilvl if tiers.rank(tier) <= tiers.rank("variable") else entries[j - 1][0] if j else 1
                out.append((tier, lo, upper - 1 if upper else None, infl, name, chaos))
            upper = ilvl
    return out


def emit_talismans(cfg, tiers, entries):
    """Talisman price blocks ([content.bestiary] talismans, price_talismans()): Show at a shown tier,
    Hide at a hidden one. Inside emit_exotics, right before the anointed-amulet Shows (every
    talisman drops anointed, so those would make every talisman blue); after the fractured /
    veiled / synthesised exotic looks, id_mods and perfection / overquality (they say more)."""
    floor = tiers.rank(cfg["content"]["bestiary"]["talisman_min_tier"])
    groups = {}
    for tier, lo, hi, infl, name, _ in entries:
        groups.setdefault((tier, lo, hi, infl), []).append(name)
    out = ""
    for tier, lo, hi, infl in sorted(groups, key=lambda k: (k[0] != "variable", tiers.rank(k[0]), -k[1], k[3] or "")):
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        below = tier != "variable" and tiers.rank(tier) > floor
        out += block("Hide" if below else action_for(cfg, tier),
                     crafting_conds(lo, hi, infl, groups[(tier, lo, hi, infl)])
                     + ['Class == "Amulets"'], gear_style(cfg, tier),
                     f"talisman {tier} ilvl{span} {infl or 'plain'}{' below talisman_min_tier' if below else ''}"
                     " (config.toml [content.bestiary] talismans)")
    return out


def fallback_tiers(cfg, kind):
    """kind "currency" (currency, corpses, vials: NeverSink tier number "1".."9") or "cards"
    (NeverSink card group "t1".."t5") -> {name: our tier}, from fallback_tiers.toml (made by
    tools/import_fallback_tiers.py; cfg["fallback_tiers"]) via config.toml
    [exchange.reference_currency_tiers] / [exchange.reference_card_tiers]. Fallback while
    poe.ninja has no confident price (league start, thin cards). Unmapped group: skipped."""
    mapping = cfg["exchange"].get("reference_currency_tiers" if kind == "currency" else "reference_card_tiers", {})
    return {name: mapping[g] for name, g in cfg["fallback_tiers"][kind].items() if g in mapping}


def fallback_groups(cfg, kind):
    """{name: NeverSink group} as in fallback_tiers.toml (for group-keyed options, e.g.
    [exchange.reference_currency_stacks])."""
    return cfg["fallback_tiers"][kind]


# ---------------------------------------------------------------- emitting

def q(names):
    return " ".join(f'"{n}"' for n in sorted(names))


def block(action, conds, style, comment=""):
    head = action + (f" # {comment}" if comment else "")
    return "\n".join([head] + [f"\t{c}" for c in conds] + [f"\t{s}" for s in style]) + "\n"


def hidden(cfg, tier):
    return tier == "hide" or tier in cfg.get("hide_tiers", [])


def jackpot_tier(tiers, tier, shown):
    """Tier of a base whose best unique is a jackpot. Top stays a tink; a shown price tier that
    beats blue (high / mid: known cheapest is already worth it) keeps its louder style; anything
    else (cheaper, hidden, unpriced) -> "variable", so a jackpot is never hidden or downgraded."""
    if tier == tiers.names[0] or (tier in tiers.names and shown(tier)
                                  and tiers.rank(tier) < tiers.rank("variable")):
        return tier
    return "variable"


def quiet_tier_lines(cfg):
    """[style.quiet] lines for quiet_tiers; quiet_icon = false drops the MinimapIcon (beam_icon
    then leaves these blocks without one). Recipe floors keep the full quiet look (icon + beam)."""
    lines = cfg["style"]["quiet"]["lines"]
    if cfg.get("quiet_icon", True):
        return lines
    return [l for l in lines if not l.startswith("MinimapIcon")]


def style_for(cfg, tier, shape=BASE_SHAPE):
    if hidden(cfg, tier):
        return HIDDEN_STYLE
    lines = cfg["style"][tier]["lines"]
    if tier in cfg.get("quiet_tiers", []):
        # quiet style, but keep the tier's own font size
        lines = [l for l in lines if l.startswith("SetFontSize")] + quiet_tier_lines(cfg)
    if tier == max(cfg["tiers"], key=cfg["tiers"].get):
        shape = UNIQUE_SHAPE  # tink
    # MinimapIcon <size> <colour> <shape>: keep tier size/colour, swap shape
    return [" ".join(l.split()[:3] + [shape]) if l.startswith("MinimapIcon") else l for l in lines]


def gear_style(cfg, tier, shape=BASE_SHAPE, force_text=False):
    """style_for for gear. force_text (Fated / [unid_tier] / memory strands): the tier's text
    colour -> gear_text_color, except variable (keeps [style.variable] pale blue)."""
    style = style_for(cfg, tier, shape)
    if hidden(cfg, tier) or tier == "variable" or not force_text:
        return style
    return [l for l in style if not l.startswith("SetTextColor")] + [f"SetTextColor {cfg['gear_text_color']}"]


def shape_of(name, item_type):
    if "Splinter" in name:
        return SPLINTER_SHAPE
    if name.endswith("Crystallised Lifeforce"):
        return LIFEFORCE_SHAPE
    return SHAPE.get(item_type, BASE_SHAPE)


def action_for(cfg, tier):
    return "Hide" if hidden(cfg, tier) else "Show"


def section(title):
    bar = "#" + "=" * 78
    return f"\n{bar}\n# {title}\n{bar}\n\n"


def emit_defaults(cfg):
    # Continue blocks: style applies, later blocks can still override or hide
    out = section("Defaults: no borders, gear text colour (config.toml gear_text_color)")
    out += block("Show", [], ["SetFontSize 45", "SetBorderColor clear", "Continue"],
                 "maximum item size; no borders unless a style sets one")
    # campaign ([leveling] on): gear keeps its rarity colour
    lv = cfg.get("leveling", {})
    camp = [f"AreaLevel > {lv.get('area_level_max', 67)}"] if lv.get("enabled") else []
    out += block("Show", ["Rarity <= Rare"] + camp + [f"Class == {q(GEAR_CLASSES)}"],
                 [f"SetTextColor {cfg['gear_text_color']}", "Continue"], "gear text colour, not rarity colour")
    if lv.get("enabled") and cfg.get("campaign_white_text_color"):
        out += block("Show", ["Rarity Normal", f"AreaLevel <= {lv.get('area_level_max', 67)}", f"Class == {q(GEAR_CLASSES)}"],
                     [f"SetTextColor {cfg['campaign_white_text_color']}", "Continue"], "campaign white gear: grey text")
    return out


def emit_pinned_stackables(cfg):
    """Divine / Mirror / Hinekora's Lock (PINNED_TOP_STACKABLES, fixed) and every item of a
    config.toml always_top_classes class (Reliquary keys, priced or not): top tier, first
    block, never hidden (beats [overrides], prices, modules)."""
    classes = cfg.get("always_top_classes", [])
    return section("Pinned top-tier stackables + always_top_classes") + "".join(
        block("Show", [f"BaseType == {q([name])}"], style_for(cfg, "top", SHAPE["Currency"]),
              f"pinned {name} (always tink)")
        for name in sorted(PINNED_TOP_STACKABLES)
    ) + "".join(block("Show", [f"Class == {q([c])}"], style_for(cfg, "top", SHAPE["Fragment"]),
                      f"always top {c} (config.toml always_top_classes)") for c in classes)


def emit_overrides(cfg, prices):
    groups = {}
    for name, tier in cfg.get("overrides", {}).items():
        if name in PINNED_TOP_STACKABLES:
            continue
        shape = shape_of(name, prices.get(name, (0, None))[1])
        groups.setdefault((tier, shape), []).append(name)
    if not groups:
        return ""
    out = section("Overrides (config.toml [overrides])")
    for (tier, shape), names in groups.items():
        out += block(action_for(cfg, tier), [f"BaseType == {q(names)}"], style_for(cfg, tier, shape), f"override {tier}")
    return out


# Module gear_special (rules/modules/gear_special.filter, made with:
#   tools/import_neversink.py gear_special 0302:0600 0901:0902
#     --config-key "crafting->qualityperfection\.(anyoverquality(perf|high)?|armors1q\d|weapont\dq\d|qualchancing)=config.toml [overquality]"
#     --config-key "s0500_1=price (stackables)" --config-key "s0500_[234]=config.toml [vendor_recipes.grasping_mail]"
#     --config-key "s0500_5=price (uniques)")
# [0302] influenced rares, [[0400]] eldritch (Exarch / Eater implicits), [[0500]] exotic bases
# (heist / ritual / Kalandra / talisman / Grasping Mail / Stygian / Cord Belt ...), [0901]
# perfection + overquality. [[0500]]'s five untagged FilterBlade "Conditional Entry" blocks are
# decided elsewhere (Stacked Deck: stackable price, breach rings: [vendor_recipes.grasping_mail],
# unique Opal Ring / Abyssal Axe: unique price): their modules.toml value says where, no block.
GEAR_SPECIAL_TOP_SECTIONS = [("0302", "0600")]
PERFECTION_SECTION = ("0901", "0902")
# [0901] overquality blocks, on / off from config.toml [overquality] quality_<N>
OVERQUALITY_KEYS = {"crafting->qualityperfection.anyoverqualityperf": 30,
                    "crafting->qualityperfection.anyoverqualityhigh": 27,
                    "crafting->qualityperfection.anyoverquality": 21}
# other quality-threshold module blocks: on / off from config.toml [overquality] <name>
# (modules.toml value "config.toml [overquality]"; module_blocks resolves them, block unchanged)
OVERQUALITY_TOGGLES = {
    "crafting->qualityperfection.armors1q1": "armour_t1_28",
    "crafting->qualityperfection.armors1q2": "armour_t1_21",
    "crafting->qualityperfection.weapont1q1": "weapon_t1_28",
    "crafting->qualityperfection.weapont1q2": "weapon_t1_24",
    "crafting->qualityperfection.weapont2q1": "weapon_t2_28",
    "crafting->qualityperfection.weapont2q2": "weapon_t2_24",
    "crafting->qualityperfection.qualchancing": "chancing_bases_28",
    "endgameflasks.any20qualflask": "any_flask_21",
    "endgametinctures.overqual1": "tinctures_26",
    "endgametinctures.overqual2": "tinctures_21",
    "endgameflasks.overqualutil1": "utility_flasks_26",
    "endgameflasks.overqualutil2": "utility_flasks_21",
    "endgameflasks.overqualcorrupted": "utility_corrupted_30",
    "endgameflasks.overquallife1": "life_mana_flasks_30",
    "endgameflasks.overquallife2": "life_mana_flasks_21",
    "uniques.overqual": "uniques_21",
}
# FilterBlade Overquality Armours / Weapons rank grids: module block -> config.toml [overquality]
# base list that replaces its BaseType line ([] = no block)
OVERQUALITY_RANK_LISTS = {
    "crafting->qualityperfection.armors1q1": "rank_a_armour",
    "crafting->qualityperfection.armors1q2": "rank_a_armour",
    "crafting->qualityperfection.weapont1q1": "rank_a_weapons",
    "crafting->qualityperfection.weapont1q2": "rank_a_weapons",
    "crafting->qualityperfection.weapont2q1": "rank_b_weapons",
    "crafting->qualityperfection.weapont2q2": "rank_b_weapons",
}


def module_elsewhere(b):
    """module_blocks driven for keys decided by another system (the modules.toml value names it:
    price, a [vendor_recipes.*] entry): no block."""
    return ""


# [0302] influenced rares = FilterBlade "Influenced Items" (High Rank A / B / C, Specific Influence
# BaseTypes / Classes, Remaining). modules.toml value "config.toml [influenced]": module key ->
# (config list that switches it on, the entry in it, list table + name, min_ilvl key).
INFLUENCES = ("crusader", "warlord", "redeemer", "hunter", "shaper", "elder")
INFLUENCED_KEYS = {
    "influenced->all.t1exotic": ("ranks", "A", ("rank_bases", "A"), "A"),
    "influenced->all.t1top": ("ranks", "B", ("rank_bases", "B"), "B"),
    "influenced->all.t2high": ("ranks", "C", ("rank_bases", "C"), "C"),
    **{f"influenced->all.t1bases{i}": ("bases", i, ("influence_bases", i), "bases") for i in INFLUENCES},
    **{f"influenced->all.t2classes{i}": ("classes", i, ("influence_classes", i), "classes") for i in INFLUENCES},
    "influenced->all.t2classesinfluencedshared": ("classes", "shared", ("influence_classes", "shared"), "shared"),
    "influenced->all.any86": ("remaining", "high", None, "high"),
    "influenced->all.any": ("remaining", "all", None, None),
}


def influenced_driven(cfg):
    """module_blocks driven for gear_special: [0302] keys from config.toml [influenced]
    (INFLUENCED_KEYS); a block is on when its entry is in the switch list (ranks / bases / classes
    / remaining), its BaseType / Class list and ItemLevel come from config (min_ilvl 0 = none),
    HasInfluence / Rarity / style stay the module's. Other driven keys: module_elsewhere."""
    inf = cfg.get("influenced", {})
    for lst, allowed in (("ranks", "ABC"), ("bases", INFLUENCES), ("classes", INFLUENCES + ("shared",)),
                         ("remaining", ("high", "all"))):
        bad = set(inf.get(lst, [])) - set(allowed)
        if bad:
            raise ValueError(f"influenced.{lst}: unknown {sorted(bad)}, use {list(allowed)}")

    def driven(b):
        spec = INFLUENCED_KEYS.get(b["key"])
        if spec is None:
            return module_elsewhere(b)
        switch, entry, table, ilvl_key = spec
        if entry not in inf[switch]:
            return ""
        conds = [c for c in b["conds"] if not c.startswith(("BaseType", "Class", "ItemLevel"))]
        ilvl = inf["min_ilvl"][ilvl_key] if ilvl_key else 0
        if ilvl:
            conds.append(f"ItemLevel >= {ilvl}")
        if table:
            names = inf[table[0]][table[1]]
            if not names:
                return ""
            conds.append(f"{'Class' if table[0] == 'influence_classes' else 'BaseType'} == {q(names)}")
        else:  # remaining: every gear class of the module block
            conds += [c for c in b["conds"] if c.startswith("Class")]
        return _transform_block(b["action"], conds, b["style"], f"gear {b['key']}", source="module gear_special")
    return driven


def overquality_driven(cfg):
    """[0901] overquality blocks from config.toml [overquality] quality_30 / 27 / 21 (not
    league_start). 30% = our top-tier (tink) style via style_for, incl. its border / background
    (the one tier allowed them); 27% / 21% league.filter's style. Uniques left to price."""
    oq = cfg.get("overquality", {})
    top = max(cfg["tiers"], key=cfg["tiers"].get)

    def driven(b):
        quality = OVERQUALITY_KEYS.get(b["key"])
        if quality is None:
            return module_elsewhere(b)
        if not oq.get(f"quality_{quality}", False):
            return ""
        style = style_for(cfg, top) if quality == 30 else b["style"]
        return block("Show", b["conds"] + ["Rarity <= Rare"], style,
                     f"overquality {quality}%+ (module gear_special {b['key']}, config.toml [overquality])")
    return driven


def flask_base_classes(data):
    """{flask / tincture base name: filter Class} from the poe.ninja base feeds' itemType
    ("Utility Flask" -> "Utility Flasks", "Tincture" -> "Tinctures")."""
    return {l["name"]: l["itemType"] + "s" for t in BASE_TYPES for l in data["stash"].get(t, {}).get("lines", [])
            if l.get("itemType", "").endswith(("Flask", "Tincture"))}


def emit_priced_bases_first(cfg, tiers, entries, flask_classes=None):
    """Copy of the crafting-base Shows (emit_crafting_bases: confident poe.ninja base + influence +
    ilvl price at a shown tier, or jackpot -> variable) before the gear_special / crafting module
    Shows: a priced base keeps its price tier there (price = source of truth). No Hides: a base
    priced below [bases] min_tier is not decided by price, so module Shows apply to it
    (league.filter behaviour). After id_mods / flasks / perfection / exotics: an identified
    good-mod, fractured or strand item keeps that look (it says more than the base price); before
    vendor recipes (same tier as their recipe_floor copy). Also before the plain flask Shows
    (emit_flasks plain=True): a priced flask base (Silver Flask ilvl 85) keeps its tier.
    flask_classes (flask_base_classes): flask bases whose Class no unused-white Hide names skip the
    unused_whites_min_tier hold-back (they never wait for those Hides)."""
    if not entries or not (cfg.get("gear_special", {}).get("enabled", True)
                           or any(cfg["links"].values()) or any(cfg["chancing"].values())
                           or cfg.get("flasks", {}).get("enabled", True)):
        return ""
    # bases below [leveling] unused_whites_min_tier wait for emit_crafting_bases (after its unused-white Hides)
    floor = tiers.rank(cfg.get("leveling", {}).get("unused_whites_min_tier") or cfg["bases"]["min_tier"])
    base_floor = tiers.rank(cfg["bases"]["min_tier"])
    unused = unused_white_hides(cfg)
    all_classes = any("Class" not in b for b in re.split(r"(?m)^(?=Hide\b)", unused) if b.strip())
    free = {n for n, c in (flask_classes or {}).items() if not all_classes and f'"{c}"' not in unused}
    groups = {}
    for tier, lo, hi, infl, name, _ in entries:
        if (tier == "variable" or tiers.rank(tier) <= (base_floor if name in free else floor)) \
                and not hidden(cfg, tier):
            groups.setdefault((tier, lo, hi, infl), []).append(name)
    out = ""
    for tier, lo, hi, infl in sorted(groups, key=lambda k: (k[0] != "variable", tiers.rank(k[0]), -k[1], k[3] or "")):
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        out += block("Show", crafting_conds(lo, hi, infl, groups[(tier, lo, hi, infl)]), gear_style(cfg, tier),
                     f"base {tier} ilvl{span} {infl or 'plain'} (priced, before gear modules)")
    return section("Priced crafting bases, before the gear modules (poe.ninja base prices)") + out if out else ""


def emit_gear_special(cfg, cheap=()):
    """[0302] influenced rares, [[0400]] eldritch, [[0500]] exotic bases: module gear_special.
    league.filter has it before [0600] id mods; ours comes after id_mods / flasks / perfection /
    exotics and emit_priced_bases_first (all Shows, only style differs): id-mod / exotic info and
    a base price beat an influence / base-type look. Uniques never match: every block is Rarity
    Normal / Magic / Rare. Before vendor recipes (league.filter: [[0500]] before [1400]).
    First the [influenced] hide_cheap Hides (cheap_influenced_hides)."""
    if not cfg.get("gear_special", {}).get("enabled", True):
        return ""
    return (section("Influenced / eldritch / exotic bases (config.toml [gear_special] + [influenced], "
                    "modules.toml [gear_special.blocks])")
            + cheap_influenced_hides(cfg, cheap)
            + module_blocks(cfg, "gear_special", "gear", sections=GEAR_SPECIAL_TOP_SECTIONS,
                            driven=influenced_driven(cfg)))


def cheap_influenced_hides(cfg, cheap):
    """[influenced] hide_cheap: Hides for influenced bases poe.ninja prices confidently at <=
    [bases] dump_floor (cheap_influenced_bases: known junk, not "no price"), before the [0302]
    blue Shows. Later Shows that must still win (links, vendor recipes = floor) are kept out by
    guards from the enabled options: [links] 5-link keys -> LinkedSockets <= 4, endgame_4l_armour
    -> <= 3; jeweller -> Sockets <= 5; chromatic -> Sockets <= 2 (no RGB possible).
    show_5_links / show_6_links are in rules/top.filter (already first)."""
    if not (cfg.get("influenced", {}).get("hide_cheap", False) and cheap):
        return ""
    links, recipes = cfg.get("links", {}), cfg.get("vendor_recipes", {})
    on = lambda r: recipes.get(r, {}).get("enabled", False)
    max_links = 3 if links.get("endgame_4l_armour") else 4 if any(links.values()) else None
    max_sockets = min([n for r, n in (("chromatic", 2), ("jeweller", 5)) if on(r)], default=None)
    guards = ([f"LinkedSockets <= {max_links}"] if max_links else []) +              ([f"Sockets <= {max_sockets}"] if max_sockets is not None else [])
    groups = {}
    for lo, hi, infl, name, _ in cheap:
        groups.setdefault((lo, hi, infl), []).append(name)
    out = ""
    for lo, hi, infl in sorted(groups, key=lambda k: (-k[0], k[2])):
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        conds = [c for c in crafting_conds(lo, hi, infl, groups[(lo, hi, infl)]) if c != "Corrupted False"]
        out += block("Hide", conds[:-1] + guards + conds[-1:], HIDDEN_STYLE,
                     f"influenced base ilvl{span} {infl} <= [bases] dump_floor ([influenced] hide_cheap)")
    return out


def overquality_rank_bases(cfg):
    """{module key: config.toml [overquality] rank list} (OVERQUALITY_RANK_LISTS; missing = error)."""
    return {k: cfg["overquality"][v] for k, v in OVERQUALITY_RANK_LISTS.items()}


PERFECTION_KEY = "crafting->qualityperfection.perfectioncrafting"


def perfection_bases(cfg):
    """{PERFECTION_KEY: names | None} from config.toml [gear_special] perfection_armour: NeverSink
    rare base tiers ("t1".."t5", the rares module's rr blocks) -> their base names (the block's own
    armour Class line keeps weapons out); "all" = None (any base); [] = no block. Unknown = error."""
    wanted = cfg["gear_special"]["perfection_armour"]  # missing key = error (no hidden settings)
    if "all" in wanted:
        return {PERFECTION_KEY: None}
    rr = {b["key"].rsplit(".", 1)[1]: b for b in load_module("rares") if re.fullmatch(r"rr\.t\d", b["key"])}
    bad = set(wanted) - set(rr)
    if bad:
        raise ValueError(f"config.toml [gear_special] perfection_armour: unknown {sorted(bad)}, use {sorted(rr)} or \"all\"")
    names = set()
    for t in wanted:
        for c in rr[t]["conds"]:
            if c.startswith("BaseType"):
                names.update(re.findall(r'"([^"]+)"', c))
        if not any(c.startswith("BaseType") for c in rr[t]["conds"]):
            return {PERFECTION_KEY: None}  # a tier with no base list (rr.t5) = any base
    return {PERFECTION_KEY: sorted(names)}


def emit_perfection(cfg):
    """[0901] perfection / overquality: module gear_special, the 3 any-gear overquality blocks
    from config.toml [overquality] (overquality_driven). league.filter: after id mods / flasks,
    before [0902] exotics; before vendor recipes (a 30% RGB item keeps its alert). The 30% block
    goes first (beats the ilvl 83+ perfection blocks: 30% always tinks). Rarity <= Rare
    added: a unique stays priced. Perfection block bases = [gear_special] perfection_armour
    (perfection_bases). [gear_special] enabled = false: only the [overquality] blocks
    (own option, independent of the module switch)."""
    if not cfg.get("gear_special", {}).get("enabled", True):
        driven = overquality_driven(cfg)
        out = "".join(driven(b) for b in load_module("gear_special") if b["key"] in OVERQUALITY_KEYS)
        return section("Overquality gear (config.toml [overquality])") + out if out else ""
    not_unique = {b["key"]: ["Rarity <= Rare"] for b in load_module("gear_special")
                  if b["section"] == PERFECTION_SECTION[0]}
    driven = overquality_driven(cfg)
    # 30% tink first: league.filter's perfection blocks (Quality >= 28 + ilvl 83+ bases) would
    # otherwise catch a 30% item with their own non-tink style
    tink = "".join(driven(b) for b in load_module("gear_special") if OVERQUALITY_KEYS.get(b["key"]) == 30)
    rest = lambda b: "" if OVERQUALITY_KEYS.get(b["key"]) == 30 else driven(b)
    return (section("Perfection / overquality (config.toml [gear_special] + [overquality], modules.toml [gear_special.blocks])")
            + tink + module_blocks(cfg, "gear_special", "perfection", sections=[PERFECTION_SECTION],
                                   extra_conds=not_unique, driven=rest,
                                   basetypes=overquality_rank_bases(cfg) | perfection_bases(cfg)))


# Module crafting (rules/modules/crafting.filter, made with:
#   tools/import_neversink.py crafting 1400:1500 2300:2500 2601:2602
#     --config-key "socketslinks\.5link\w*|normalcraft->extra\.earlyendgame4link=config.toml [links]"
#     --config-key "chancing\.\w+=config.toml [chancing]"
#     --config-key "normalcraft->extra\.earlycraftoptional|crafting->generalgear\.\w+=price (bases)"
#     --config-key "socketslinks\.(rgb\w+)=config.toml [vendor_recipes.chromatic]"
#     --config-key "socketslinks\.6sockets\w*=config.toml [vendor_recipes.jeweller]"
#     --config-key "endgamergb\.\w+=config.toml [vendor_recipes.chromatic]")
# [1401] 5-links, [2301] early endgame crafting, [2302] crafting matrix (ilvl 83-86 bases),
# [[2400]] chancing bases, [2601] RGB ([[2600]] animated weapons: module rares). The RGB /
# 6-socket blocks are vendor recipes: [vendor_recipes.chromatic] / [vendor_recipes.jeweller]
# (tier floor) cover them (any size / area level), so no module block.
LINK_SECTION = ("1400", "1500")
ENDGAME_CRAFTING_SECTIONS = [("2300", "2500"), ("2601", "2602")]
# Link / chancing blocks: on / off from config.toml [links] / [chancing] (modules.toml value
# "config.toml [links]" / "[chancing]"; config_toggle resolves them, block unchanged).
# [2301] early bases + [2302] matrix = fixed FilterBlade base lists: "price (bases)" (no block,
# poe.ninja [bases] min_tier decides crafting bases).
LINK_TOGGLES = {
    "socketslinks.5linksleveling": "leveling_5l",
    "socketslinks.5links": "endgame_5l",
    "socketslinks.5link6sockets": "five_link_6s",
    "normalcraft->extra.earlyendgame4link": "endgame_4l_armour",
}
CHANCING_TOGGLES = {"chancing.hh": "belts", "chancing.t2": "shield"}
MODULE_CONFIG_TOGGLES = {"overquality": OVERQUALITY_TOGGLES, "links": LINK_TOGGLES, "chancing": CHANCING_TOGGLES}


def emit_links(cfg):
    """[1401] 5-links (leveling, 5L 6S, endgame): module crafting. league.filter: after [1300]
    (emit_exotics), before [1500] bases, so before vendor recipes. rules/top.filter show_5_links
    (normal / magic / rare, like [0100]; uniques go to unique rules) is a different rule and
    stays first."""
    return (section("Linked gear (config.toml [links])")
            + module_blocks(cfg, "crafting", "links", sections=[LINK_SECTION], driven=module_elsewhere))


def emit_endgame_crafting(cfg):
    """[[2300]] crafting projects + matrix, [[2400]] chancing, [2601] RGB (vendor recipe: no
    block): module crafting. league.filter: after the rare gear tiers ([2201], emit_rares),
    before emit_rare_hide_layer ([[2600]] animated weapons, [2602] remaining rares, [[2700]];
    [2601] has no block, so its place before [[2600]] doesn't matter). Priced bases decided
    earlier (emit_priced_bases_first)."""
    return (section("Endgame 4-links / chancing bases (config.toml [links] / [chancing])")
            + module_blocks(cfg, "crafting", "crafting", sections=ENDGAME_CRAFTING_SECTIONS, driven=module_elsewhere))


def emit_visibility_toggles(cfg):
    """Config hides that beat any price: hide_forbidden_tome, show_contracts = false
    (every Heist contract, any rarity; quest contracts are Quest Items, untouched)."""
    out = ""
    if cfg.get("hide_forbidden_tome", False):
        out += block("Hide", ['BaseType == "Forbidden Tome"'], HIDDEN_STYLE,
                     "Forbidden Tome (config.toml hide_forbidden_tome)")
    if not cfg.get("show_contracts", True):
        out += block("Hide", ['Class == "Contracts"'], HIDDEN_STYLE, "Heist contracts (config.toml show_contracts)")
    return section("Config visibility toggles") + out if out else ""


def icon_floor_names(cfg):
    """[league_mechanic] icon_floor: names that always get a beam + minimap icon."""
    lm = cfg.get("league_mechanic", {})
    names = lm.get("names", []) + lm.get("fragments", [])
    return set(names) if lm.get("enabled") and lm.get("icon_floor") else set()


def floored(cfg, tier, shape):
    """(action, style) of a tier, but a tier without beam + icon (hidden, brown, dust) -> Show in
    the quiet look (grey beam + icon, the tier's font size; hidden tiers: the lowest shown size)."""
    style = style_for(cfg, tier, shape)
    if not hidden(cfg, tier) and any(l.startswith("PlayEffect") for l in style) \
            and any(l.startswith("MinimapIcon") for l in style):
        return action_for(cfg, tier), style
    size = [l for l in (cfg["style"].get(tier, {}).get("lines") or style_for(cfg, "brown")) if l.startswith("SetFontSize")]
    return "Show", size + [" ".join(l.split()[:3] + [shape]) if l.startswith("MinimapIcon") else l
                           for l in cfg["style"]["quiet"]["lines"]]


def emit_stackables(cfg, tiers, prices, ref_currency, ref_cards, card_volumes):
    ex = cfg["exchange"]
    overridden = set(cfg.get("overrides", {}))
    floor = icon_floor_names(cfg)
    singles = {}   # (tier, shape, floor) -> [names]
    stacks = {}    # (tier, n, shape, floor) -> [names]
    for name, (v, t) in prices.items():
        if name in PINNED_TOP_STACKABLES or name in overridden or v <= 0:
            continue
        own, shape, fl = tiers.of(v), shape_of(name, t), name in floor
        sl = small_loot(cfg)
        if sl and t in sl[1] and v < sl[0]:
            singles.setdefault(("hide", shape, fl), []).append(name)  # doesn't stack: wrist saver
            continue
        singles.setdefault((own, shape, fl), []).append(name)
        # cheapest stack size that lifts it into each better tier
        if t == "DivinationCard" and name in ex.get("card_rewards", {}):
            max_stack = ex["card_rewards"][name][2]
        else:
            max_stack = ex.get("splinters", {}).get(name, [None, ex.get("big_stacks", {}).get(name, ex["max_stack"])])[1]
        for tname, thr in tiers.list:
            if tiers.rank(tname) >= tiers.rank(own):
                continue
            need = math.ceil(thr / v - 1e-9)  # exact: stack value >= tier threshold
            if need <= max_stack:
                stacks.setdefault((tname, need, shape, fl), []).append(name)
        n = ex.get("show_stacks", {}).get(name)  # forced stack Show: before the hidden tiers' blocks
        if n and hidden(cfg, tiers.of(v * n)):
            stacks.setdefault((ex["show_stacks_tier"], n, shape, fl), []).append(name)

    def look(t, shape, fl):
        return floored(cfg, t, shape) if fl else (action_for(cfg, t), style_for(cfg, t, shape))

    out = section("Stackables (Currency Exchange prices)")
    forced = sorted(n for n in ex.get("show_stacks", {}) if n not in prices and n not in overridden)
    out += "".join(block(action_for(cfg, ex["show_stacks_tier"]), [f"StackSize >= {ex['show_stacks'][n]}", f"BaseType == {q([n])}"],
                         style_for(cfg, ex["show_stacks_tier"], "Circle"), f"{n} stack (config.toml [exchange.show_stacks])")
                   for n in forced)
    for tname in tiers.names:
        for (t, n, shape, fl), names in sorted(stacks.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][3])):
            if t == tname:
                act, style = look(t, shape, fl)
                out += block(act, [f"StackSize >= {n}", f"BaseType == {q(names)}"],
                             style, f"{t} stack x{n}" + (" (icon_floor)" if fl else ""))
        for (t, shape, fl), names in sorted(singles.items()):
            if t == tname:
                act, style = look(t, shape, fl)
                out += block(act, [f"BaseType == {q(names)}"], style, t + (" (icon_floor)" if fl else ""))
    for (t, shape, fl), names in sorted(singles.items()):
        if t == "hide" and fl:  # below the lowest tier: still beam + icon
            out += block(*floored(cfg, "hide", shape), [f"BaseType == {q(names)}"],
                         "priced below lowest tier (config.toml [league_mechanic] icon_floor)")
    hide = [n for (t, _, fl), names in singles.items() if t == "hide" and not fl for n in names]
    if hide:
        out += block("Hide", [f"BaseType == {q(hide)}"], HIDDEN_STYLE, "priced below lowest tier")

    def fallback(classes, setting, label, shape):
        if setting == "hide":
            return block("Hide", [f"Class == {q(classes)}"], HIDDEN_STYLE, f"unpriced {label}")
        return block(action_for(cfg, setting), [f"Class == {q(classes)}"], style_for(cfg, setting, shape), f"unpriced {label}")

    def reference(ref, conds, label, source="reference"):
        # unpriced names at their NeverSink reference tier (or [exchange.unpriced_tiers])
        groups = {}
        for name, tier in ref.items():
            if name not in prices and name not in overridden:
                groups.setdefault((tier, name in floor), []).append(name)
        out = ""
        for tier in ["variable"] + tiers.names + ["unknown", "hide"]:
            for fl in (True, False):
                if groups.get((tier, fl)):
                    act, style = look(tier, "Circle", fl)
                    out += block(act, conds + [f"BaseType == {q(groups[(tier, fl)])}"], style,
                                 f"unpriced {label}, {source} tier {tier}" + (" (icon_floor)" if fl else ""))
        return out

    # fixed tiers for known-cheap stackables, before (and regardless of) unpriced_currency
    out += reference(ex.get("unpriced_tiers", {}), [], "currency", "config")
    if ex["unpriced_currency"] == "reference":
        out += fallback_stacks(cfg, ref_currency, prices, fallback_groups(cfg, "currency"),
                               ex.get("reference_currency_stacks", {}), [], "currency")
        out += reference(ref_currency, [], "currency")
    out += emit_league_mechanic(cfg, prices, ref_currency)  # new league stuff: blue + Moon, before class fallbacks
    if cfg["content"]["bestiary"]["quiet_beasts"]:
        # itemised beasts (menagerie): Stackable Currency, magic / rare, BaseType = beast species.
        # Unique spirit beasts fall through to the blue unpriced currency block.
        size = [l for l in cfg["style"]["low"]["lines"] if l.startswith("SetFontSize")]
        out += block("Show", ['Class == "Stackable Currency"', "Rarity Magic Rare"],
                     size + quiet_tier_lines(cfg),
                     "itemised beasts, quiet look (config.toml [content.bestiary] quiet_beasts)")
    for classes, shape in CURRENCY_CLASSES:
        setting = "unknown" if ex["unpriced_currency"] == "reference" else ex["unpriced_currency"]
        out += fallback(classes, setting, classes[0].lower(), shape)
    card_fallbacks = {
        name: tier for name, tier in ref_cards.items()
        if card_volumes.get(name, 0) < ex["card_fallback_min_volume"]
    }
    card_stack = ex.get("card_fallback_stack", 0)
    out += fallback_stacks(cfg, card_fallbacks, prices, {n: "card" for n in card_fallbacks}, {"card": card_stack},
                           ['Class == "Divination Cards"'], "cards")
    out += reference(card_fallbacks, ['Class == "Divination Cards"'], "cards")
    unknown_card_style = [line for line in style_for(cfg, "unknown", "Circle")
                          if not line.startswith("PlayAlertSound")]
    unknown_card_style.append("DisableDropSound True")
    out += block(action_for(cfg, "unknown"), ['Class == "Divination Cards"'],
                 unknown_card_style, "unpriced cards (no poe.ninja quote or reward price)")
    return out


def fallback_stacks(cfg, ref, prices, groups, stack_of, conds, label):
    """league.filter's stack Shows for unpriced items whose fallback tier hides them (cards
    "exstack" x3, [3901] currency t5 x5 / t6 x14): StackSize >= stack_of[group] -> Show in
    [exchange] fallback_stack_tier. Priced / overridden names: their price decides (stack blocks)."""
    overridden = set(cfg.get("overrides", {}))
    by_stack = {}
    for name, tier in ref.items():
        n = stack_of.get(groups.get(name), 0)
        if n and hidden(cfg, tier) and name not in prices and name not in overridden:
            by_stack.setdefault(n, []).append(name)
    tier = cfg["exchange"].get("fallback_stack_tier", "low")
    return "".join(block(action_for(cfg, tier), [f"StackSize >= {n}"] + conds + [f"BaseType == {q(names)}"],
                         style_for(cfg, tier, "Circle"), f"unpriced {label}, hidden reference tier, stack x{n}, tier {tier}")
                   for n, names in sorted(by_stack.items()))


def emit_content_overrides(cfg, content, ubases):
    policy = content_policy(content, cfg)
    # true: faded show, but a base its price already shows keeps its price tier style
    show = {b: n for b, n in policy["show"].items() if hidden(cfg, ubases.get(b, ("hide",))[0])}
    if not show and not policy["hide"]:
        return ""
    out = section("League-content unique overrides ([content.<name>.drops])")
    for base, names in sorted(policy["hide"].items()):
        out += block("Hide", ["Rarity Unique", f"BaseType == {q([base])}"], HIDDEN_STYLE,
                     f"content override hide: {', '.join(sorted(names))}")
    for base, names in sorted(show.items()):
        out += block("Show", ["Rarity Unique", f"BaseType == {q([base])}"],
                     cfg["style"]["content"]["lines"],
                     f"content override show: {', '.join(sorted(names))}")
    return out


def recipe_floor(cfg, tiers, tier, bases, cbases):
    """-> [(tier, conds, style, label)]: crafting bases and [overrides] whose own tier is better
    than a recipe tier. Emitted (with the recipe's conditions) before the recipe block, so an
    ingredient worth more keeps its own tier. `bases` None = any base."""
    out, groups = [], {}
    for t, lo, hi, infl, name, _ in cbases:
        if tiers.rank(t) < tiers.rank(tier) and (bases is None or name in bases):
            groups.setdefault((t, lo, hi, infl), []).append(name)
    for (t, lo, hi, infl), names in sorted(groups.items(), key=lambda kv: (tiers.rank(kv[0][0]), -kv[0][1])):
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        out.append((t, crafting_conds(lo, hi, infl, names), gear_style(cfg, t), f"base {t} ilvl{span} {infl or 'plain'}"))
    over = {}
    for name, t in cfg.get("overrides", {}).items():
        if not hidden(cfg, t) and tiers.rank(t) < tiers.rank(tier) and (bases is None or name in bases):
            over.setdefault(t, []).append(name)
    for t, names in sorted(over.items(), key=lambda kv: tiers.rank(kv[0])):
        out.append((t, [f"BaseType == {q(names)}"], style_for(cfg, t), f"override {t}"))
    return out


# [vendor_recipes.*] sizes: inventory size -> condition sets (FilterBlade's RGB options:
# [1401] / [2601] rgbsmall1 + rgbsmall2, rgbmedium, rgblarge)
RECIPE_SIZES = {"small": [["Width 2", "Height 2"], ["Width 1", "Height <= 4"]],
                "medium": [["Width 2", "Height 3"]],
                "large": [["Width 2", "Height 4"]]}


RECIPE_MAX_QUALITY = 30  # highest item quality recipe_levels looks at (corrupted gems reach 23)


def recipe_levels(cfg, tiers, rec, prices, ref_currency=None):
    """[vendor_recipes.<name>] -> [(tier, extra conds)], best tier first; [] = nothing shown.
    Fixed `tier`: [(tier, [])]. tier = "price": what one ingredient vendors for = `reward` price
    x `reward_count`; with `per_quality` scaled by quality / per_quality (one item at
    `full_quality`+ = the full reward; 0 = off), one "Quality >= N" level per tier. Price only
    sets how loud: a value in a hidden tier gets the lowest shown tier (an enabled recipe shows
    every ingredient its `conds` accept, e.g. Quality >= 1: the lower threshold wins); `min_tier`
    = never quieter than that tier. Reward without a
    confident price: its NeverSink fallback tier's chaos threshold (ref_currency, as
    stackables), else blue "variable" (quality recipes: full_quality+, else any quality)."""
    tier = rec["tier"]
    if tier != "price":
        return [(tier, [])]
    per, full = rec.get("per_quality", 0), rec.get("full_quality", 0)
    price, ref = prices.get(rec["reward"]), (ref_currency or {}).get(rec["reward"])
    chaos = price[0] if price else cfg["tiers"].get(ref)
    if chaos is None:
        return [("variable", [f"Quality >= {full or 1}"] if per else [])]
    value = chaos * rec.get("reward_count", 1)
    shown = [n for n in tiers.names if not hidden(cfg, n)]
    low = rec.get("min_tier")  # quietest look, whatever the price (hidden tier: quiet look, recipe_blocks)
    floor = lambda t: (low if low and tiers.rank(t) >= tiers.rank(low)
                       else t if not hidden(cfg, t) else shown[-1] if shown else "variable")
    if not per:
        return [(floor(tiers.of(value)), [])]
    first = {}  # tier -> lowest quality reaching it
    for qual in range(1, RECIPE_MAX_QUALITY + 1):
        first.setdefault(floor(tiers.of(value * max(qual / per, 1 if full and qual >= full else 0))), qual)
    return [(t, [f"Quality >= {qual}"]) for t, qual in sorted(first.items(), key=lambda kv: tiers.rank(kv[0]))]


def emit_vendor_recipes(cfg, tiers, ubases, fbases, cbases, prices=None, ref_currency=None):
    """[vendor_recipes.<name>]: ingredients shown in the recipe's tier style (recipe_levels:
    fixed `tier`, or "price" = reward value, per quality level), Diamond icon.
    Ingredients = `bases` (any rarity) or, without bases, every item matching `conds` (+ `rarity`).
    Optional `sizes` (RECIPE_SIZES names, [] = any) and `area_level` ([min, max], [] = any) narrow
    it (one block set per `any` condition x size).
    The tier is a floor: unique bases whose own (normal or Foulborn) tier is better are left
    out, so their unique rule wins (a tink Fugitive Ring stays a tink); better crafting bases /
    [overrides] get a copy of their own block first (recipe_floor)."""
    out = ""
    for name, rec in cfg.get("vendor_recipes", {}).items():
        if not rec.get("enabled") or rec.get("uniques"):  # `uniques`: value floor, unique_vendor_values
            continue
        if rec["tier"] not in tiers.names + ["variable", "price"]:
            raise ValueError(f"[vendor_recipes.{name}] tier must be a price tier, variable or price, got {rec['tier']!r}")
        if rec["tier"] == "price" and not rec.get("reward"):
            raise ValueError(f"[vendor_recipes.{name}] tier = \"price\" needs `reward`")
        unknown = set(rec.get("sizes", [])) - set(RECIPE_SIZES)
        if unknown:
            raise ValueError(f"[vendor_recipes.{name}] sizes: unknown {sorted(unknown)}, use {list(RECIPE_SIZES)}")
        for tier, qual in recipe_levels(cfg, tiers, rec, prices or {}, ref_currency):
            out += recipe_blocks(cfg, tiers, name, rec, tier, qual, ubases, fbases, cbases)
    return section("Vendor recipes ([vendor_recipes.*], tier = floor)") + out if out else ""


def recipe_blocks(cfg, tiers, name, rec, tier, qual, ubases, fbases, cbases):
    """One recipe level of emit_vendor_recipes: floor copies, the recipe block, its uniques."""
    out = ""
    better = lambda b: any(tiers.rank(p.get(b, ("hide",))[0]) < tiers.rank(tier) for p in (ubases, fbases))
    classes = [rec["class"]] if isinstance(rec.get("class"), str) else rec.get("class")
    cls = [f"Class == {q(classes)}"] if classes else []
    # min_tier in a config-hidden tier: still shown, in the quiet (grey beam + icon) look
    quiet = hidden(cfg, tier) and rec.get("min_tier") == tier
    shape = GEM_SHAPE if classes and set(classes) <= GEM_CLASSES else BASE_SHAPE
    style = ([l for l in cfg["style"][tier]["lines"] if l.startswith("SetFontSize")]
             + [" ".join(l.split()[:3] + [shape]) if l.startswith("MinimapIcon") else l
                for l in cfg["style"]["quiet"]["lines"]]) if quiet else style_for(cfg, tier, shape)
    act = "Show" if quiet else action_for(cfg, tier)
    bases = rec.get("bases")
    conds = list(dict.fromkeys(list(rec.get("conds", [])) + qual))  # level's Quality >= 1 = conds' one
    if bases:
        items, uniques = ["Rarity < Unique", f"BaseType == {q(bases)}"], [b for b in bases if not better(b)]
    else:
        items, uniques = [f"Rarity {' '.join(rec['rarity'])}"] if rec.get("rarity") else [], []
    floor = recipe_floor(cfg, tiers, tier, bases, cbases)
    sizes = [c for s in rec.get("sizes", []) for c in RECIPE_SIZES[s]] or [[]]
    area = rec.get("area_level", [])
    area = [f"AreaLevel >= {area[0]}", f"AreaLevel <= {area[1]}"] if area else []
    for cond, size in ((c, s) for c in rec.get("any") or [""] for s in sizes):
        extra = cls + conds + area + size + ([cond] if cond else [])
        rarity = [c for c in items if c.startswith("Rarity")]  # recipe rarities are all <= Rare
        for t, fconds, fstyle, label in floor:
            own = [c for c in fconds if not (rarity and c.startswith("Rarity"))]
            out += block("Show", extra + rarity + own, fstyle, f"vendor recipe: {name} (worth more: {label})")
        out += block(act, extra + items, style, f"vendor recipe: {name}")
        if uniques:
            out += block(act, extra + ["Rarity Unique", f"BaseType == {q(uniques)}"],
                         style, f"vendor recipe: {name} (uniques not worth more)")
    return out


def emit_uniques(cfg, tiers, bases, fbases, linked, map_bases, rescue=None):
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
    # normal tiers say Foulborn False: a Foulborn takes only its own price, never its base's
    # normal one (Foulborn Cutlass 5.5c must not show red because United in Dream is 780c)
    normal = ["Rarity Unique", "Foulborn False"]
    for tier in shown:
        out += tier_blocks(tier, fbases, foul, "foulborn")
        out += tier_blocks(tier, bases, normal, "uniques")
        if tier == tiers.names[0] and cfg["uniques"].get("variable_classes"):
            # whole classes always blue; only a known tink base beats it
            out += block("Show", ["Rarity Unique", f"Class == {q(cfg['uniques']['variable_classes'])}"],
                         style_for(cfg, "variable", UNIQUE_SHAPE), "uniques variable_classes")
    for links in sorted(linked, reverse=True):
        out += block("Show", ["Rarity Unique", f"LinkedSockets >= {links}", f"BaseType == {q(linked[links])}"],
                     style_for(cfg, "variable", UNIQUE_SHAPE), f"linked unique jackpot {links}L")
    out += emit_corrupted_uniques(cfg)
    out += emit_unique_exceptions(cfg)  # after the shown price tiers, before the hidden ones
    # no faded content rescue for Foulborn: they only come from Wombgifts, never content drops
    for tier in order:
        if tier not in shown:
            out += tier_blocks(tier, fbases, foul, "foulborn")
    out += unpriced_blocks(cfg["foulborn"]["unpriced"], foul, "foulborn unpriced")
    # enabled [content.*] unique in a shown tier on a base the price rules hide: small + faded
    faded = sorted(b for b in rescue or {} if b in bases and hidden(cfg, bases[b][0]))
    if faded:
        out += block("Show", ["Rarity Unique", f"BaseType == {q(faded)}"], cfg["style"]["content"]["lines"],
                     "content override show: enabled [content.*] uniques on otherwise hidden bases")
    for tier in order:
        if tier not in shown:
            out += tier_blocks(tier, bases, normal, "uniques")
    out += unpriced_blocks(cfg["uniques"]["unpriced"], ["Rarity Unique"], "unpriced uniques")
    return out


def emit_unique_exceptions(cfg):
    """Unique variants a per-base price can't see (module unique_exceptions = league.filter
    [4801] / [4803] / [4804] overqual): uber Impresence / Forge swords (influence), Kaom's Heart
    (no sockets), Tabula, synthesised, abyss-socket uniques, Vestigial, unique idols, double
    corrupted, crucible, 21%+ quality (ours; league.filter 27%; on / off: config.toml
    [overquality] uniques_21). Shows only, inside emit_uniques after the shown price
    tiers (a priced shown base keeps its tier style) and before the hidden tiers (the variant
    beats its base's Hide). [4804] base lists / Foulborn = our unique / Foulborn pricing
    (modules.toml value "config.toml [uniques] (price)": no block).
    Refresh: python tools/import_neversink.py unique_exceptions 4801:4802 4803:4805
    --config-key "uniques[.](multispecialhigh|multispecial|foulborn|exdust[0-9])=config.toml [uniques] (price)"
    --config-key "uniques[.]overqual=config.toml [overquality]"  (then set its Quality line to 21)
    """
    if not cfg.get("unique_exceptions", {}).get("enabled", True):
        return ""
    return module_blocks(cfg, "unique_exceptions", "unique exception", driven=module_elsewhere)


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
    # jackpot (variable) blocks first, before the league-start unused-white hides
    keys = sorted(groups, key=lambda k: (k[0] != "variable", tiers.rank(k[0]), -k[1], k[3] or ""))
    unused = unused_white_hides(cfg)
    floor = tiers.rank(cfg.get("leveling", {}).get("unused_whites_min_tier") or cfg["bases"]["min_tier"])
    for tier, lo, hi, infl in keys:
        if unused and tier != "variable" and tiers.rank(tier) > floor:
            out, unused = out + unused, ""
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        out += block(action_for(cfg, tier), crafting_conds(lo, hi, infl, groups[(tier, lo, hi, infl)]),
                     gear_style(cfg, tier), f"base {tier} ilvl{span} {infl or 'plain'}")
    return out + unused


def crafting_conds(lo, hi, infl, names):
    # dual-influence entries use their first influence (matches any item having it)
    conds = ["Rarity <= Rare", "Corrupted False", f"ItemLevel >= {lo}"]
    if hi:
        conds.append(f"ItemLevel <= {hi}")
    return conds + [f"HasInfluence {infl.split('/')[0] if infl else 'None'}", f"BaseType == {q(names)}"]


# NeverSink endgame rare sections, module rules/modules/rares.filter, made with:
#   tools/import_neversink.py rares 1700:2300 2600:2601 2602:2800 --config-key "rr(->\w+)?\.t\d=config.toml [rares]"
# [[1700]] decorators (Continue) + talismans, [[1800]] veiled, [[1900]] breach rings, [[2000]]
# conditional hides, [[2100]] amulet / ring / belt tiers, [[2200]] droplevel hides, [2201] gear
# tiers (emit_rares) | [[2600]] animated weapons, [2602] remaining rares t5, [[2700]] hide layer 1
# (emit_rare_hide_layer)
RARE_SECTIONS = ("1700", "2300")
RARE_ANIMATED_SECTION = ("2600", "2601")
RARE_HIDE_LAYER_SECTIONS = ("2602", "2800")
RARE_TIER_KEY = re.compile(r"rr(->\w+)?\.t\d")  # base-tier Shows, decided by config.toml [rares]


def emit_rares(cfg):
    """Endgame rares [[1700]]-[2201]: module rares, per-block toggles in modules.toml [rares.blocks].
    After the crafting bases, like league.filter ([1500] economy bases first): a priced base or
    jackpot base is decided before any rare Hide here (id_mods / exotics / flasks / recipes /
    uniques too). The NeverSink base-tier Shows (keys "rr...tN", value "config.toml [rares]")
    are made by rare_tier_blocks from config.toml [rares], not by modules.toml / league_start."""
    if not cfg.get("rares", {}).get("enabled", True):
        return ""
    return (section("Endgame rares (config.toml [rares], modules.toml [rares.blocks])")
            + module_blocks(cfg, "rares", "rare", sections=[RARE_SECTIONS], driven=rare_tier_blocks(cfg),
                            restyle=rare_decorator_style(cfg)))


def rare_decorator_style(cfg):
    """module_blocks restyle: [[1700]] decorator blocks ("decorators->...") get rares.text_color
    instead of NeverSink's yellow (calm look, like the base-tier Shows); none set = no colour."""
    color = cfg.get("rares", {}).get("text_color")

    def restyle(key, style):
        if not key.startswith("decorators->"):
            return style
        return [s for s in style if not s.startswith("SetTextColor")] + ([f"SetTextColor {color}"] if color else [])
    return restyle


def emit_rare_hide_layer(cfg):
    """[[2600]] animated-weapon Shows (RARE_ANIMATED_SECTION, off; NOT turned on by league_start:
    they'd show every normal / magic weapon), [2602] remaining rares (rr.t5) + [[2700]] hide
    layer (normal / magic gear in maps, rares ilvl 68+), module rares. league.filter has
    [[2300]] crafting, [[2400]] chancing, [2601] RGB between emit_rares and this: their emitters
    go before this one ([2601] RGB then sits before [[2600]]: both Shows, only style differs)."""
    if not cfg.get("rares", {}).get("enabled", True):
        return ""
    return (section("Endgame rares: animated weapons, remaining, hide layer (modules.toml [rares.blocks])")
            + module_blocks(cfg, "rares", "rare", sections=[RARE_ANIMATED_SECTION])
            + module_blocks(cfg, "rares", "rare", sections=[RARE_HIDE_LAYER_SECTIONS],
                            driven=rare_tier_blocks(cfg)))


def rare_tier_blocks(cfg):
    """module_blocks driven for the rares "rr" base-tier blocks (poe.ninja has no rare prices):
    one block "rr->amuring.t1" / "rr.t2" ... -> a Show per RARE_GROUPS group whose rares.<group>
    list has that tier, limited to the group's classes with rares.show.<class> true (missing =
    true), ItemLevel >= rares.min_ilvl.<group> (68 floor), styled only by rares.text_color.
    "all" = one Show for every rare of the group, at the first rr block. Generic gear tiers (no
    Class line) never cover jewellery. rares.base_tiers false: none."""
    rc = cfg.get("rares", {})
    show = rc.get("show", {})
    unknown = set(show) - {c for classes in RARE_GROUPS.values() for c in classes}
    if unknown:
        raise ValueError(f"rares.show: unknown class {sorted(unknown)}, use one of {RARE_GROUPS}")
    hide = {c for c, on in show.items() if not on}
    style = [f"SetTextColor {rc['text_color']}"] if rc.get("text_color") else []
    first = next(b["key"] for b in load_module("rares") if RARE_TIER_KEY.fullmatch(b["key"]))

    def emit(b):
        if not RARE_TIER_KEY.fullmatch(b["key"]):
            raise ValueError(f"modules.toml [rares.blocks] {b['key']!r}: only rr tier keys can be config-driven")
        if not rc.get("base_tiers", True):
            return ""
        tier = b["key"].rsplit(".", 1)[1]
        classes = next((re.findall(r'"([^"]+)"', c) for c in b["conds"] if c.startswith("Class")), None)
        out = ""
        for group, group_classes in RARE_GROUPS.items():
            wanted = rc.get(group, [])
            allowed = [c for c in group_classes if c not in hide]
            ilvl = f"ItemLevel >= {max(68, rc.get('min_ilvl', {}).get(group, 68))}"  # NeverSink's endgame floor
            if not wanted or not allowed:
                continue
            if "all" in wanted:
                if b["key"] == first:
                    out += block("Show", [ilvl, "Rarity Rare", f"Class == {q(allowed)}"], style,
                                 f"rare {group}, any base (rares.{group} all)")
                continue
            if classes is None and group == "jewellery":
                continue  # generic gear tiers: armour / weapon bases only
            shown = [c for c in allowed if classes is None or c in classes]
            if tier in wanted and shown:
                conds = [ilvl if c.startswith("ItemLevel >=") else c for c in b["conds"] if not c.startswith("Class")]
                out += block("Show", conds + [f"Class == {q(shown)}"], style,
                             f"rare {group} {b['key']} (NeverSink base tier, module rares)")
        return out
    return emit


# Module jewels (rules/modules/jewels.filter, made with: tools/import_neversink.py jewels
# 2801:2802 2803:2900 --config-key "jewels->generic\.anyrare=config.toml [jewels] show_rare"
# --config-key "jewels->generic\.anymagic=config.toml [jewels] show_magic"; [2802] leveling
# stays with emit_leveling): [2801] special, [2803] abyss, [2804] generic (cobalt / crimson /
# viridian: [jewels] show_rare / show_magic, GENERIC_JEWEL_STYLE, else bottom.filter hides);
# cluster sections [2805] eco-based (enchant x passives x ilvl), [2806] random
JEWEL_SECTIONS = ("2801", "2805")
CLUSTER_SECTIONS = ("2805", "2900")
GENERIC_JEWEL_TOGGLES = {"jewels->generic.anyrare": "show_rare", "jewels->generic.anymagic": "show_magic"}
# Shown jewels (endgame [2804] show_rare / show_magic, campaign show_jewels): icon + beam (no temp beams)
GENERIC_JEWEL_STYLE = {"Rare": ["SetFontSize 45", "PlayEffect Grey", "MinimapIcon 2 Grey Diamond"],
                       "Magic": ["SetFontSize 40", "PlayEffect Grey", "MinimapIcon 2 Grey Diamond"]}
CLUSTER_ECO_SECTION = ("2805", "2806")
# poe.ninja ClusterJewel levelRequired = ilvl bucket start -> bucket end (None = no cap)
CLUSTER_ILVL = {1: 49, 50: 67, 68: 74, 75: 83, 84: None}
# poe.ninja cluster enchant text -> in-game EnchantmentPassiveNode name (= RePoE cluster_jewels
# "name"). Tests check valuable ones against NeverSink's reference + test VERIFIED_CLUSTER_NODES.
CLUSTER_NODES = {
    # Large
    "10% increased Attack Damage": "Attack Damage",
    "10% increased Elemental Damage": "Elemental Damage",
    "10% increased Spell Damage": "Spell Damage",
    "12% increased Attack Damage while Dual Wielding": "Attack Damage while Dual Wielding",
    "12% increased Attack Damage while holding a Shield": "Attack Damage while holding a Shield",
    "12% increased Chaos Damage": "Chaos Damage",
    "12% increased Cold Damage": "Cold Damage",
    "12% increased Damage with Bows, 12% increased Damage Over Time with Bow Skills": "Bow Damage",
    "12% increased Damage with Two Handed Weapons": "Damage with Two Handed Weapons",
    "12% increased Fire Damage": "Fire Damage",
    "12% increased Lightning Damage": "Lightning Damage",
    "12% increased Physical Damage": "Physical Damage",
    "Axe Attacks deal 12% increased Damage with Hits and Ailments, "
    "Sword Attacks deal 12% increased Damage with Hits and Ailments": "Axe and Sword Damage",
    "Claw Attacks deal 12% increased Damage with Hits and Ailments, "
    "Dagger Attacks deal 12% increased Damage with Hits and Ailments": "Dagger and Claw Damage",
    "Minions deal 10% increased Damage": "Minion Damage",
    "Staff Attacks deal 12% increased Damage with Hits and Ailments, "
    "Mace or Sceptre Attacks deal 12% increased Damage with Hits and Ailments": "Mace and Staff Damage",
    "Wand Attacks deal 12% increased Damage with Hits and Ailments": "Wand Damage",
    # Medium
    "10% increased Area Damage": "Area Damage",
    "10% increased Damage over Time": "Damage over Time",
    "10% increased Damage while affected by a Herald": "Damage while you have a Herald",
    "10% increased Effect of Non-Damaging Ailments": "Effect of Non-Damaging Ailments",
    "10% increased Life Recovery from Flasks, 10% increased Mana Recovery from Flasks": "Life and Mana recovery from Flasks",
    "10% increased Projectile Damage": "Projectile Damage",
    "12% increased Brand Damage": "Brand Damage",
    "12% increased Burning Damage": "Fire Damage over Time",
    "12% increased Chaos Damage over Time": "Chaos Damage over Time",
    "12% increased Cold Damage over Time": "Cold Damage over Time",
    "12% increased Physical Damage over Time": "Physical Damage over Time",
    "12% increased Totem Damage": "Totem Damage",
    "12% increased Trap Damage, 12% increased Mine Damage": "Trap and Mine Damage",
    "15% increased Critical Strike Chance": "Critical Chance",
    "6% increased Flask Effect Duration": "Flask Duration",
    "Channelling Skills deal 12% increased Damage": "Channelling Skill Damage",
    "Exerted Attacks deal 20% increased Damage": "Exerted Attack Damage",
    "Minions deal 10% increased Damage while you are affected by a Herald": "Minion Damage while you have a Herald",
    "Minions have 12% increased maximum Life": "Minion Life",
    # Small
    "+12% to Chaos Resistance": "Chaos Resistance",
    "+15% to Cold Resistance": "Cold Resistance",
    "+15% to Fire Resistance": "Fire Resistance",
    "+15% to Lightning Resistance": "Lightning Resistance",
    "+2% Chance to Block Attack Damage": "Chance to Block Attack Damage",
    "+4% chance to Suppress Spell Damage": "Chance to Suppress Spell Damage",
    "15% increased Armour": "Armour",
    "15% increased Evasion Rating": "Evasion",
    "2% Chance to Block Spell Damage": "Chance to Block Spell Damage",
    "2% increased Effect of your Curses": "Curse Effect",
    "4% increased maximum Life": "Life",
    "6% increased Mana Reservation Efficiency of Skills": "Reservation Efficiency",
    "6% increased maximum Energy Shield": "Energy Shield",
    "6% increased maximum Mana": "Mana",
}


def module_cluster_nodes():
    """EnchantmentPassiveNode names module jewels' cluster blocks use (NeverSink's, = confirmed
    in-game names; tests check CLUSTER_NODES against them)."""
    return {n for b in load_module("jewels") for c in b["conds"] if c.startswith("EnchantmentPassiveNode")
            for n in re.findall(r'"([^"]+)"', c)}


def price_clusters(data, cfg, tiers):
    """Confident poe.ninja cluster prices in a shown tier ->
    {(tier, base, passives, ilvl_lo, ilvl_hi, node or None): chaos}. Each price covers only its
    own ilvl bucket. Enchant missing from CLUSTER_NODES: node None (no node condition, blue)."""
    out = {}
    for line in data["stash"].get("ClusterJewel", {}).get("lines", []):
        if line.get("listingCount", 0) < cfg["uniques"]["min_listings"]:
            continue
        tier = tiers.of(line["chaosValue"])
        node = CLUSTER_NODES.get(line["name"])
        if tier == "hide" or hidden(cfg, tier):
            continue
        if node is None:
            tier = "variable"
        lo = line.get("levelRequired", 0)
        key = (tier, line["baseType"], int(line["variant"].split()[0]), lo, CLUSTER_ILVL.get(lo), node)
        out[key] = max(out.get(key, 0), line["chaosValue"])
    return out


def emit_cluster_prices(cfg, tiers, prices):
    """Cluster jewels worth a shown tier (price_clusters), tier style. Before leveling: a
    valuable campaign cluster beats the build module's jewel Hide."""
    groups = {}
    for (tier, base, n, lo, hi, node), _ in prices.items():
        groups.setdefault((tier, base, n, lo, hi), set()).add(node)
    out = ""
    for (tier, base, n, lo, hi), nodes in sorted(groups.items(), key=lambda kv: (tiers.rank(kv[0][0]), -kv[0][3])):
        conds = ["Rarity <= Rare", f"ItemLevel >= {lo}"] + ([f"ItemLevel <= {hi}"] if hi else [])
        conds += [f"EnchantmentPassiveNum {n}", f"BaseType == {q([base])}"]
        if None not in nodes:
            conds.append(f"EnchantmentPassiveNode == {q(nodes)}")
        out += block("Show", conds, style_for(cfg, tier, CLUSTER_SHAPE), f"cluster {tier} (poe.ninja)")
    return section("Cluster jewels: poe.ninja prices (enchant x passives x ilvl bucket)") + out if out else ""


STYLE_RE = re.compile(r"(Set|Play|Minimap|Disable|Enable|Custom)")


def _transform_block(action, conds, style, comment, classes=None, only=None, drop_classes=(), unhide=None,
                     source="NeverSink"):
    """One module block -> filter text ("" = dropped), after the module_blocks options."""
    conds = list(conds)
    if only and only not in conds:
        return ""
    cls = next((c for c in conds if c.startswith("Class")), None)
    if classes is not None and not cls:
        conds.append(f"Class == {q(classes)}")
    elif classes is not None or (drop_classes and cls):
        kept = [c for c in re.findall(r'"([^"]+)"', cls)
                if (classes is None or c in classes) and c not in drop_classes]
        if not kept:
            return ""
        conds = [f"Class == {q(kept)}" if c is cls else c for c in conds]
    if unhide:
        extra = unhide(conds) if action == "Hide" else None
        if extra is None:  # not a Hide, or unhide says keep it hidden: no Show block
            return ""
        return block("Show", conds + extra, style, f"{comment} ({source}, unhidden)")
    return block(action, conds, HIDDEN_STYLE if action == "Hide" else style, f"{comment} ({source})")


MODULES_DIR = ROOT / "rules/modules"


def load_module(name, directory=MODULES_DIR):
    """rules/modules/<name>.filter -> parse_module (PoE2: directory rules/modules_poe2)."""
    return parse_module((directory / f"{name}.filter").read_text(encoding="utf-8"))


def parse_module(text):
    """Module filter text -> [{action, key, section, conds, style, tags}]. Our own rule
    files (first made by tools/import_neversink.py). Block header "Show # <key> [tags]" (tags =
    NeverSink strictness markers "%D3" / "%H2" / "!utility_layer"), section lines
    "# [NNNN] title"; on/off per key lives in modules.toml (PoE2: modules_poe2.toml)."""
    out, section, cur = [], None, None
    for line in text.splitlines():
        h = re.match(r"#\s+\[\[?(\d{4})\]\]?", line)
        m = re.match(r"(Show|Hide)\s+#\s*(\S+)(.*)", line)
        if h:
            section, cur = h.group(1), None
        elif m:
            cur = {"action": m.group(1), "key": m.group(2), "section": section, "conds": [], "style": [],
                   "tags": m.group(3).split()}
            out.append(cur)
        elif cur is not None and line.strip() and not line.lstrip().startswith("#"):
            l = line.strip()
            cur["style" if STYLE_RE.match(l) else "conds"].append(l)
        elif not line.strip():
            cur = None
    return out


def module_on(cfg, name, key):
    """Block toggle from modules.toml [<name>.blocks] (league_start: apply_league_start has set
    the off Shows true, LS_KEEP_SECTIONS aside). Missing key = error (no hidden settings)."""
    blocks = cfg["modules"][name]["blocks"]
    if key not in blocks:
        raise KeyError(f"modules.toml [{name}.blocks] has no {key!r} (run tools/import_neversink.py)")
    return blocks[key]


def config_toggle(cfg, key, on):
    """modules.toml value "config.toml [<section>]" for a key in MODULE_CONFIG_TOGGLES[<section>]
    -> that config key's bool (missing key = error: no hidden settings); else unchanged."""
    m = re.fullmatch(r"config\.toml \[(\w+)\]", on) if isinstance(on, str) else None
    keys = MODULE_CONFIG_TOGGLES.get(m.group(1), {}) if m else {}
    return cfg[m.group(1)][keys[key]] if key in keys else on


def module_blocks(cfg, name, label, sections=None, classes=None, only=None, drop_classes=(), unhide=None,
                  extra_conds=None, driven=None, restyle=None, keep=None, basetypes=None):
    """Filter text of rules/modules/<name>.filter blocks turned on in modules.toml.
    sections: (first, after) ranges of section numbers to keep (None = all). extra_conds:
    {key: [condition lines]} added to that block (e.g. "Rarity <= Rare": uniques stay priced).
    driven: block -> text, for keys whose modules.toml value is a string (set by config.toml,
    e.g. rares rr tiers; importer --config-key); such a key without driven = error.
    restyle: (key, style lines) -> style lines (e.g. rares decorators: our text colour).
    Borders / backgrounds were dropped by the importer; Hide blocks get HIDDEN_STYLE.
    classes: keep only these in a block's `Class ==` line (no Class line: add one), drop blocks
    left with none. drop_classes: remove these from `Class ==`, drop blocks left with none.
    only: keep blocks with this condition line (e.g. "FracturedItem True").
    unhide: conds -> extra conds; Hide blocks become Show with their own style + those conds
    (None = that Hide stays hidden: no block), Show blocks are dropped (the user turning a hidden FilterBlade rule on).
    keep: block -> bool, only those blocks (e.g. emit_flasks splits the module in two).
    basetypes: {key: names} replaces that block's `BaseType ==` line ([] = block dropped, None =
    line dropped: any base; e.g. [overquality] rank lists, [gear_special] perfection_armour)."""
    out = ""
    for b in load_module(name):
        if keep and not keep(b):
            continue
        if sections and not any(first <= (b["section"] or "") < after for first, after in sections):
            continue
        on = module_on(cfg, name, b["key"])
        on = config_toggle(cfg, b["key"], on)
        if isinstance(on, str):
            if driven is None:
                raise ValueError(f"modules.toml [{name}.blocks] {b['key']!r}: string value needs an emitter")
            out += driven(b)
            continue
        if not on:
            continue
        conds = b["conds"] + (extra_conds or {}).get(b["key"], [])
        if basetypes and b["key"] in basetypes:
            names = basetypes[b["key"]]
            if names is not None and not names:
                continue
            conds = [c for c in conds if not c.startswith("BaseType")] + ([f"BaseType == {q(names)}"] if names else [])
        style = restyle(b["key"], b["style"]) if restyle else b["style"]
        out += _transform_block(b["action"], conds, style, f"{label} {b['key']}",
                                classes, only, drop_classes, unhide, source=f"module {name}")
    return out


def emit_jewels(cfg):
    """Normal / magic / rare jewels: module jewels ([2801] special corrupted / uncorrupted-mod,
    [2803] abyss, [2804] generic, [2805]-[2806] cluster eco tiers + random), per-block toggles in
    modules.toml. league.filter's place: after rares ([[2700]]), before heist. Priced cluster
    jewels (emit_cluster_prices), priced jewel bases (emit_crafting_bases), ID-mod / fractured
    jewels and the campaign ([2802], emit_leveling) are decided earlier.
    league_start turns every Show on except [2805] (LS_KEEP_SECTIONS): its off blocks are FilterBlade's empty
    economy tiers (no EnchantmentPassiveNode list) that would tink every enchant."""
    if not cfg.get("jewels", {}).get("enabled", True):
        return ""
    eco, rest = CLUSTER_ECO_SECTION, (CLUSTER_ECO_SECTION[1], CLUSTER_SECTIONS[1])

    def generic(b):  # [2804] Hide -> Show when [jewels] show_rare / show_magic (missing key = error)
        opt = GENERIC_JEWEL_TOGGLES.get(b["key"])
        if opt is None:
            raise ValueError(f"modules.toml [jewels.blocks] {b['key']!r}: string value needs an emitter")
        if not cfg["jewels"][opt]:
            return ""  # bottom.filter hides
        return block("Show", b["conds"], GENERIC_JEWEL_STYLE["Rare" if opt == "show_rare" else "Magic"],
                     f"jewel {b['key']} ([jewels] {opt})") + "\n"
    return (section("Jewels + cluster jewels (config.toml [jewels], modules.toml [jewels.blocks])")
            + module_blocks(cfg, "jewels", "jewel", sections=[JEWEL_SECTIONS], driven=generic)
            + module_blocks(cfg, "jewels", "cluster", sections=[eco])
            + module_blocks(cfg, "jewels", "cluster", sections=[rest]))


# NeverSink [[2900]] heist cloak / brooch / gear / tool (module rules/modules/heist.filter, made
# with: tools/import_neversink.py heist 2900:3000)


def emit_heist(cfg):
    """Normal / magic / rare heist gear by base tier: module heist, per-block toggles in
    modules.toml. Right after jewels as in league.filter ([[2900]] after [2806]); priced
    crafting bases and ID-mod / fractured heist gear are decided earlier."""
    if not cfg.get("heist", {}).get("enabled", True):
        return ""
    return (section("Heist gear (config.toml [heist], modules.toml [heist.blocks])")
            + module_blocks(cfg, "heist", "heist"))


# Module misc (rules/modules/misc.filter, made with: tools/import_neversink.py misc 0100:0300
# 4500:4800 4900:5000 --config-key "6l\..*=config.toml show_6_links (rules/top.filter)"):
# [0100] 6L overrides (FilterBlade off; config.toml show_6_links decides, rules/top.filter's
# 6L Show is a superset, so no module block is emitted), [0200] gold stack tiers, [4500] heist
# targets, [4600] enshrouded gear, [4700] idols, [4900] Maven's invitations / lab / incursion items
GOLD_SECTION = ("0200", "0300")
MISC_BEFORE_UNIQUES = ("4500", "4800")
MISC_AFTER_UNIQUES = ("4900", "5000")
GOLD_MAP_AREA_LEVEL = 68  # show_gold: stacks below gold_min_stack hidden from this area level (maps)
GOLD_FONT_SIZE = 18  # smallest font the game allows; every gold Show uses it (maximize_item_sizes skips gold)
GOLD_BACKGROUND = "SetBackgroundColor 0 0 0 0"  # gold label fully transparent (no game default dark box)
GOLD_SMALL_STYLE = [f"SetFontSize {GOLD_FONT_SIZE}", GOLD_BACKGROUND, "SetTextColor gold", "DisableDropSound True"]


def emit_gold(cfg):
    """Gold. config.toml show_gold false = one Hide for all gold. true = gold_min_stack decides
    (one source of truth): module misc [0200] keys are config-driven (modules.toml string
    values): gold.stack3 = its style for StackSize >= gold_min_stack, gold.anyother = one Hide
    for smaller stacks in maps (AreaLevel >= GOLD_MAP_AREA_LEVEL; none with gold_min_stack <= 1 or show_small_gold,
    e.g. league start: small stacks keep the small look), the other
    tier Hides emit nothing; then a small Show for the rest (campaign gold, show_gold's promise).
    Independent of [misc] enabled. League.filter's place ([[0200]] first): before
    rules/top.filter, no earlier block matches gold."""
    out = section("Gold (config.toml show_gold, gold_min_stack)")
    if not cfg.get("show_gold"):
        return out + block("Hide", ['BaseType == "Gold"'], HIDDEN_STYLE, "gold (show_gold = false)")
    n = cfg["gold_min_stack"]

    def driven(b):
        if b["key"] == "gold.stack3":
            style = [f"SetFontSize {GOLD_FONT_SIZE}" if l.startswith("SetFontSize") else l
                     for l in b["style"] if not l.startswith("SetBackgroundColor")] + [GOLD_BACKGROUND]
            return block("Show", [f"StackSize >= {n}", 'BaseType == "Gold"'], style,
                         f"gold >= {n} (config.toml gold_min_stack)")
        if b["key"] == "gold.anyother" and n > 1 and not cfg.get("show_small_gold"):
            return block("Hide", ['BaseType == "Gold"', f"AreaLevel >= {GOLD_MAP_AREA_LEVEL}"], HIDDEN_STYLE,
                         f"gold < {n} in maps (config.toml gold_min_stack)")
        return ""
    out += module_blocks(cfg, "misc", "misc", sections=[GOLD_SECTION], driven=driven)
    return out + block("Show", ['BaseType == "Gold"'], GOLD_SMALL_STYLE, "gold: rest (campaign)")


def emit_misc(cfg, sections):
    """Module misc questlike / event items, league.filter's style, per-block toggles in
    modules.toml. MISC_BEFORE_UNIQUES ([4500] heist targets, [4600] enshrouded gear, [4700]
    idols): after special maps, before uniques as in league.filter ("override uniques": a
    heist target / enshrouded item of unique rarity keeps this look; neither is priced by
    poe.ninja; only Shows, so no jackpot is hidden). MISC_AFTER_UNIQUES ([4900] Maven's
    invitations, lab / incursion items): right after uniques; a poe.ninja price or the
    unpriced Map Fragments / Misc Map Items fallback (stackables) decides invitations / Maven's
    currency first."""
    if not cfg.get("misc", {}).get("enabled", True):
        return ""
    return (section(f"Misc items [{sections[0]}]-[{sections[1]}] (config.toml [misc], modules.toml [misc.blocks])")
            + module_blocks(cfg, "misc", "misc", sections=[sections]))


# Flask / tincture rules: [0803] identified magic mods, [1303] fractured (flask classes only),
# [[2500]] endgame quality / ilvl ([2501]-[2505])
#   (module rules/modules/flasks.filter, made with: tools/import_neversink.py flasks 0803:0900 1303:1304 2500:2600
#    --config-key "endgame(tinctures|flasks)\.(overqual\w*|any20qualflask)=config.toml [overquality]")
FLASK_CLASSES = ["Hybrid Flasks", "Life Flasks", "Mana Flasks", "Utility Flasks", "Tinctures"]


def flask_says_more(b):
    """Flask module block that says more than the base: good identified mods [0803], fractured
    [1303], overquality / corrupted 30% (modules.toml value "config.toml [overquality]")."""
    return b["section"] in ("0803", "1303") or b["key"] in OVERQUALITY_TOGGLES         or "overqual" in b["key"]


def emit_flasks(cfg, plain=False):
    """Normal / magic flasks + tinctures, module flasks, Class narrowed to FLASK_CLASSES (its
    [1303] copy = the flask part of league.filter's fractured rules; gear part: emit_exotics).
    plain=False: flask_says_more blocks (good mods, fractured, overquality), before priced bases.
    plain=True: the rest (ilvl 82-85, low quality, any utility / tincture in maps), after
    emit_priced_bases_first: a poe.ninja-priced flask base (Silver Flask ilvl 85) keeps its price
    tier, cheap ones fall to these. Both before vendor recipes: a 21% flask keeps this look over
    glassblower. Flask classes overlap no id_mods / exotics block.
    [flasks] show_plain false: no plain blocks, a plain flask base is decided by its price only
    (like a crafting base: cheap / unpriced fall to the later Hides)."""
    fl = cfg.get("flasks", {})
    if not fl.get("enabled", True) or (plain and not fl.get("show_plain", True)):
        return ""
    out = module_blocks(cfg, "flasks", "flask", classes=FLASK_CLASSES,
                        keep=lambda b: flask_says_more(b) != plain)
    title = "plain bases, after priced bases" if plain else "mods / fractured / quality"
    return section(f"Flasks + tinctures: {title} (config.toml [flasks], modules.toml [flasks.blocks])") + out if out else ""


# Exotic gear rules: [0902] memory strands, [[1100]] exotic mods (1101 veiled, 1102 incursion,
# 1103 necropolis, 1104 bestiary, 1105 delve / mercenary / warband / essence), [[1200]] exotic
# classes (imbued, synthesised, voidstones, trinkets, fishing rods, pieces, quest items) +
# [1201] relics, [[1300]] variations (1301 corruptions, 1302 abyss sockets, 1303 fractured
# (flasks: emit_flasks), 1304 enchanted, 1305 crucible)
#   (module rules/modules/exotics.filter, made with: tools/import_neversink.py exotics 0902:1000 1100:1400)
# Blocks with no Rarity line that can catch a poe.ninja-priced unique: unique stays priced
# (emit_uniques, jackpot / blue rules), the block shows only normal / magic / rare.
EXOTIC_NOT_UNIQUE = {"artefact->misc.anyimbued": ["Rarity <= Rare"],
                     "artefact->misc.fishingrods": ["Rarity <= Rare"]}


def emit_exotics(cfg, talismans=""):
    """Memory-stranded, exotic-mod, exotic-class and exotic-variation gear: module exotics
    (league.filter's own style). After id_mods like league.filter ([0600]-[0802] before
    [0902]-[1300]; [1000] corrupted id mods never meet [0902], which needs Corrupted False),
    before vendor recipes / crafting bases / stackables / uniques / rares: all Shows, nothing
    priced loses (EXOTIC_NOT_UNIQUE; [1201] relics are normal / magic / rare only).
    talismans (emit_talismans text) goes right before the anointed-amulet blocks (end if off)."""
    if not cfg.get("exotics", {}).get("enabled", True):
        return section("Talismans (config.toml [content.bestiary] talismans)") + talismans if talismans else ""
    out = module_blocks(cfg, "exotics", "exotic", drop_classes=FLASK_CLASSES, extra_conds=EXOTIC_NOT_UNIQUE)
    head, sep, tail = out.partition("Show # exotic exotic->enchanted.anointedamulets")
    out = head + talismans + sep + tail
    return section("Exotic gear (config.toml [exotics], modules.toml [exotics.blocks])") + out


# NeverSink identified-mod sections: [[0600]] combinations (+ [0617] veiled exceptions),
# [[0700]] dual mods, [0801] top value, [0802] uncorrupted mods ([0803] flasks: emit_flasks),
# [[1000]] corrupted items with good mods
#   (module rules/modules/id_mods.filter, made with: tools/import_neversink.py id_mods 0600:0803 1000:1100)


def emit_id_mods(cfg):
    """Identified magic / rare gear with good mods (HasExplicitMod): module id_mods, per-block
    toggles in modules.toml. Before vendor recipes / crafting bases / rares, like league.filter:
    a good identified rare beats any base Hide."""
    if not cfg.get("id_mods", {}).get("enabled", True):
        return ""
    return (section("Identified mods (config.toml [id_mods], modules.toml [id_mods.blocks])")
            + module_blocks(cfg, "id_mods", "idmod", drop_classes=FLASK_CLASSES))


# Module maps (rules/modules/maps.filter, made with: tools/import_neversink.py maps 0301:0302
# 3201:3300 3302:3600): [0301] influenced (Zana / Elder / conqueror), [3201] unique maps
# (uniques.hide_maps), [3202]-[3204] Valdo / Nightmare / Shaper guardian / blighted / Vaal
# Temple / enchanted / implicit, [3302] normal map tiers (Hide in league.filter), [[3400]]
# pseudo-map items (heist contracts / blueprints, logbooks, charts, sanctum research),
# [[3500]] misc map items (reliquary keys, Chronicle of Atzoatl, Inscribed Ultimatum)
# [3202] Valdo / Nightmare / Shaper guardian first: shown even corrupted ([maps] corrupted_min_tier)
NIGHTMARE_MAP_SECTION = ("3202", "3203")
SPECIAL_MAP_SECTIONS = [("0301", "0302"), ("3203", "3300")]
UNIQUE_MAP_SECTION = ("3201", "3202")
MAP_PROGRESSION_SECTION = ("3302", "3400")
MAP_ITEM_SECTION = ("3400", "3600")
# module maps Hide blocks a config.toml toggle overrides: key -> cfg -> True = block off
MAP_ITEM_CONFIG_OVERRIDES = {
    "heist->contract.handpicked": lambda cfg: cfg.get("show_contracts", True),
    "exoticmap->sanctum.ilvl83": lambda cfg: not cfg.get("hide_forbidden_tome", False),
    "exoticmap->sanctum.any": lambda cfg: not cfg.get("hide_forbidden_tome", False),
}


def tier_ranges(tiers):
    """[1, 2, 3, 7, 9, 10] -> [(1, 3), (7, 7), (9, 10)]: contiguous runs, one Hide each."""
    out = []
    for t in sorted(set(tiers)):
        if out and t == out[-1][1] + 1:
            out[-1] = (out[-1][0], t)
        else:
            out.append((t, t))
    return out


def emit_special_maps(cfg):
    """Special maps + map-like items: module maps, league.filter's own style, per-block toggles
    in modules.toml. Before uniques: league.filter puts them first; a Valdo / implicit map
    can't fall into a unique Hide, unique contracts / blueprints keep their [3400] look.
    uniques.hide_maps: [3201] (corrupted unique maps shown, rest hidden).
    [maps] corrupted_min_tier: after Valdo / Nightmare / Shaper guardian, Hide non-unique
    corrupted maps below that tier (before influenced / blighted / 8-mod / implicit / progression).
    [maps] blighted_hide_tiers: Hide blighted (not blight-ravaged) maps of those tiers, same spot.
    [3400]-[3500] map items: after stackables, so a poe.ninja price (Voidborn Reliquary Key) or
    the unpriced Map Fragments / Misc Map Items fallback (blue) decides first; show_contracts /
    hide_forbidden_tome Hides come before everything, and those toggles beat the module's own
    contract / Sanctum Research Hides (MAP_ITEM_CONFIG_OVERRIDES)."""
    if not cfg.get("maps", {}).get("enabled", True):
        return ""
    mod = lambda *secs: module_blocks(cfg, "maps", "map", sections=list(secs))
    out = mod(UNIQUE_MAP_SECTION) if cfg["uniques"].get("hide_maps") else ""
    out += mod(NIGHTMARE_MAP_SECTION)
    min_tier = cfg["maps"].get("corrupted_min_tier", 0)
    if min_tier:
        out += block("Hide", ["Rarity <= Rare", 'Class == "Maps"', "Corrupted True",
                              f"MapTier < {min_tier}"], HIDDEN_STYLE, "corrupted map below [maps] corrupted_min_tier")
    for lo, hi in tier_ranges(cfg["maps"].get("blighted_hide_tiers", [])):
        out += block("Hide", ["Rarity <= Rare", 'Class == "Maps"', "BlightedMap True", "UberBlightedMap False",
                              f"MapTier >= {lo}", f"MapTier <= {hi}"], HIDDEN_STYLE,
                     "blighted map tier in [maps] blighted_hide_tiers")
    out += mod(*SPECIAL_MAP_SECTIONS)
    # explicit config.toml toggles beat module defaults: show_contracts = true drops the plain
    # contract Hide, hide_forbidden_tome = false drops the Sanctum Research (tome) Hides
    blocks = dict(cfg["modules"]["maps"]["blocks"])
    for key, beaten in MAP_ITEM_CONFIG_OVERRIDES.items():
        if key in blocks and beaten(cfg):
            blocks[key] = False
    items_cfg = {**cfg, "modules": {**cfg["modules"], "maps": {**cfg["modules"]["maps"], "blocks": blocks}}}
    # Reliquary keys (relickeys*): config.toml always_top_classes, emit_pinned_stackables
    out += module_blocks(items_cfg, "maps", "map", sections=[MAP_ITEM_SECTION], driven=module_elsewhere)
    return section("Special maps + map items (config.toml [maps], modules.toml [maps.blocks])") + out


# Shown normal map tiers (T1-T16, not special): grey beam + grey icon (user rule), stock
# NeverSink's sound / icon size per tier group (league.filter dropped them, its tier blocks are
# Hides). Special maps (Valdo, blighted, influenced, 8-mod ...) keep their own style.
# Key "maps.maps_<group>_t<N>" -> group letter.
MAP_TIER_ALERTS = {
    "a": ["PlayAlertSound 5 300", "PlayEffect Grey", "MinimapIcon 1 Grey Square"],
    "b": ["PlayAlertSound 5 300", "PlayEffect Grey", "MinimapIcon 1 Grey Square"],
    "c": ["PlayAlertSound 4 300", "PlayEffect Grey", "MinimapIcon 1 Grey Square"],
    "d": ["PlayAlertSound 4 300", "PlayEffect Grey", "MinimapIcon 2 Grey Square"],
}


def map_tier_alert_style(cfg):
    """module_blocks restyle for unhidden [3302] tiers: [maps] text_color (faded: no price, reads
    below minor tier white) + stock alerts."""
    text = cfg.get("maps", {}).get("text_color", "faded")

    def restyle(key, style):
        m = re.search(r"maps_([a-d])_t\d+", key)
        if not m:
            return style
        drop = ("PlayAlertSound", "PlayEffect", "MinimapIcon", "SetTextColor")
        return ([s for s in style if not s.strip().startswith(drop)] + [f"SetTextColor {text}"]
                + MAP_TIER_ALERTS[m.group(1)])
    return restyle


def emit_map_progression(cfg):
    """Normal maps by tier ([maps] progression): "all" = module maps' [3302] tier Hides turned
    to Show, "auto" = a tier shows while AreaLevel <= its own level (campaign: all, T5 map: T5+),
    "none" = as league.filter (all hidden). A tier Hide toggled off in modules.toml: that tier
    falls to [3302] restex (pink Show). min_tier: tiers below it stay hidden ("all" / "auto"),
    except extra_tiers (listed tiers shown anyway).
    After uniques: unique maps are priced there."""
    if not cfg.get("maps", {}).get("enabled", True):
        return ""
    mode = cfg["maps"].get("progression", "none")
    min_tier = cfg["maps"].get("min_tier", 0)
    extra_tiers = set(cfg["maps"].get("extra_tiers", []))
    tier = lambda conds: int(re.search(r"\d+", next(c for c in conds if c.startswith("MapTier"))).group())
    extra = {"all": lambda conds: [], "auto": lambda conds: [f"AreaLevel <= {67 + tier(conds)}"]}.get(mode)
    unhide = extra and (lambda conds: None if tier(conds) < min_tier and tier(conds) not in extra_tiers
                        else extra(conds))
    secs = [MAP_PROGRESSION_SECTION]
    out = module_blocks(cfg, "maps", "map", sections=secs, unhide=unhide,
                        restyle=map_tier_alert_style(cfg)) if unhide else ""
    return (section(f"Normal maps: tiers (module maps [3302], [maps] progression = {mode})")
            + out + module_blocks(cfg, "maps", "map", sections=secs))


def alt_gem(line):
    """Alternate gem (transfigured "Cyclone of Tumult", "Heavy Strike of Trarthus"): poe.ninja's
    name is no BaseType, the trade type has a discriminator (alt_x/y/z) on the plain gem. Or
    a baseType unlike the name: 3.28 Vaal transfigured "Vaal Fireball (Fireball of Radiation)"
    can come with tradeFilter null."""
    kind = ((line.get("tradeFilter") or {}).get("query") or {}).get("type")
    return (isinstance(kind, dict) and bool(kind.get("discriminator"))) \
        or bool(line.get("baseType") and line["baseType"] != line["name"])


def alt_gem_bases(data):
    """{alternate gem name: plain gem BaseType} from the SkillGem feed's tradeFilter (or baseType)."""
    out = {}
    for l in data["stash"].get("SkillGem", {}).get("lines", []):
        if alt_gem(l):
            kind = ((l.get("tradeFilter") or {}).get("query") or {}).get("type")
            out[l["name"]] = kind["option"] if isinstance(kind, dict) and kind.get("option") else l["baseType"]
    return out


def gem_lines(data):
    """poe.ninja SkillGem lines without alternate gems (their name in a BaseType makes the game
    reject the filter). ImbuedGem is never fetched (SKIPPED_TYPES: can't drop)."""
    alts = alt_gem_bases(data)
    return [l for l in data["stash"].get("SkillGem", {}).get("lines", []) if l["name"] not in alts]


# poe.ninja's minimum gem listing price: a plain vendor gem here is listing noise, not value
NINJA_FLOOR_CHAOS = 1

# Drop-only gems poe.ninja doesn't tag gemKind "exceptional" (Pacts, Awakened, old exceptional
# supports): NeverSink [2801] "$type->gems->exceptional" BaseType list (reference/regular-neversink.filter).
EXCEPTIONAL_GEMS = frozenset((
    "Annihilation Support", "Awakened Empower Support", "Awakened Enhance Support", "Awakened Enlighten Support",
    "Bloodsoaked Banner Support", "Bonespire Support", "Cast on Ward Break Support", "Communion Support",
    "Companionship Support", "Congregation Support", "Cooldown Recovery Support", "Coursing Current Support",
    "Crystalfall Support", "Cull the Weak Support", "Divine Sentinel Support", "Eclipse Support",
    "Eldritch Blasphemy Support", "Empower Support", "Enhance Support", "Enlighten Support", "Fissure Support",
    "Foulgrasp Support", "Frostmage Support", "Gluttony Support", "Greater Ancestral Call Support",
    "Greater Chain Support", "Greater Devour Support", "Greater Fork Support", "Greater Kinetic Instability Support",
    "Greater Multistrike Support", "Greater Spell Cascade Support", "Greater Spell Echo Support",
    "Greater Unleash Support", "Hexpass Support", "Hextoad Support", "Hiveborn Support", "Invention Support",
    "Invert the Rules Support", "Item Quantity Support", "Lethal Dose Support", "Machinations Support",
    "Overheat Support", "Overloaded Intensity Support", "Pacifism Support", "Pact of Beidat", "Pact of Ghorr",
    "Pact of K'Tash", "Pact of Lycia", "Pyre Support", "Scornful Herald Support", "Transfusion Support",
    "Unholy Trinity Support", "Vaal Sacrifice Support", "Vaal Temptation Support", "Void Shockwave Support",
    "Voidstorm Support"))


def exceptional_gem(line):
    """Drop-only gem (never vendor-sold): poe.ninja gemKind "exceptional", NeverSink's
    exceptional list or Awakened."""
    return ((line.get("metadata") or {}).get("gemKind") == "exceptional"
            or line["name"] in EXCEPTIONAL_GEMS or line["name"].startswith("Awakened "))


def plain_level1_gem(line):
    """[gems] hide_level1 target: level 1, 0% quality, uncorrupted, not exceptional = the
    vendor sells it."""
    return (line.get("gemLevel", 1) == 1 and not line.get("gemQuality") and not line.get("corrupted")
            and not exceptional_gem(line))


def never_hide_gem(line, cfg):
    """Confidently listed (uniques.min_listings) at >= [uniques] never_hide_tier: never hidden,
    not even by [gems] hide_level1 (e.g. a plain level 1 gem the vendor no longer sells)."""
    return (line.get("listingCount", 0) >= cfg["uniques"]["min_listings"]
            and line["chaosValue"] >= cfg["tiers"][cfg["uniques"]["never_hide_tier"]])


def price_gems(data, cfg, tiers, divine=None):
    """Gem prices per poe.ninja variant (level / quality / corrupted: "1", "1/20", "20/20",
    "21/23c", ...), like NeverSink's leveled / quality gem rules ->
    {(tier, level, quality, corrupted): {names}}. Thin listings (below uniques.min_listings)
    are blue, except plain vendor gems (levels 1-19, 0 quality, uncorrupted; not exceptional_gem),
    which are hidden when thin or at poe.ninja's 1c floor (NINJA_FLOOR_CHAOS: the minimum
    listing price, ~600 plain level 1 gems sit there, vendor sells them) and use their price
    tier when confidently listed above it. [gems] hide_level1: plain_level1_gem variants never
    get a price Show (emit_level1_gem_hide hides them), except a never_hide_gem. Price is capped by gem_caps (never above a confidently listed better variant); a thin
    variant capped into a hidden tier hides. Alternate gems (gem_lines) are skipped: their name in
    BaseType makes the game reject the filter, see emit_gems. A gem_special variant priced below
    min_tier stays hidden before emit_gem_fallback's blue catch-all."""
    min_rank = min_shown_rank(cfg, tiers, cfg.get("gems", {}).get("min_tier", "minor"))
    min_listings = cfg["uniques"]["min_listings"]
    hide_level1 = cfg.get("gems", {}).get("hide_level1")
    out = {}
    lines = [l for l in gem_lines(data) if l.get("listingCount", 0)]
    caps = gem_caps(lines, min_listings)
    for i, line in enumerate(lines):
        cap = caps.get(i, math.inf)
        thin = line["listingCount"] < min_listings
        tier = tiers.of(min(line["chaosValue"], cap))
        level, quality = line.get("gemLevel", 1), line.get("gemQuality") or 0
        ordinary_vendor_gem = (
            1 <= level < 20 and quality == 0 and not line.get("corrupted")
            and not exceptional_gem(line)
        )
        if (hide_level1 and plain_level1_gem(line) and not never_hide_gem(line, cfg)) or \
                (ordinary_vendor_gem and (thin or line["chaosValue"] <= NINJA_FLOOR_CHAOS)):
            tier = "hide"
        elif tiers.rank(tier) > min_rank or hidden(cfg, tier):
            # confident price, or a thin one capped by a confident better variant
            tier = "hide" if not thin or cap < line["chaosValue"] else "variable"
        elif thin:
            tier = "variable"
        if hidden(cfg, tier):
            tier = "hide"
        if tier != "hide" or gem_special(level, quality):
            out.setdefault((tier, level, quality, bool(line.get("corrupted"))), set()).add(line["name"])
    return out


def gem_caps(lines, min_listings):
    """Price cap per line index: the cheapest confident (min_listings) strictly better variant
    of the same gem (same corrupted, level >= and quality >=). Nobody pays more for a worse gem
    (poe.ninja's "20" Spectral Helix at 1 div vs 9c for 20/20 = price-fix listings)."""
    key = lambda l: (l["name"], bool(l.get("corrupted")))
    lq = lambda l: (l.get("gemLevel", 1), l.get("gemQuality") or 0)
    better = {}
    for b in lines:
        if b["listingCount"] >= min_listings:
            better.setdefault(key(b), []).append(b)
    caps = {}
    for i, a in enumerate(lines):
        (la, qa) = lq(a)
        vals = [b["chaosValue"] for b in better.get(key(a), [])
                if b is not a and lq(b) != (la, qa) and lq(b)[0] >= la and lq(b)[1] >= qa]
        if vals:
            caps[i] = min(vals)
    return caps


# poe.ninja gem quality variants: 0 (= below 20), 20, 23
GEM_QUALITY_STEPS = (0, 20, 23)


def gem_special(level, quality):
    """Level 21+ / quality 21+: corruption outcomes, probably valuable even unpriced (blue)."""
    return level >= 21 or quality >= 21


def gem_variant_conds(level, quality, corrupted):
    """Conditions matching exactly one poe.ninja gem variant (quality up to the next step)."""
    nxt = [s for s in GEM_QUALITY_STEPS if s > quality]
    return (['Class == "Skill Gems" "Support Gems"', f"Corrupted {corrupted}", f"GemLevel == {level}"]
            + ([f"Quality >= {quality}"] if quality else []) + ([f"Quality < {nxt[0]}"] if nxt else []))


def emit_gems(cfg, tiers, prices):
    """Gems worth a shown tier as they drop (price_gems). Emitted before rules/top.filter
    (20% / Awakened Shows) and vendor recipes, so a priced gem keeps its tier (recipe = floor);
    rules/bottom.filter hides the rest. Best tier first, then most specific variant (a gem matches every variant at or below
    its level / quality: a worse variant can only show it, never hide it). Then NeverSink's
    "TransfiguredGem True" show, blue: the filter BaseType is the plain gem."""
    out = ""
    order = lambda kv: (tiers.rank(kv[0][0]), -kv[0][1], -kv[0][2], kv[0][3])
    for (tier, level, quality, corrupted), names in sorted(prices.items(), key=order):
        if tier == "hide":
            continue
        conds = ['Class == "Skill Gems" "Support Gems"', f"Corrupted {corrupted}"] \
            + ([f"GemLevel >= {level}"] if level > 1 else []) + ([f"Quality >= {quality}"] if quality else [])
        label = f"{level}" + (f"/{quality}" if quality else "") + ("c" if corrupted else "")
        out += block("Show", conds + [f"BaseType == {q(names)}"], style_for(cfg, tier, GEM_SHAPE),
                     f"gem {tier} {label} (poe.ninja)")
    out += block("Show", ['Class == "Skill Gems" "Support Gems"', "TransfiguredGem True"],
                 style_for(cfg, "variable", GEM_SHAPE), "transfigured gem (value per transfiguration)")
    return section("Gems: poe.ninja prices per level / quality") + out


def emit_gem_fallback(cfg, prices):
    """Level 21+ / quality 21+ gems no price block showed (gem_special): blue "variable"
    (probably valuable, no exact price: low trade volume, unlisted variant). Exact variants
    priced confidently into a hidden tier are hidden first (explicit hide wins). After the
    vendor recipes (gemcutter = floor) and top's 20% Show."""
    if hidden(cfg, "variable"):
        return ""
    out = ""
    for (tier, level, quality, corrupted), names in sorted(prices.items(), key=lambda kv: kv[0][1:]):
        if tier == "hide":
            out += block("Hide", gem_variant_conds(level, quality, corrupted) + [f"BaseType == {q(names)}"],
                         HIDDEN_STYLE, f"gem {level}/{quality}{'c' if corrupted else ''} priced below gems.min_tier")
    for cond in ("GemLevel >= 21", "Quality >= 21"):
        out += block("Show", ['Class == "Skill Gems" "Support Gems"', cond], style_for(cfg, "variable", GEM_SHAPE),
                     f"gem {cond}: no confident price (variable)")
    return section("Gems: blue fallback for unpriced level / quality 21+") + out


def emit_level1_gem_hide(cfg, data, divine=None):
    """[gems] hide_level1: plain level 1 / under 20% / uncorrupted gems the vendor sells
    (plain_level1_gem names from the poe.ninja feed, minus never_hide_gem ones: never hidden)
    hidden, also with [gems] show_all. 1-19%
    ones only show via the gemcutter recipe (earlier, so recipe off = hidden). After
    the campaign rules ([leveling] show_gems wins) and every price / top.filter / recipe Show;
    gems poe.ninja doesn't list aren't named, so emit_unknown_gems still shows them blue."""
    if not cfg.get("gems", {}).get("hide_level1"):
        return ""
    lines = gem_lines(data)
    keep = {l["name"] for l in lines if plain_level1_gem(l) and never_hide_gem(l, cfg)}
    names = sorted({l["name"] for l in lines if plain_level1_gem(l)} - keep)
    if not names:
        return ""
    return section("Gems: plain level 1 vendor gems hidden ([gems] hide_level1)") + block(
        "Hide", ['Class == "Skill Gems" "Support Gems"', "GemLevel == 1", "Quality < 20", "Corrupted False",
                 "TransfiguredGem False", f"BaseType == {q(names)}"], HIDDEN_STYLE, "gems.hide_level1")


def emit_unknown_gems(cfg, data):
    """Gems poe.ninja doesn't list at all (new exceptional supports, e.g. league.filter [3001]
    Item Quantity / Transfusion Support): blue "variable" instead of rules/bottom.filter's gem
    Hide (probably valuable, no price). Gems poe.ninja knows that no price / top.filter /
    leveling rule showed are hidden here first (same as bottom.filter; [gems] show_all: not,
    its gem Hide turns Show too). No gem feed (fetch failed / tests): nothing. Last before
    rules/bottom.filter, so every gem rule above wins."""
    if hidden(cfg, "variable"):
        return ""
    gems = 'Class == "Skill Gems" "Support Gems"'
    known = sorted({l["name"] for l in gem_lines(data)})
    if not known:  # no gem feed: nothing to tell unlisted gems apart, bottom.filter decides
        return ""
    out = ""
    if not cfg.get("gems", {}).get("show_all"):
        out += block("Hide", [gems, f"BaseType == {q(known)}"], HIDDEN_STYLE, "gem on poe.ninja, no shown price")
    out += block(action_for(cfg, "variable"), [gems], style_for(cfg, "variable", GEM_SHAPE), "gem not on poe.ninja (variable)")
    return section("Gems: blue for gems poe.ninja doesn't list") + out


def unused_white_hides(cfg):
    """[leveling] build + unused_whites_min_tier (league start sets it to bases.min_tier): white
    crafting bases the build never uses (the build module's Hide blocks without an AreaLevel
    upper limit, made Rarity Normal) stay hidden in maps. Goes after the bases priced at that
    tier or better, so those still show."""
    lv = cfg.get("leveling", {})
    if not (lv.get("build") and lv.get("unused_whites_min_tier")):
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


# NeverSink campaign rules: module rules/modules/leveling.filter, made with:
#   tools/import_neversink.py leveling 2802:2803 3800:3900 5000:5406 --config-key
#     'jewels->leveling\.\w+|currency->leveling(stacked)?\.\w+|decorators->leveling->magic\.noticeearly|(?!leveling->flasks->utility\.(quicksilver|asortedutility)$|leveling->normalmagic->minion\.minionshields$)leveling->[\w>-]+\.\w+=config.toml [leveling] strictness'
# [2802] jewels, [[3800]] currency styles (price first: leveling_price_first), [[5000]]
# outdated flasks, [[5100]]-[[5200]] flasks, [[5300]] rares, [[5400]] normal / magic.
# [5406] hide-all / [5407] show-all = rules/bottom.filter. Defaults kept from before the module:
# quicksilver / utility flask Shows true (FilterBlade has them off).
# Strictness-driven keys (value "config.toml [leveling] strictness"): leveling_strictness_block.
# Gear classes eligible for the campaign vendor-item size rule. Size is checked per item
# using Width and Height, rather than the largest base in its class.
VENDOR_CLASSES = [
    "Amulets", "Rings", "Jewels", "Abyss Jewels", "Belts",
    "Life Flasks", "Mana Flasks", "Hybrid Flasks", "Utility Flasks", "Tinctures",
    "Wands", "Daggers", "Rune Daggers", "Claws", "Thrusting One Hand Swords",
    "Helmets", "Boots", "Gloves", "One Hand Axes", "One Hand Swords", "One Hand Maces",
    "Sceptres", "Body Armours", "Quivers", "Bows", "Staves", "Warstaves",
    "Two Hand Axes", "Two Hand Swords", "Two Hand Maces", "Shields",
]
# White gear hidden by [leveling] hide_normal_after (flasks / tinctures stay)
NORMAL_HIDE_CLASSES = [c for c in GEAR_CLASSES if "Flask" not in c and c not in (
    "Tinctures", "Maps", "Blueprints", "Contracts", "Heist Brooches", "Heist Cloaks", "Heist Gear", "Heist Tools")]
WEAPON_CLASSES = ["Bows", "Claws", "Daggers", "One Hand Axes", "One Hand Maces", "One Hand Swords",
                  "Quivers", "Rune Daggers", "Sceptres", "Staves", "Thrusting One Hand Swords",
                  "Two Hand Axes", "Two Hand Maces", "Two Hand Swords", "Wands", "Warstaves"]


def build_magic_weapons(text):
    """Classes the build module Shows at magic rarity, kept past hide_magic_after: weapon
    classes (rf: 2H axes / maces; minion: wands) and any gear class of a Show naming exact
    BaseTypes (minion: Bone Ring, minion spirit shields)."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        rarity = re.search(r"(?m)^\s*Rarity (.*)$", blk)
        cls = re.search(r"(?m)^\s*Class == (.*)$", blk)
        if blk.startswith("Show") and rarity and cls and ("Magic" in rarity.group(1) or "<= Rare" in rarity.group(1)):
            ok = NORMAL_HIDE_CLASSES if re.search(r"(?m)^\s*BaseType ==", blk) else WEAPON_CLASSES
            out += [c for c in re.findall(r'"([^"]+)"', cls.group(1)) if c in ok and c not in out]
    return out


def emit_league_mechanic(cfg, prices, ref_currency):
    """[league_mechanic]: new league content without a price -> blue ("tier") + Moon icon.
    Inside emit_stackables, after prices / reference tiers, before the unpriced class fallbacks:
    names = exact BaseTypes nothing priced, fragments = same but fragment shape (Hexagon) instead of
    Moon, classes = whole classes (Viscera)."""
    lm = cfg.get("league_mechanic", {})
    if not lm.get("enabled"):
        return ""
    tier, overridden = lm["tier"], set(cfg.get("overrides", {}))
    out = ""
    for key, shape in (("names", LEAGUE_SHAPE), ("fragments", SHAPE["Fragment"])):
        names = [n for n in lm.get(key, []) if n not in prices and n not in overridden and n not in ref_currency
                 and n not in PINNED_TOP_STACKABLES]
        if names:
            out += block(action_for(cfg, tier), [f"BaseType == {q(names)}"], style_for(cfg, tier, shape),
                         f"new league item, no price yet (config.toml [league_mechanic] {key})")
    if lm.get("classes"):
        out += block(action_for(cfg, tier), [f"Class == {q(lm['classes'])}"], style_for(cfg, tier, LEAGUE_SHAPE),
                     "new league class, no price yet (config.toml [league_mechanic] classes)")
    return out


# NeverSink 3.30 "fatedspecial": rare non-gear classes a Fated roll can land on
FATED_SPECIAL_CLASSES = ["Abyss Jewels", "Heist Brooches", "Heist Cloaks", "Heist Gear", "Heist Tools",
                         "Jewels", "Utility Flasks"]


def emit_fated(cfg):
    """[league_mechanic] fated: "Fated True" items blue + Moon, gear_text_color text. Before leveling / stackables /
    uniques / bases / rares (their Hides can't reach it); top.filter, gems, id mods, exotics,
    recipes and cluster prices decide first. Rare gear (RARE_GROUPS) goes by base tier like
    NeverSink's t1f / t2f: league_mechanic.fated_tiers.<group> = tiers of the rares module's
    "rr" blocks ("t1".."t5", jewellery "t1".."t3", "all" = any base, [] = none), limited to
    rares.show classes; a Fated rare outside them falls through to the normal rare rules.
    Fated non-rare items and rare jewels / flasks / heist gear (FATED_SPECIAL_CLASSES) always."""
    lm = cfg.get("league_mechanic", {})
    if not (lm.get("enabled") and lm.get("fated")):
        return ""
    tiers = lm.get("fated_tiers", {})
    # gear text (variable tier: pale blue) like [unid_tier], any rarity / class / campaign
    action, style = action_for(cfg, lm["tier"]), gear_style(cfg, lm["tier"], LEAGUE_SHAPE, force_text=True)
    out = rare_base_blocks(cfg, tiers, "league_mechanic.fated_tiers", ["Fated True"], "Rarity Rare", action, style,
                           "fated rare")
    out += block(action, ["Fated True", "Rarity Rare", f"Class == {q(FATED_SPECIAL_CLASSES)}"], style,
                 "fated rare jewel / flask / heist item")
    out += block(action, ["Fated True", "Rarity <= Magic"], style, "fated item")
    out += block(action, ["Fated True", "Rarity Unique"], style, "fated item")
    return section("Fated items (config.toml [league_mechanic] fated, fated_tiers)") + out


def rare_base_blocks(cfg, tiers, setting, conds, rarity, action, style, label):
    """Blocks for gear by NeverSink rare base tier, like rares.<group>: tiers = {group: ["t1".."t5"
    (jewellery "t1".."t3") | "all" | ...]} over RARE_GROUPS, base lists = the rares module's "rr"
    blocks, limited to rares.show classes. conds = extra condition lines, rarity = "Rarity ..."
    line. Unknown group / tier = error (setting names the config key)."""
    unknown = set(tiers) - set(RARE_GROUPS)
    if unknown:
        raise ValueError(f"{setting}: unknown group {sorted(unknown)}, use {list(RARE_GROUPS)}")
    hidden = {c for c, on in cfg.get("rares", {}).get("show", {}).items() if not on}
    rr = [b for b in load_module("rares") if RARE_TIER_KEY.fullmatch(b["key"])]
    out, groups = "", {}
    for group, group_classes in RARE_GROUPS.items():
        wanted, allowed = tiers.get(group, []), [c for c in group_classes if c not in hidden]
        bad = set(wanted) - {"all"} - {b["key"].rsplit(".", 1)[1] for b in rr}
        if bad:
            raise ValueError(f"{setting}.{group}: unknown tier {sorted(bad)}")
        if not wanted or not allowed:
            continue
        if "all" in wanted:
            out += block(action, conds + [rarity, f"Class == {q(allowed)}"], style,
                         f"{label} {group}, any base ({setting}.{group} all)")
        else:
            groups[group] = (wanted, allowed)
    # One block per tier: NeverSink's generic tiers (no Class line) mix weapon + armour bases, so
    # groups wanting the same tier share one block (a per-group block could hold none of its bases)
    for b in rr:
        tier = b["key"].rsplit(".", 1)[1]
        classes = next((re.findall(r'"([^"]+)"', c) for c in b["conds"] if c.startswith("Class")), None)
        names, shown = [], []
        for group, (wanted, allowed) in groups.items():
            if tier not in wanted or (classes is None and group == "jewellery"):
                continue  # generic gear tiers (no Class line): armour / weapon bases only
            s = [c for c in allowed if classes is None or c in classes]
            if s:
                names.append(group)
                shown += s
        if shown:
            base = [c for c in b["conds"] if not c.startswith(("Class", "ItemLevel", "Rarity"))]
            out += block(action, conds + [rarity] + base + [f"Class == {q(sorted(shown))}"], style,
                         f"{label} {' + '.join(names)} {b['key']} "
                         f"({', '.join(f'{setting}.{g}' for g in names)})")
    return out



def emit_unid_tiers(cfg):
    """[unid_tier]: unidentified magic / rare gear whose hidden mods rolled well (3.28 condition
    UnidentifiedItemTier), maps only (AreaLevel >= 68). Bases like rares.<group>: weapons /
    armour / jewellery = NeverSink rare base tiers ("t1".."t5", "all", [] none, rares.show
    classes respected); min_tier.rare / .magic = lowest UnidentifiedItemTier shown (1-5, 0 =
    none); style = price tier `tier` (gear_text_color text, like Fated). Position = NeverSink
    [0800]: after id_mods / flasks / perfection / exotics and the priced-base copies (a priced base
    keeps its price tier), before gear_special / recipes / leveling / rares (their Hides)."""
    ut = cfg.get("unid_tier", {})
    if not ut.get("enabled", True):
        return ""
    action, style = action_for(cfg, ut["tier"]), gear_style(cfg, ut["tier"], BASE_SHAPE, force_text=True)
    tiers = {g: ut[g] for g in RARE_GROUPS}  # missing key = error (no hidden settings)
    out = ""
    for rarity in ("Rare", "Magic"):
        n = ut["min_tier"][rarity.lower()]
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 5:
            raise ValueError(f"config.toml [unid_tier] min_tier.{rarity.lower()} = {n!r}: use 0 (none) .. 5")
        if n:
            out += rare_base_blocks(cfg, tiers, "unid_tier", [f"UnidentifiedItemTier >= {n}", "AreaLevel >= 68"],
                                    f"Rarity {rarity}", action, style, f"unid tier {n}+ {rarity.lower()}")
    return section("Unidentified item tier (config.toml [unid_tier])") + out


def _strand_count(ms, key):
    n = ms[key]  # missing key = error (no hidden settings)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError(f"config.toml [memory_strands] {key} = {n!r}: use 0 (none) or a strand count")
    return n


def emit_memory_strands(cfg):
    """[memory_strands]: normal / magic / rare gear with Memory Strands (MemoryStrands), uncorrupted,
    unmirrored. Replaces NeverSink [0902]: bases like rares.<group> (weapons / armour / jewellery =
    rr base tiers, rares.show classes respected) at min_strands+, any base at any_base_min_strands+
    (0 = none), any base with 1+ strands when fractured / identified veiled (fractured, veiled).
    Style = price tier `tier`, gear_text_color text (like [unid_tier]). Right after [unid_tier]:
    priced bases keep their price look; before gear_special / recipes / rares (their Hides)."""
    ms = cfg.get("memory_strands", {})
    if not ms.get("enabled", True):
        return ""
    action, style = action_for(cfg, ms["tier"]), gear_style(cfg, ms["tier"], BASE_SHAPE, force_text=True)
    base = ["Mirrored False", "Corrupted False"]
    rarity = "Rarity Normal Magic Rare"
    out = ""
    if ms["fractured"]:
        out += block(action, base + ["MemoryStrands >= 1", "FracturedItem True", rarity], style,
                     "memory strands, fractured (config.toml [memory_strands] fractured)")
    if ms["veiled"]:
        out += block(action, base + ["MemoryStrands >= 1", "Identified True", rarity, 'HasExplicitMod "Veil"'],
                     style, "memory strands, veiled (config.toml [memory_strands] veiled)")
    n = _strand_count(ms, "min_strands")
    tiers = {g: ms[g] for g in RARE_GROUPS}
    if n:
        out += rare_base_blocks(cfg, tiers, "memory_strands", base + [f"MemoryStrands >= {n}"], rarity,
                                action, style, f"memory strands {n}+")
    n = _strand_count(ms, "any_base_min_strands")
    if n:
        out += block(action, base + [f"MemoryStrands >= {n}", rarity], style,
                     f"memory strands {n}+, any base (config.toml [memory_strands] any_base_min_strands)")
    return section("Memory strands (config.toml [memory_strands])") + out


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


def strip_removed_basetypes(cfg, text):
    """Drops config `removed_basetypes` names from every BaseType line (the game refuses a filter
    naming an unknown base type). A block whose BaseType list ends up empty is dropped (its rule
    lines up to the first blank line; trailing comments kept)."""
    gone = set(cfg.get("removed_basetypes", []))
    if not gone:
        return text

    def fix(m):
        names = [n for n in re.findall(r'"([^"]*)"', m.group(3)) if n not in gone]
        return f'{m.group(1)}{m.group(2)}{" ".join(chr(34) + n + chr(34) for n in names)}' if names else "\0EMPTY"

    out = []
    for blk in re.split(r"(?m)(?=^(?:Show|Hide|Minimal)\b)", text):
        blk = re.sub(r'(?m)^(\s*BaseType\s*)((?:==\s*)?)(".*)$', fix, blk)
        if "\0EMPTY" in blk:
            rule, sep, rest = blk.partition("\n\n")
            blk = rest if sep else ""
        out.append(blk)
    return "".join(out)


def maximize_item_sizes(text):
    """Use maximum font size for visible rules, except intentional content-module overrides and
    gold (GOLD_FONT_SIZE, smallest)."""
    out = []
    for blk in re.split(r"(?m)(?=^(?:Show|Hide|Minimal)\b)", text):
        if (blk.startswith(("Show", "Minimal")) and "content override show:" not in blk.splitlines()[0]
                and not re.search(r'(?m)^\s*BaseType == "Gold"\s*$', blk)):
            blk = re.sub(r"(?m)^(\s*SetFontSize\s+)\d+\b", r"\g<1>45", blk)
        out.append(blk)
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


def emit_leveling(cfg, price_shown=None, unique_bases=()):
    """Campaign rules, all gated AreaLevel <= area_level_max: [leveling] extras (jewellery,
    gems, vendor fodder, magic / white hides), the build module rules/leveling/<build>.filter,
    then module leveling (NeverSink's [2802] [[3800]] [[5000]]-[[5405]] in league.filter order,
    per-block toggles in modules.toml [leveling.blocks], leveling_module_blocks). Placed
    before overrides / stackables / uniques / bases: campaign Shows beat price Hides, never
    a unique (Rarity <= Rare on gear blocks). Build-module Shows: price first
    (campaign_price_first: price_shown stackables, unique_bases) like [[3800]]."""
    lv = cfg.get("leveling", {})
    if not lv.get("enabled"):
        return ""
    s, area = lv.get("strictness", 2), lv.get("area_level_max", 67)

    build = lv.get("build")
    out = section(f"Leveling (build {build or 'none'}, NeverSink strictness {s}, AreaLevel <= {area} only)")
    text = full = (ROOT / "rules" / "leveling" / f"{build}.filter").read_text(encoding="utf-8") if build else ""
    text = campaign_price_first(text, price_shown or {}, set(unique_bases))
    # Build module's leading Shows (before its first Hide: build uniques / bases, own style with
    # sound + icon + beam) go before the [leveling] extras, else e.g. show_jewellery's plain
    # Show wins the Bone Ring / rf rings. Module order is kept (no Hide of it precedes them).
    first_hide = re.search(r"(?m)^Hide\b", text)
    if first_hide:
        cut = text.rfind("\n\n", 0, first_hide.start())  # keep the Hide's comment with it
        cut = first_hide.start() if cut < 0 else cut + 2
        lead, text = text[:cut], text[cut:]
        out += campaign_only(lead, area) + "\n"
    if lv.get("show_jewellery"):
        out += block("Show", ["Rarity <= Rare", f"AreaLevel <= {area}", 'Class == "Amulets" "Belts" "Rings"'],
                     ["SetFontSize 40"], "jewellery, any rarity (show_jewellery)") + "\n"
    links_cls = [f"Class == {q(lv['link_classes'])}"] if lv.get("link_classes") else []
    for n in (4, 3):  # show_4_links_until / show_3_links_until: same rule, own area limit
        links_until = lv.get(f"show_{n}_links_until")
        if links_until:
            out += block("Show", ["Rarity <= Rare", f"LinkedSockets >= {n}", f"AreaLevel <= {min(links_until, area)}"]
                         + links_cls, ["SetFontSize 45", "PlayEffect Grey", "MinimapIcon 2 Grey Diamond"],
                         f"{n}-links, any base / rarity, until area {links_until} (show_{n}_links_until)") + "\n"
    if lv.get("show_jewels"):
        for rar, cond in (("Rare", "Rarity Rare"), ("Magic", "Rarity <= Magic")):
            out += block("Show", [cond, f"AreaLevel <= {area}", 'Class == "Abyss Jewels" "Jewels"'],
                         GENERIC_JEWEL_STYLE[rar], f"jewels, {rar.lower()} (show_jewels)") + "\n"
    if lv.get("show_gems"):
        out += block("Show", [f"AreaLevel <= {area}", 'Class == "Skill Gems" "Support Gems"'],
                     ["SetFontSize 40", "SetTextColor cyan"], "skill / support gems (show_gems)") + "\n"
    # Vendor fodder goes first so it can override hide_magic_after and build-module Hides.
    # The rarity toggles let users keep only the magic or rare vendor recipe items they want.
    cells = lv.get("show_magic_rare_cells", 0)
    if cells:
        for rarity, enabled, setting in (
            ("Magic", lv.get("show_magic_vendor", True), "show_magic_vendor"),
            ("Rare", lv.get("show_rare_vendor", True), "show_rare_vendor"),
        ):
            if enabled:
                for width in range(1, cells + 1):
                    max_height = cells // width
                    if max_height:
                        out += block(
                            "Show",
                            [f"Rarity {rarity}", f"AreaLevel <= {area}", f"Class == {q(VENDOR_CLASSES)}",
                             f"Width == {width}", f"Height <= {max_height}"],
                            ["SetFontSize 40"],
                            f"{rarity.lower()}, {cells} cells or less, to vendor ({setting})",
                        ) + "\n"
    # show_unid_tier_magic / _rare: unID gear rolled high (UnidentifiedItemTier >= N), any base, whole
    # campaign. Before hide_magic_after / build Hides. [unid_tier] = maps only (AreaLevel >= 68).
    for rarity in ("Magic", "Rare"):
        setting = f"show_unid_tier_{rarity.lower()}"
        min_tier = lv.get(setting)
        if min_tier:
            out += block("Show", [f"UnidentifiedItemTier >= {min_tier}", f"Rarity {rarity}", f"AreaLevel <= {area}",
                                  f"Class == {q(NORMAL_HIDE_CLASSES)}"],
                         ["SetFontSize 45", "PlayEffect Blue", "MinimapIcon 1 Blue Diamond"],
                         f"{rarity.lower()} unID tier {min_tier}+ ({setting})") + "\n"
    # magic gear after hide_magic_after: after vendor fodder, so only
    # flasks / tinctures, jewellery (show_jewellery) and the kept build weapons stay
    magic_after = lv.get("hide_magic_after")
    kept = build_magic_weapons(full) if lv.get("keep_build_weapons_magic", True) else []
    if magic_after is not None:
        out += block("Hide", ["Rarity Magic", f"AreaLevel > {magic_after}", f"AreaLevel <= {area}",
                              f"Class == {q([c for c in NORMAL_HIDE_CLASSES if c not in kept])}"],
                     HIDDEN_STYLE, f"magic gear after area {magic_after} (hide_magic_after)") + "\n"
    normal_after = lv.get("hide_normal_after")
    if build:
        # "Show # whites": the white item types the build uses, shown until hide_normal_after
        text = re.sub(r"(?m)^(Show # whites.*)$", lambda m: f"{m.group(1)}\n\tAreaLevel <= {normal_after or 0}", text)
        out += campaign_only(link_classes_only(text, lv.get("link_classes")), area) + "\n"
    if magic_after is not None and kept:
        # kept build weapons: only what the build module Shows (rf: 2H axes until the RF swap)
        out += block("Hide", ["Rarity Magic", f"AreaLevel > {magic_after}", f"AreaLevel <= {area}", f"Class == {q(kept)}"],
                     HIDDEN_STYLE, "magic build weapons the module didn't show (keep_build_weapons_magic)") + "\n"
    if build or normal_after is not None:
        # build: every white gear piece its module didn't show; no build: from hide_normal_after on
        after = [] if build else [f"AreaLevel > {normal_after}"]
        out += block("Hide", ["Rarity Normal"] + after + [f"AreaLevel <= {area}", f"Class == {q(NORMAL_HIDE_CLASSES)}"],
                     HIDDEN_STYLE, "white gear (build whites / hide_normal_after)") + "\n"
    out += leveling_module_blocks(cfg, price_shown)
    return campaign_icon_sound(out, lv.get("icon_sound", "PlayAlertSound 2 300"))


def link_classes_only(text, classes):
    """[leveling] link_classes: build-module Shows with a LinkedSockets condition only for these
    classes (their Class list cut to it, or the line added; a block left with none is dropped).
    Empty / missing = unchanged."""
    if not classes:
        return text
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        if blk.startswith("Show") and re.search(r"(?m)^\s*LinkedSockets\b", blk):
            cls = re.search(r"(?m)^(\s*)Class == (.*)$", blk)
            if cls:
                keep = [c for c in re.findall(r'"([^"]+)"', cls.group(2)) if c in classes]
                if not keep:
                    continue
                blk = blk[:cls.start()] + f"{cls.group(1)}Class == {q(keep)}" + blk[cls.end():]
            else:
                head, _, rest = blk.partition("\n")
                blk = f"{head}\n\tClass == {q(classes)}\n{rest}"
        out.append(blk)
    return "".join(out)


def leveling_module_blocks(cfg, price_shown=None):
    """Module leveling ([2802] jewels, [[3800]] currency, [[5000]]-[[5405]] flasks / rares /
    normal + magic gear), modules.toml [leveling.blocks]. Every block gets "AreaLevel <=
    area_level_max" (unless it has a lower one) and, without a Rarity / currency line,
    "Rarity <= Rare" (never a unique). true / false keys = FilterBlade options (league_start
    turns their Shows on); "config.toml [leveling] strictness" keys: leveling_strictness_block
    (league_start does not change them: strictness is the campaign preset). [[3800]] currency
    blocks: price first (leveling_price_first with price_shown, from leveling_price_shown)."""
    lv = cfg["leveling"]
    area = lv.get("area_level_max", 67)
    extra = {}
    for b in load_module("leveling"):
        gated = any(int(n) <= area for c in b["conds"] for n in re.findall(r"^AreaLevel <= (\d+)$", c))
        extra[b["key"]] = ([] if gated else [f"AreaLevel <= {area}"]) + (
            [] if any(c.startswith("Rarity") or "Stackable Currency" in c for c in b["conds"]) else ["Rarity <= Rare"])
        if b["section"] != "3800" and not any(c.startswith(("Class", "BaseType")) for c in b["conds"]):
            # gear sections, no item type: NeverSink has them after its currency sections, ours
            # come first, so e.g. [5402] firstareas ("Rarity Normal", AreaLevel <= 4) caught currency
            extra[b["key"]].append(f"Class == {q(GEAR_CLASSES)}")
        if lv.get("link_classes") and b["action"] == "Show" and any(c.startswith("LinkedSockets") for c in b["conds"]):
            extra[b["key"]].append(f"Class == {q(lv['link_classes'])}")  # [leveling] link_classes
    driven =leveling_strictness_block(lv.get("strictness", 2), extra)
    out = module_blocks(cfg, "leveling", "leveling", sections=[("0000", "3800")], extra_conds=extra, driven=driven)
    for b in load_module("leveling"):
        if b["section"] != "3800":
            continue
        on = module_on(cfg, "leveling", b["key"])
        if isinstance(on, str):
            action = leveling_strictness_action(b, lv.get("strictness", 2))
        else:
            action = b["action"] if on else None
        for conds in ([] if action is None else leveling_price_first(b["conds"], price_shown or {})):
            out += _transform_block(action, conds + extra[b["key"]], b["style"], f"leveling {b['key']}",
                                    source="module leveling")
    return out + module_blocks(cfg, "leveling", "leveling", sections=[("3801", "9999")], extra_conds=extra,
                               driven=driven)


def price_beats_campaign(cfg, tiers, tier):
    """[leveling] price_over_tier: a price tier beats campaign Shows (build module, [[3800]])
    when it is shown, not quiet and ranks at or above price_over_tier ("" = any shown tier)."""
    over = cfg.get("leveling", {}).get("price_over_tier", "")
    if tier not in tiers.order or hidden(cfg, tier) or tier in cfg.get("quiet_tiers", []):
        return False
    return not over or tiers.rank(tier) <= tiers.rank(over)


def _tier_style_key(lines):
    """Look of a price-tier style, for campaign_price_over: sound / beam / icon size + colour /
    background / border lines (text colour and font size left out: gear_text_color and
    maximize_item_sizes change those). No beam = None (not a price-tier look)."""
    key = frozenset(" ".join(l.split()[:3]) if l.startswith("MinimapIcon") else l for l in lines
                    if l.startswith(("PlayAlertSound", "PlayEffect", "MinimapIcon", "SetBackgroundColor",
                                     "SetBorderColor", "DisableDropSound")))
    return key if any(l.startswith("PlayEffect") for l in key) else None


def campaign_price_over(cfg, tiers, text):
    """[leveling] on: every price-tier Show block of the rules after the campaign rules (text =
    overrides, stackables, viscera, maps, crafting bases, gems, ...) whose tier beats them
    (price_beats_campaign) -> campaign-only copy (AreaLevel <= area_level_max), emitted right
    before emit_leveling: a later rule that gives a higher tier wins over leveling's Show / Hide.
    Tier = tier name in the comment ("low stack x3", "base mid ...", "... tier low"), else the look
    (_tier_style_key, equal looks -> best tier). Only exact
    "BaseType ==" blocks (class catch-alls keep their place behind the per-name Hides), no
    uniques (leveling never matches them; build-module uniques: leveling_unique_bases), no
    module blocks (NeverSink styles, no price tier), none limited to maps (AreaLevel above)."""
    lv = cfg.get("leveling", {})
    if not lv.get("enabled"):
        return ""
    area = lv.get("area_level_max", 67)
    look = {}
    for t in reversed(tiers.order):  # better tier last: wins an equal look
        if t != "hide" and t in cfg["style"] and not hidden(cfg, t):
            for style in (style_for(cfg, t), gear_style(cfg, t, force_text=True)):
                if _tier_style_key(style):
                    look[_tier_style_key(style)] = t
    out = ""
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        if not blk.startswith("Show"):
            continue
        rule = blk.split("\n\n", 1)[0].rstrip("\n").splitlines()
        lines = [l.strip() for l in rule[1:]]
        style_at = next((i for i, l in enumerate(lines) if STYLE_RE.match(l)), len(lines))
        conds, style = lines[:style_at], lines[style_at:]
        tier = look.get(_tier_style_key(style))
        words = rule[0].partition("#")[2].replace(",", " ").split()  # "low stack x3", "base mid ...", "... tier low"
        named = [w for i, w in enumerate(words) if w in tiers.order and (i < 2 or words[i - 1] == "tier")]
        tier = named[0] if tier and named else tier
        if (tier is None or "Continue" in style or "(module " in rule[0] or "(NeverSink" in rule[0]
                or not any(c.startswith("BaseType ==") for c in conds)
                or any(c.startswith("Rarity") and rarities_of(c) == {"Unique"} for c in conds)
                or any(int(n) + (op == ">") > area for c in conds
                       for op, n in re.findall(r"^AreaLevel (>=|>|==|=)? ?(\d+)$", c))
                or not price_beats_campaign(cfg, tiers, tier)):
            continue
        out += "\n".join([f"{rule[0]} (campaign: price first)", f"\tAreaLevel <= {area}"]
                         + [f"\t{l}" for l in lines]) + "\n"
    return section("Campaign: price tiers over the leveling rules ([leveling] price_over_tier)") + out if out else ""


def leveling_price_shown(cfg, tiers, prices):
    """Priced stackable name -> smallest stack size whose price tier beats the campaign Shows
    (price_beats_campaign; 1 = any; None = never): pinned top, [overrides] at such a tier, a
    confident price in one, or a stack of it reaching one (as emit_stackables, up to its max stack)."""
    ex, sl, out = cfg["exchange"], small_loot(cfg), dict.fromkeys(PINNED_TOP_STACKABLES, 1)
    beats = lambda tier: price_beats_campaign(cfg, tiers, tier)
    overrides = cfg.get("overrides", {})
    out.update({n: 1 if beats(tier) else None for n, tier in overrides.items()})
    for name, (v, t) in prices.items():
        if name in out:
            continue
        out[name] = None
        if v <= 0 or (sl and t in sl[1] and v < sl[0]):
            continue
        own = tiers.of(v)
        if beats(own):
            out[name] = 1
            continue
        if t == "DivinationCard":
            continue
        max_stack = ex.get("splinters", {}).get(name, [None, ex.get("big_stacks", {}).get(name, ex["max_stack"])])[1]
        needs = [math.ceil(thr / v - 1e-9) for tn, thr in tiers.list
                 if beats(tn) and tiers.rank(tn) < tiers.rank(own)]
        out[name] = min((n for n in needs if n <= max_stack), default=None)
    return out


def leveling_unique_bases(cfg, tiers, ubases):
    """Unique bases whose price tier beats the campaign Shows (price_beats_campaign): dropped
    from campaign "Rarity Unique" Shows (build module uniques), so the price style wins."""
    return {b for b, (t, *_r) in ubases.items() if price_beats_campaign(cfg, tiers, t)}


def campaign_price_first(text, price_shown, unique_bases):
    """Campaign Show blocks (build module) -> price first, like [[3800]]: stackable names
    leveling_price_first (dropped / "StackSize < n"); "Rarity Unique" Shows drop unique_bases.
    A block left without names is dropped."""
    out = []
    for blk in re.split(r"(?m)^(?=(?:Show|Hide)\b)", text):
        if not blk.startswith("Show"):
            out.append(blk)
            continue
        lines = blk.splitlines()
        n = next((i for i, l in enumerate(lines) if i and not l[:1].isspace()), len(lines))
        rule, tail = lines[:n], lines[n:]
        style_at = next((i for i, l in enumerate(rule) if i and re.match(r"\s*(Set|Play|Minimap|Disable|Enable|Custom)", l)),
                        len(rule))
        conds = [l.strip() for l in rule[1:style_at]]
        bt = next((c for c in conds if c.startswith("BaseType")), None)
        if bt is None:
            out.append(blk)
            continue
        if "Rarity Unique" in conds or "Rarity == Unique" in conds:
            keep = [b for b in re.findall(r'"([^"]+)"', bt) if b not in unique_bases]
            groups = [[c if c is not bt else f"BaseType == {q(keep)}" for c in conds]] if keep else []
        else:
            groups = leveling_price_first(conds, price_shown)
        tail_text = "\n".join(tail) + ("\n" if blk.endswith("\n") else "")
        out.append("".join("\n".join([rule[0]] + [f"\t{c}" for c in g] + rule[style_at:]) + "\n" for g in groups)
                   + tail_text)
    return "".join(out)


def leveling_price_first(conds, price_shown):
    """[[3800]] campaign currency block -> condition lists without what price rules show
    (price_shown: name -> stack size, leveling_price_shown): those names dropped, or
    "StackSize < n" below the stack a price tier shows. Partial BaseType (essence prefixes): unchanged unless a priced
    name matches, then the matching priced names as exact names."""
    bt = next(c for c in conds if c.startswith("BaseType"))
    names = re.findall(r'"([^"]+)"', bt)
    if not bt.startswith("BaseType =="):
        names = [n for n in price_shown if any(n.startswith(p) for p in names)]
        if not any(price_shown[n] for n in names):
            return [conds]
    floor = max((int(m) for c in conds for m in re.findall(r"^StackSize >= (\d+)$", c)), default=1)
    groups = {}
    for n in names:
        need = price_shown.get(n)
        if need is None or need > floor:
            groups.setdefault(need, []).append(n)
    rest = [c for c in conds if c is not bt]
    return [rest + [f"BaseType == {q(ns)}"] + ([f"StackSize < {need}"] if need else []) for need, ns in groups.items()]


def leveling_strictness_block(s, extra):
    """module_blocks driven for leveling keys valued "config.toml [leveling] strictness", from
    the block's NeverSink tag (FilterBlade strictness s, 0 soft .. 4 very strict): %D<n> = Show
    while s < n; %H<n> = Hide from s >= n, Show below; !utility_layer (optional magic blockers)
    = Hide from s >= 3; untagged Hide (FilterBlade's export has leveling off) = Show."""
    def emit(b):
        action = leveling_strictness_action(b, s)
        if action is None:
            return ""
        return _transform_block(action, b["conds"] + extra[b["key"]], b["style"], f"leveling {b['key']}",
                                source="module leveling")
    return emit


def leveling_strictness_action(b, s):
    """Show / Hide / None (off) of a leveling block at strictness s, from its NeverSink tag
    (see leveling_strictness_block)."""
    tags = " ".join(b["tags"])
    d, h = re.search(r"%D(\d)", tags), re.search(r"%H(\d)", tags)
    if d:
        return "Show" if s < int(d.group(1)) else None
    if h:
        return "Hide" if s >= int(h.group(1)) else "Show"
    if "!utility_layer" in tags:
        return "Hide" if s >= 3 else None
    return "Show"


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

def load_cfg(config="config.toml"):
    """config = settings file (relative to ROOT), e.g. config_standard.toml (build --config)."""
    cfg = split_tiers(tomllib.loads((ROOT / config).read_text(encoding="utf-8")))
    raw = tomllib.loads((ROOT / "unique_tiers.toml").read_text(encoding="utf-8"))
    cfg["unique_tiers"] = {n: int(t) for t, names in raw.items() for n in names}
    cfg["modules"] = tomllib.loads((ROOT / "modules.toml").read_text(encoding="utf-8"))
    cfg["fallback_tiers"] = tomllib.loads((ROOT / "fallback_tiers.toml").read_text(encoding="utf-8"))
    return apply_league_start(cfg)


def split_tiers(cfg):
    """tiers.<name> = divine fraction -> cfg["tiers_divine"]; cfg["tiers"] = chaos at
    FALLBACK_DIVINE until build_text knows the real divine price (apply_divine_tiers)."""
    cfg["tiers_divine"] = {n: float(v) for n, v in cfg["tiers"].items()}
    cfg["tiers"] = {n: v * FALLBACK_DIVINE for n, v in cfg["tiers_divine"].items()}
    return cfg


# League start = these loosened values, ONE table for both: config.toml league_start = true
# (apply_league_start, at load) and tools/league_start.py start (writes them into config.toml /
# modules.toml so they can be tightened one by one). New league-start behaviour -> add it here
# as a value (a config key if needed), never as a league_start check in an emitter.
# Module blocks league start leaves as modules.toml has them: module -> sections.
LS_KEEP_SECTIONS = {  # off Shows that stay off (they'd flood)
    "rares": [RARE_ANIMATED_SECTION],      # [[2600]] animated weapons: every normal / magic weapon
    "jewels": [CLUSTER_ECO_SECTION],       # [2805] off blocks = empty eco tiers: tink every enchant
}
LS_KEEP_HIDES = {  # on Hides that stay on
    "maps": [MAP_PROGRESSION_SECTION],     # [3302] tier Hides: [maps] progression "all" turns them
                                           # to Show in their tier style; off = generic restex look
    "leveling": [("0000", "9999")],        # campaign preset (outdated-flask Hides; strictness keys
                                           # are strings anyway): junk while levelling
}
# Config tables whose `enabled` league start turns on (rule modules + priced sections).
LS_ENABLE_TABLES = ("bases", "rares", "id_mods", "flasks", "exotics", "gear_special", "maps",
                    "jewels", "heist", "misc", "unique_exceptions", "leveling",
                    "league_mechanic", "unid_tier", "memory_strands")


def league_start_values(conf, modules):
    """Loosened league-start values: (config changes, modules changes), each {key path tuple:
    value}. conf = config.toml dict (tiers = name -> threshold, any scale), modules =
    modules.toml dict. Only keys that exist are listed (no hidden settings); a value equal to
    the current one is listed too (callers diff)."""
    lowest = min(conf["tiers"], key=conf["tiers"].get)
    shown = lambda t: lowest if t == "hide" else t
    present = lambda *path: _has(conf, path)
    c = {("hide_tiers",): [], ("small_loot", "enabled"): False,
         ("uniques", "hide_maps"): False,
         ("gems", "min_tier"): lowest, ("gems", "show_all"): True, ("gems", "hide_level1"): False,
         ("show_5_links",): True, ("show_6_links",): True, ("show_mirrored",): True,
         ("show_contracts",): True, ("hide_forbidden_tome",): False,
         ("show_gold",): True, ("show_small_gold",): True,
         ("maps", "corrupted_min_tier"): 0, ("maps", "min_tier"): 0, ("maps", "blighted_hide_tiers"): [],
         ("flasks", "show_plain"): True,
         ("jewels", "show_rare"): True, ("jewels", "show_magic"): True,
         }
    c.update({("overquality", k): True for k, v in conf.get("overquality", {}).items()
              if isinstance(v, bool)})  # every quality rule on (rank base lists stay as set)
    c.update({("links", k): True for k in conf.get("links", {})})  # every 5-link / 4-link Show on
    # [chancing] stays as set (user choice: chancing bases are no loot value)
    c[("gear_special", "perfection_armour")] = ["all"]
    c[("league_mechanic", "fated")] = True
    c.update({("league_mechanic", "fated_tiers", g): ["all"] for g in conf.get("league_mechanic", {}).get("fated_tiers", {})})

    c = {p: v for p, v in c.items() if present(*p)}
    c.update({("uniques", "show", t): True for t in conf["uniques"].get("show", {})})
    for sec in ("foulborn", "bases", "viscera"):
        if "min_tier" in conf.get(sec, {}):
            c[(sec, "min_tier")] = lowest
    if "talisman_min_tier" in conf.get("content", {}).get("bestiary", {}):
        c[("content", "bestiary", "talisman_min_tier")] = lowest
    for sec in ("uniques", "foulborn", "bases"):
        if "unpriced" in conf.get(sec, {}):
            c[(sec, "unpriced")] = shown(conf[sec]["unpriced"])
    if conf.get("maps", {}).get("progression", "none") == "none":
        c[("maps", "progression")] = "all"
    ex = conf["exchange"]
    c[("exchange", "unpriced_currency")] = shown(ex["unpriced_currency"])
    c.update({("exchange", "reference_card_tiers", k): shown(t) for k, t in ex["reference_card_tiers"].items()})
    c.update({("exchange", "unpriced_tiers", k): shown(t) for k, t in ex.get("unpriced_tiers", {}).items()
              if isinstance(t, str)})
    c.update({("overrides", k): shown(t) for k, t in conf.get("overrides", {}).items()})
    for m, mod in conf.get("content", {}).items():
        c[("content", m, "enabled")] = True
        c.update({("content", m, "drops", n): "price" for n, v in mod.get("drops", {}).items() if v is False})
        c.update({("content", m, "wombgifts", n): "price" for n, v in mod.get("wombgifts", {}).items() if v == "hide"})
    c.update({("vendor_recipes", r, "enabled"): True for r, rec in conf.get("vendor_recipes", {}).items()
              if "enabled" in rec})
    c.update({(t, "enabled"): True for t in LS_ENABLE_TABLES if "enabled" in conf.get(t, {})})
    c[("leveling", "enabled")] = True
    rares = conf.get("rares", {})
    if rares:
        c[("rares", "base_tiers")] = True
        c.update({("rares", g): ["all"] for g in RARE_GROUPS if g in rares})
        c.update({("rares", "min_ilvl", g): 68 for g in rares.get("min_ilvl", {})})
        c.update({("rares", "show", k): True for k in rares.get("show", {})})
    inf = conf.get("influenced", {})
    loose = {"ranks": ["A", "B", "C"], "bases": list(INFLUENCES), "classes": [*INFLUENCES, "shared"],
             "remaining": ["high", "all"], "hide_cheap": False}
    c.update({("influenced", k): v for k, v in loose.items() if k in inf})
    ut = conf.get("unid_tier", {})
    c.update({("unid_tier", g): ["all"] for g in RARE_GROUPS if g in ut})
    c.update({("unid_tier", "min_tier", r): 2 for r in ut.get("min_tier", {})})  # FilterBlade's lowest cell
    ms = conf.get("memory_strands", {})
    c.update({("memory_strands", g): ["all"] for g in RARE_GROUPS if g in ms})
    c.update({("memory_strands", k): True for k in ("fractured", "veiled") if k in ms})
    if "min_strands" in ms:
        c[("memory_strands", "min_strands")] = 1  # any stranded item on any base
    if "any_base_min_strands" in ms:
        c[("memory_strands", "any_base_min_strands")] = 1
    lv = conf.get("leveling", {})
    if lv.get("build") and lv.get("league_start_hide_unused", True) and not lv.get("unused_whites_min_tier"):
        c[("leveling", "unused_whites_min_tier")] = conf["bases"]["min_tier"]  # whites the build never uses
    m = {}
    inside = lambda b, secs: any(first <= (b["section"] or "") < after for first, after in secs)
    for name, table in modules.items():
        for b in load_module(name):
            on = table.get("blocks", {}).get(b["key"])
            if b["action"] == "Show" and on is False and not inside(b, LS_KEEP_SECTIONS.get(name, [])):
                m[(name, "blocks", b["key"])] = True
            elif b["action"] == "Hide" and on is True and not inside(b, LS_KEEP_HIDES.get(name, [])):
                m[(name, "blocks", b["key"])] = False
    return c, m


def _has(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return False
        d = d[k]
    return True


def set_path(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def apply_league_start(cfg):
    """league_start = true: show (almost) everything = league_start_values written into cfg
    (same values tools/league_start.py start writes into the files). Once per cfg."""
    if not cfg.get("league_start") or cfg.get("_league_start_applied"):
        return cfg
    c, m = league_start_values(cfg, cfg["modules"])
    for path, value in c.items():
        set_path(cfg, path, value)
    for path, value in m.items():
        set_path(cfg["modules"], path, value)
    cfg["_league_start_applied"] = True
    return cfg


def beam_icon(cfg, text):
    """Every Show block with a beam (PlayEffect) but no MinimapIcon -> MinimapIcon 2 <beam colour>
    Diamond after the beam (NeverSink module copies often beam without icon). No sound added.
    Exceptions: brown tier blocks (SetBackgroundColor brown_bg) keep their grey beam without icon;
    quiet_tiers blocks with quiet_icon = false (every quiet_tier_lines line present) too."""
    quiet = None if cfg.get("quiet_icon", True) else quiet_tier_lines(cfg)

    def one(m):
        b = m.group(0)
        e = re.search(r"^([ \t]*)PlayEffect (\w+).*$", b, re.M)
        if not b.startswith("Show") or not e or re.search(r"^\s*MinimapIcon\b", b, re.M) \
                or re.search(r"^\s*SetBackgroundColor brown_bg\b", b, re.M):
            return b
        if quiet and all(re.search(rf"^\s*{re.escape(l)}\s*$", b, re.M) for l in quiet):
            return b
        return b[:e.end()] + f"\n{e.group(1)}MinimapIcon 2 {e.group(2)} Diamond" + b[e.end():]
    return BLOCK_RE.sub(one, text)


def blue_beam_text(cfg, text):
    """Every Show block with a blue beam (variable / unknown tier, module blocks NeverSink marks
    blue) -> text colour variable_text_color ([colors] name), so blue beam = pale blue text
    everywhere. Its old SetTextColor lines go; the new one sits before PlayEffect Blue."""
    color = cfg.get("variable_text_color", "variable_blue")

    def one(m):
        b = m.group(0)
        if not b.startswith("Show") or not re.search(r"^\s*PlayEffect Blue\b", b, re.M):
            return b
        b = re.sub(r"^[ \t]*SetTextColor .*\n", "", b, flags=re.M)
        return re.sub(r"^([ \t]*)(PlayEffect Blue)", rf"\1SetTextColor {color}\n\1\2", b, count=1, flags=re.M)
    return BLOCK_RE.sub(one, text)


def unique_game_text(cfg, text):
    """[uniques] keep_text_color: every block that only matches uniques (Rarity Unique / == Unique)
    loses its SetTextColor lines, so uniques keep the game's unique colour whatever their tier
    (price, variable / blue beam, brown / dust, module copies). Top tier (tink, SetBackgroundColor
    tink_bg) keeps its red text. Beam / icon / sound / background stay."""
    if not cfg["uniques"].get("keep_text_color", True):
        return text

    def one(m):
        b = m.group(0)
        if not re.search(r"^\s*Rarity (?:==? ?)?Unique\s*$", b, re.M) \
                or re.search(r"^\s*SetBackgroundColor tink_bg\b", b, re.M):
            return b
        return re.sub(r"^[ \t]*SetTextColor .*\n?", "", b, flags=re.M)
    return BLOCK_RE.sub(one, text)


def apply_palette(cfg, text):
    """Every Set*Color line -> a config [colors] value. Name: its value (unknown -> ValueError).
    Numbers (NeverSink copies): the nearest palette colour by RGB, text only from text colours,
    so imported whites / reds / yellows match ours. Runs before hidden_game_colours (Alt view
    keeps the game's rarity colours)."""
    palette = cfg["colors"]
    rgba = lambda v: ([int(x) for x in v.split()] + [255])[:4]

    def one(m):
        key, value = m.group(1), m.group(2)
        if value[0].isalpha():
            if value not in palette:
                raise ValueError(f"unknown colour {value!r} (config.toml [colors])")
            return f"{key} {palette[value]}"
        text = key.endswith("TextColor")
        names = [n for n in palette if n not in NAME_ONLY_COLORS and (not text or n not in NON_TEXT_COLORS)]
        # text: RGB only; border / background: alpha too (an invisible 0-alpha one stays invisible)
        dims = 3 if text else 4
        if not text and rgba(value)[3] == 0:
            names = [n for n in names if rgba(palette[n])[3] == 0] or names
        near = min(names, key=lambda n: sum((a - b) ** 2 for a, b in
                                            zip(rgba(value)[:dims], rgba(palette[n])[:dims])))
        return f"{key} {palette[near]}"
    return COLOR_LINE.sub(one, text)


def hand_rules(cfg, name):
    """rules/<name>.filter; [gems] show_all turns "Hide # gems.show_all" blocks into Show."""
    text = (ROOT / "rules" / f"{name}.filter").read_text(encoding="utf-8")
    if name == "top":
        for key in ("show_5_links", "show_6_links", "show_mirrored"):
            pattern = rf"(?ms)^# BEGIN {key}\r?\n(.*?)^# END {key}\r?\n?"
            replacement = r"\1" if cfg.get(key, key == "show_6_links") else TOGGLE_OFF.get(key, "")
            text, count = re.subn(pattern, replacement, text)
            if count != 1:
                raise ValueError(f"Expected one {key} section in rules/top.filter, found {count}")
    if cfg.get("gems", {}).get("show_all"):
        text = re.sub(r"^Hide(?= # gems\.show_all)", "Show", text, flags=re.M)
    return section(f"Hand-written {name} rules (rules/{name}.filter)") + text


def build_text(cfg, data, league):
    """Whole filter text + pricing results. No network, no file writes (tests use this).
    league_start set but not applied yet (tests): applied to a copy, cfg stays as it is."""
    if cfg.get("league_start") and not cfg.get("_league_start_applied"):
        cfg = apply_league_start(copy.deepcopy(cfg))
    cfg = apply_wombgift_choices(cfg)
    apply_divine_tiers(cfg, exchange_divine(data))
    tiers = Tiers(cfg)
    prices, divine = price_stackables(data, cfg, tiers)
    card_volumes = card_trade_volumes(data)
    ancient_wombgift, item_type = prices.get("Ancient Wombgift", (0, "Wombgift"))
    prices["Ancient Wombgift"] = (max(ancient_wombgift, cfg["tiers"]["minor"]), item_type)
    unique_ev = {}
    ubases = price_unique_bases(data, cfg, tiers, divine, unique_ev, unique_vendor_values(cfg, prices))
    fbases = price_foulborn_bases(data, cfg, tiers, divine)
    vbases = price_viscera_bases(data, cfg, tiers, divine)
    linked = price_linked_jackpots(data, cfg, divine)
    cbases = price_crafting_bases(data, cfg, tiers, divine)
    talismans = price_talismans(data, cfg, tiers, divine)
    ref_cards = fallback_tiers(cfg, "cards")
    ref_currency = fallback_tiers(cfg, "currency")
    clusters = price_clusters(data, cfg, tiers)
    gems = price_gems(data, cfg, tiers, divine)

    header = (f"# Price filter - generated {datetime.now():%Y-%m-%d %H:%M}"
              + ("   LEAGUE START (almost nothing hidden)" if cfg.get("league_start") else "") + "\n"
              f"# League: {league}   Divine = {divine:.0f}c\n"
              f"# Tiers (chaos, from divine fractions): " + ", ".join(f"{n}>={v:g}" for n, v in tiers.list) +
              f"   Jackpot (never hidden) >= {cfg['jackpot_divine']} div\n"
              f"# Do not edit - edit config.toml / rules/*.filter and rerun build_filter.py\n")
    after_leveling = [  # campaign_price_over copies their higher-tier Shows before leveling
        campaign_unhide(cfg, emit_overrides(cfg, prices)),
        campaign_unhide(cfg, emit_viscera(cfg, tiers, vbases)),  # before the league_mechanic Viscera blue
        campaign_unhide(cfg, emit_stackables(cfg, tiers, prices, ref_currency, ref_cards, card_volumes)),
        emit_special_maps(cfg),
        emit_misc(cfg, MISC_BEFORE_UNIQUES),  # [[4500]]-[[4700]] heist targets / enshrouded / idols
        emit_uniques(cfg, tiers, ubases, fbases, linked,
                     {l["baseType"] for l in data["stash"]["UniqueMap"].get("lines", []) if l.get("baseType")},
                     valuable_content_bases(data, cfg, tiers)),
        emit_misc(cfg, MISC_AFTER_UNIQUES),  # [[4900]] questlike items 2 after uniques
        emit_map_progression(cfg),
        emit_crafting_bases(cfg, tiers, cbases),
        emit_rares(cfg),  # after crafting bases: priced bases beat rare Hides
        emit_endgame_crafting(cfg),  # [[2300]] crafting, [[2400]] chancing, [2601] RGB (league.filter order)
        emit_rare_hide_layer(cfg),  # [2602] + [[2700]]
        emit_jewels(cfg),  # league.filter [[2800]] after rares
        emit_heist(cfg),  # [[2900]] right after jewels
        emit_level1_gem_hide(cfg, data, divine),  # after campaign / price Shows; names only, unlisted gems stay blue
        emit_unknown_gems(cfg, data),  # last gem rule: unlisted gems blue, before bottom.filter's gem Hide
        hand_rules(cfg, "bottom"),
    ]
    text = "\n".join([
        header,
        emit_visibility_toggles(cfg),
        emit_content_overrides(cfg, data.get("content", {}), ubases),
        emit_defaults(cfg),
        emit_pinned_stackables(cfg),
        emit_gems(cfg, tiers, gems),  # before top's 20% / Awakened Shows and the gemcutter recipe floor
        emit_gold(cfg),  # league.filter [[0200]]: config show_gold, then module misc gold tiers
        hand_rules(cfg, "top"),
        emit_flasks(cfg),  # before vendor recipes too (glassblower)
        emit_id_mods(cfg),  # before recipes / crafting bases / rares: good identified gear beats base Hides
        emit_perfection(cfg),  # [0901] perfection / overquality ([overquality]); before recipes: 30% RGB keeps its alert
        emit_exotics(cfg, emit_talismans(cfg, tiers, talismans)),  # same; after id_mods like league.filter ([0600]-[0802] before [0902]-[1300])
        emit_priced_bases_first(cfg, tiers, cbases, flask_base_classes(data)),  # priced crafting bases beat the gear_special / crafting Shows only
        emit_flasks(cfg, plain=True),  # plain ilvl / any-utility flask Shows: after priced flask bases
        emit_unid_tiers(cfg),  # [0800] unID item tier by rare base tier: after priced bases, before gear_special / recipes / rares
        emit_memory_strands(cfg),  # [0902] memory strands by rare base tier: same spot / reason as unid_tier
        emit_gear_special(cfg, cheap_influenced_bases(data, cfg)),  # [0302] influenced, [[0400]] eldritch, [[0500]] exotic bases (after id/exotic info)
        emit_links(cfg),  # [[1400]] 5-links ([1401]); league.filter: after [1300], before [1500] bases
        emit_vendor_recipes(cfg, tiers, ubases, fbases, cbases, prices, ref_currency),
        emit_gem_fallback(cfg, gems),  # after the gemcutter floor; explicit hides before blue
        emit_cluster_prices(cfg, tiers, clusters),
        emit_fated(cfg),  # [league_mechanic] fated: before campaign / stackable / unique / rare Hides
        campaign_price_over(cfg, tiers, "".join(after_leveling)),  # later rules' higher tiers beat leveling
        emit_leveling(cfg, leveling_price_shown(cfg, tiers, prices),  # price first: [[3800]] + build module
                      leveling_unique_bases(cfg, tiers, ubases)),
    ] + after_leveling)
    text = apply_palette(cfg, unique_game_text(cfg, blue_beam_text(cfg, beam_icon(cfg, text))))
    text = hidden_game_colours(text)
    text = maximize_item_sizes(text)
    text = strip_removed_basetypes(cfg, text)
    return text, {"tiers": tiers, "prices": prices, "divine": divine, "ubases": ubases, "unique_ev": unique_ev,
                  "fbases": fbases, "vbases": vbases, "linked": linked, "cbases": cbases, "talismans": talismans, "ref_cards": ref_cards,
            "ref_currency": ref_currency, "card_volumes": card_volumes, "clusters": clusters, "gems": gems}


def report_name(config):
    """config.toml -> report.html, config_standard.toml -> report_standard.html."""
    stem = Path(config).stem
    return "report.html" if stem == "config" else f"report{stem[len('config'):]}.html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore price cache")
    ap.add_argument("--league", help="override league name")
    ap.add_argument("--config", default="config.toml",
                    help="settings file, e.g. config_standard.toml (own league / output_name)")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    league = detect_league(cfg, args)
    print(f"League: {league}")
    check_ninja_categories(args.refresh)
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
    card_fallbacks = sum(1 for n in r["ref_cards"] if n not in prices
                         and r["card_volumes"].get(n, 0) < cfg["exchange"]["card_fallback_min_volume"])
    print(f"Cards using NeverSink fallback (no price, low volume): {card_fallbacks}")
    print(f"Currency from reference tiers: {sum(1 for n in r['ref_currency'] if n not in prices)}")
    print(f"Unique bases: {len(ubases)}  ({count(t for t, *_ in ubases.values())})")
    div = divine or float("nan")  # league day 1: poe.ninja has no Divine price yet
    jack = sorted(((b, v) for b, v in ubases.items() if v[0] == 'variable'), key=lambda kv: -kv[1][2])
    print(f"Variable bases ({len(jack)}): " + ", ".join(
        f"{b} ({v[3]} {v[2] / div:.1f}div" + (f", EV {v[4]:.1f}c)" if v[4] is not None else ")") for b, v in jack))
    gone = sorted(((b, v) for b, v in ubases.items() if v[0] == "hide" and v[4] is not None
                   and v[2] >= jackpot_chaos(cfg, divine)), key=lambda kv: -kv[1][2])
    print(f"Hidden by EV despite a jackpot ({len(gone)}): " + ", ".join(
        f"{b} ({v[3]} {v[2] / div:.0f}div, EV {v[4]:.1f}c)" for b, v in gone))
    missing = sorted(n for n in data.get("drop_anywhere", ()) if n not in cfg["unique_tiers"])
    if cfg["uniques"].get("ev", {}).get("enabled") and missing:
        print(f"No drop tier in unique_tiers.toml (default_tier used): {', '.join(missing)}")
    print(f"Skipped boss / encounter-only uniques (wiki): {len(data.get('nomap', {}))}")
    for mod, by_base in data.get("content", {}).items():
        if cfg["content"][mod].get("enabled"):
            print(f"Content {mod} (small, silent): " + ", ".join(sorted(by_base)))
    print(f"Foulborn bases: {len(r['fbases'])}  ({count(t for t, *_ in r['fbases'].values())})")
    print(f"Viscera bases: {len(r['vbases'])}  ({count(t for t, *_ in r['vbases'].values())})")
    print(f"Crafting base rules: {len(cbases)} entries")
    print(f"Written: {out_file}")
    print(f"Report:  {report.write(cfg, data, text, r, league, ROOT / 'out' / report_name(args.config))}")


if __name__ == "__main__":
    main()
