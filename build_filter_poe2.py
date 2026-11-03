"""Build a PoE2 loot filter from poe.ninja Currency and Runes exchange data."""
import argparse
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

ROOT = Path(__file__).resolve().parent
NINJA = "https://poe.ninja/poe2/api"
UA = {"User-Agent": "price-filter-builder/1.0 (personal loot filter script)"}
PINNED_TOP = {"Divine Orb", "Mirror of Kalandra"}
GEAR_CLASSES = [
    "Amulets", "Belts", "Body Armours", "Boots", "Bows", "Bucklers", "Charms",
    "Claws", "Crossbows", "Foci", "Gloves", "Helmets", "Life Flasks", "Mana Flasks",
    "One Hand Axes", "One Hand Maces", "One Hand Swords", "Quarterstaves", "Quivers",
    "Rings", "Sceptres", "Shields", "Spears", "Staves", "Two Hand Axes",
    "Two Hand Maces", "Two Hand Swords", "Wands", "Warstaves",
]
SHAPES = {"Currency": "Circle", "Runes": "Moon"}
HIDDEN_STYLE = ["SetFontSize 18", "DisableDropSound True"]
STYLES = {
    "top": ["SetFontSize 45", "SetTextColor 255 0 0 255", "SetBorderColor 255 0 0 255",
            "SetBackgroundColor 255 255 255 255", "PlayAlertSound 6 300", "PlayEffect Red",
            "MinimapIcon 0 Red Star"],
    "high": ["SetFontSize 45", "SetTextColor 255 0 0 255", "PlayAlertSound 1 300",
             "PlayEffect Red", "MinimapIcon 1 Red Circle"],
    "mid": ["SetFontSize 45", "SetTextColor 255 190 0", "PlayAlertSound 2 300",
            "PlayEffect Yellow", "MinimapIcon 1 Yellow Circle"],
    "minor": ["SetFontSize 40", "SetTextColor 215 215 215 255", "PlayAlertSound 2 300",
              "PlayEffect White", "MinimapIcon 1 White Circle"],
    "low": ["SetFontSize 35", "SetTextColor 215 215 215 255", "PlayAlertSound 2 300",
            "PlayEffect White", "MinimapIcon 1 White Circle"],
    "brown": ["SetFontSize 30", "SetTextColor 210 178 134 255", "DisableDropSound True"],
    "dust": ["SetFontSize 25", "SetTextColor 210 178 134 255", "DisableDropSound True"],
    "unknown": ["SetFontSize 40", "PlayAlertSound 2 300", "PlayEffect Blue",
                "MinimapIcon 1 Blue Diamond"],
}
QUIET_STYLE = ["SetTextColor 210 178 134 255", "PlayEffect Grey",
               "MinimapIcon 2 Grey Circle", "DisableDropSound True"]


def q(names):
    return " ".join(json.dumps(name, ensure_ascii=False) for name in sorted(names))


def block(action, conditions, style, comment=""):
    head = action + (f" # {comment}" if comment else "")
    return "\n".join([head] + [f"\t{condition}" for condition in conditions]
                     + [f"\t{line}" for line in style]) + "\n"


class Tiers:
    def __init__(self, cfg, divine_chaos):
        self.cfg = cfg
        self.values = {}
        for name, value in cfg["tiers"].items():
            if cfg["tiers_follow_divine"] and divine_chaos and "div" in value:
                self.values[name] = max(1.0, round(value["div"] * divine_chaos, 2))
            else:
                self.values[name] = float(value["chaos"])
        self.ordered = sorted(self.values.items(), key=lambda pair: -pair[1])

    def of(self, chaos):
        for name, threshold in self.ordered:
            if chaos >= threshold:
                return name
        return "hide"

    def hidden(self, name):
        return name == "hide" or name in self.cfg["hide_tiers"]

    def style(self, name, shape):
        if self.hidden(name):
            return HIDDEN_STYLE
        lines = list(STYLES[name])
        if name in self.cfg["quiet_tiers"]:
            lines = [line for line in lines if line.startswith("SetFontSize")] + QUIET_STYLE
        if name == self.ordered[0][0]:
            shape = "Star"
        return [" ".join(line.split()[:3] + [shape]) if line.startswith("MinimapIcon") else line
                for line in lines]

    def action(self, name):
        return "Hide" if self.hidden(name) else "Show"


def fetch_json(url, cache_file, max_age_min, refresh):
    if (not refresh and cache_file.exists()
            and time.time() - cache_file.stat().st_mtime < max_age_min * 60):
        return json.loads(cache_file.read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def detect_league(cfg, args):
    if args.league:
        return args.league
    if cfg["league"] != "auto":
        return cfg["league"]
    state = fetch_json(f"{NINJA}/data/index-state", ROOT / "cache" / "poe2" / "index-state.json",
                       60, args.refresh)
    for league in state.get("economyLeagues", []):
        name = league.get("name", "")
        if (league.get("indexed") and not league.get("hardcore")
                and name not in ("Standard", "Hardcore")
                and not any(word in name for word in ("SSF", "Ruthless", "Hardcore"))):
            return name
    if any(league.get("name") == "Standard" and league.get("indexed")
           for league in state.get("economyLeagues", [])):
        return "Standard"
    raise RuntimeError("poe.ninja reports no indexed PoE2 trade league.")


def fetch_all(league, cfg, refresh):
    cache_name = re.sub(r"[^A-Za-z0-9._-]+", "_", league).strip("._")
    if not cache_name:
        raise ValueError(f"Invalid league name: {league!r}")
    cache = ROOT / "cache" / "poe2" / cache_name
    query = urllib.parse.urlencode({"league": league})
    data = {"exchange": {}}
    for item_type in cfg["exchange"]["types"]:
        url = f"{NINJA}/economy/exchange/current/overview?{query}&type={urllib.parse.quote(item_type)}"
        data["exchange"][item_type] = fetch_json(
            url, cache / f"ex_{item_type}.json", cfg["cache_minutes"], refresh)
    return data


def currency_conversion(core):
    """Return chaos per primary unit and divine price in chaos, when available."""
    primary = core.get("primary")
    rates = core.get("rates", {})
    if primary == "chaos":
        chaos_per_primary = 1.0
    else:
        chaos_per_primary = rates.get("chaos")
    if not isinstance(chaos_per_primary, (int, float)) or chaos_per_primary <= 0:
        return None, None
    if primary == "divine":
        divine_chaos = chaos_per_primary
    elif primary == "chaos":
        divine_rate = rates.get("divine")
        divine_chaos = 1 / divine_rate if isinstance(divine_rate, (int, float)) and divine_rate > 0 else None
    else:
        divine_rate = rates.get("divine")
        divine_chaos = (chaos_per_primary / divine_rate
                        if isinstance(divine_rate, (int, float)) and divine_rate > 0 else None)
    return float(chaos_per_primary), divine_chaos


def price_exchange(data, cfg):
    """Return name -> (chaos price, feed type, chaos-equivalent market volume)."""
    prices = {}
    divine_chaos = None
    for item_type, feed in data["exchange"].items():
        core = feed.get("core", {})
        chaos_per_primary, divine_rate = currency_conversion(core)
        if feed.get("lines") and chaos_per_primary is None:
            raise ValueError(f"{item_type} feed has prices but no conversion to chaos: {core}")
        if divine_rate:
            divine_chaos = divine_rate
        names = {item.get("id"): item.get("name") for item in feed.get("items", [])}
        for line in feed.get("lines", []):
            name = names.get(line.get("id"))
            if not name or chaos_per_primary is None:
                continue
            value = line.get("primaryValue")
            volume = line.get("volumePrimaryValue", 0)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                continue
            if not isinstance(volume, (int, float)) or not math.isfinite(volume):
                volume = 0
            price = (value * chaos_per_primary, item_type, volume * chaos_per_primary)
            if name not in prices or price[0] > prices[name][0]:
                prices[name] = price
    return prices, divine_chaos


def build_text(cfg, data, league):
    prices, divine_chaos = price_exchange(data, cfg)
    tiers = Tiers(cfg, divine_chaos)
    singles = {}
    stacks = {}
    for name, (value, item_type, volume) in prices.items():
        if name in PINNED_TOP:
            continue
        tier = tiers.of(value)
        reliable = volume >= cfg["exchange"]["min_volume"]
        if tiers.hidden(tier) and not reliable:
            tier = "unknown"
        shape = SHAPES.get(item_type, "Diamond")
        singles.setdefault((tier, shape), []).append(name)
        if tier == "unknown" or item_type != "Currency":
            continue
        for target, threshold in tiers.ordered:
            count = math.ceil(threshold / value - 1e-9)
            if count > 1 and count <= cfg["exchange"]["max_stack"]:
                stacks.setdefault((target, count, shape), []).append(name)

    divine_label = f"{divine_chaos:.2f}c" if divine_chaos else "unknown"
    header = (f"# PoE2 price filter - generated {datetime.now():%Y-%m-%d %H:%M}\n"
              f"# League: {league}   Divine = {divine_label}\n"
              "# Prices: poe.ninja Currency and Runes exchange feeds; prices are chaos-equivalent.\n"
              "# Do not edit - edit config_poe2.toml and rerun build_filter_poe2.py\n")
    out = [header]
    for name in sorted(PINNED_TOP):
        out.append(block("Show", [f"BaseType == {q([name])}"], tiers.style(tiers.ordered[0][0], "Circle"),
                          f"pinned {name}"))

    out.append("\n# Stack-size alerts: a full stack can reach a higher price tier.\n")
    for target, _ in tiers.ordered:
        for (tier, count, shape), names in sorted(stacks.items()):
            if tier == target:
                out.append(block(tiers.action(tier),
                                 [f"StackSize >= {count}", f"BaseType == {q(names)}"],
                                 tiers.style(tier, shape), f"{tier} stack x{count}"))
        for (tier, shape), names in sorted(singles.items()):
            if tier == target:
                out.append(block(tiers.action(tier), [f"BaseType == {q(names)}"],
                                 tiers.style(tier, shape), tier))

    hidden_names = [name for (tier, _), names in singles.items() if tier == "hide" for name in names]
    if hidden_names:
        out.append(block("Hide", [f"BaseType == {q(hidden_names)}"], HIDDEN_STYLE,
                         "priced below lowest tier"))

    unknown = singles.get(("unknown", "Circle"), []) + singles.get(("unknown", "Moon"), [])
    if unknown:
        out.append(block("Show", [f"BaseType == {q(unknown)}"], STYLES["unknown"],
                         "low-volume price: never hide"))

    classes = cfg["gear"]["classes"]
    if cfg["gear"]["hide_normal_magic_after_area"] >= 0:
        out.append(block(
            "Hide",
            [f"AreaLevel >= {cfg['gear']['hide_normal_magic_after_area']}",
             "Rarity <= Magic", f"Class == {q(classes)}"],
            HIDDEN_STYLE, "hide normal/magic gear after configured area level"))
    out.append(block("Show", ["Rarity Unique"], STYLES["unknown"], "unpriced uniques: review"))
    out.append(block("Show", [], [], "unmatched items: keep visible"))
    return "".join(out), {"prices": prices, "divine": divine_chaos, "tiers": tiers}


def load_cfg():
    with (ROOT / "config_poe2.toml").open("rb") as f:
        return tomllib.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="ignore price cache")
    parser.add_argument("--league", help="override league name")
    args = parser.parse_args()
    cfg = load_cfg()
    league = detect_league(cfg, args)
    print(f"PoE2 league: {league}")
    data = fetch_all(league, cfg, args.refresh)
    text, result = build_text(cfg, data, league)
    out_file = ROOT / "out" / f"{cfg['output_name']}.filter"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(text, encoding="utf-8")
    for directory in cfg["output_dirs"]:
        destination = Path(directory).expanduser()
        if destination.is_dir():
            shutil.copy2(out_file, destination / out_file.name)
            print(f"Copied to {destination / out_file.name}")
        else:
            print(f"Skip missing output dir: {destination}", file=sys.stderr)
    print(f"Priced items: {len(result['prices'])}")
    print(f"Divine: {result['divine']:.2f}c" if result["divine"] else "Divine price unavailable")
    print(f"Written: {out_file}")


if __name__ == "__main__":
    main()
