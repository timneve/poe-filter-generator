"""Build a PoE2 loot filter: poe.ninja exchange prices tiered in divines, on top of NeverSink's filter."""
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

from build_filter import apply_palette

ROOT = Path(__file__).resolve().parent
NINJA = "https://poe.ninja/poe2/api"
UA = {"User-Agent": "price-filter-builder/1.0 (personal loot filter script)"}
PINNED_TOP = {"Divine Orb", "Mirror of Kalandra", "Hinekora's Lock"}
# Minimap shape per poe.ninja feed (top tier always Star). Unlisted feeds -> Diamond.
SHAPES = {"Currency": "Circle", "Essences": "Circle", "Ritual": "Circle",
          "Fragments": "Hexagon", "Breach": "Hexagon", "Delirium": "Hexagon",
          "Expedition": "Hexagon", "Abyss": "Hexagon",
          "Runes": "Moon", "SoulCores": "Moon", "Idols": "Moon",
          "UncutGems": "Triangle", "LineageSupportGems": "Triangle"}
# Feeds whose items never stack: no stack-size blocks.
NO_STACK = {"UncutGems", "LineageSupportGems"}
# poe.ninja "Uncut Skill Gem (Level 19)" = BaseType "Uncut Skill Gem" + GemLevel 19.
# (Other feeds' "(Level N)" names, e.g. Thaumaturgic Flux, are the literal BaseType.)
LEVELED_FEEDS = {"UncutGems"}
LEVELED = re.compile(r"^(.*) \(Level (\d+)\)$")
HIDDEN_STYLE = ["SetFontSize 18", "DisableDropSound True"]
STYLES = {
    "top": ["SetFontSize 45", "SetTextColor red", "SetBorderColor red",
            "SetBackgroundColor tink_bg", "PlayAlertSound 6 300", "PlayEffect Red",
            "MinimapIcon 0 Red Star"],
    "high": ["SetFontSize 45", "SetTextColor red", "PlayAlertSound 1 300",
             "PlayEffect Red", "MinimapIcon 1 Red Circle"],
    "mid": ["SetFontSize 45", "SetTextColor yellow", "PlayAlertSound 2 300",
            "PlayEffect Yellow", "MinimapIcon 1 Yellow Circle"],
    "minor": ["SetFontSize 40", "SetTextColor white", "PlayAlertSound 2 300",
              "PlayEffect White", "MinimapIcon 1 White Circle"],
    "low": ["SetFontSize 35", "SetTextColor white", "PlayAlertSound 2 300",
            "PlayEffect White", "MinimapIcon 1 White Circle"],
    "brown": ["SetFontSize 30", "SetTextColor brown", "DisableDropSound True"],
    "dust": ["SetFontSize 25", "SetTextColor brown", "DisableDropSound True"],
    "unknown": ["SetFontSize 40", "PlayAlertSound 2 300", "PlayEffect Blue",
                "MinimapIcon 1 Blue Diamond"],
}
QUIET_STYLE = ["SetTextColor brown", "PlayEffect Grey",
               "MinimapIcon 2 Grey Circle", "DisableDropSound True"]
# reference export's tink blocks (white background, numbers: before apply_palette)
TINK_BACKGROUND = "SetBackgroundColor 255 255 255 255"
GOLD_HIDE = 'Hide # gold (show_gold = false)\n\tBaseType == "Gold"\n' + "".join(f"\t{line}\n" for line in HIDDEN_STYLE)


def q(names):
    return " ".join(json.dumps(name, ensure_ascii=False) for name in sorted(names))


def block(action, conditions, style, comment=""):
    head = action + (f" # {comment}" if comment else "")
    return "\n".join([head] + [f"\t{condition}" for condition in conditions]
                     + [f"\t{line}" for line in style]) + "\n"


class Tiers:
    """Tier thresholds are fractions of 1 divine, so they follow the economy on their own."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ordered = sorted(((name, float(value)) for name, value in cfg["tiers"].items()),
                              key=lambda pair: -pair[1])

    def of(self, div):
        for name, threshold in self.ordered:
            if div >= threshold:
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


def cache_dir(league):
    cache_name = re.sub(r"[^A-Za-z0-9._-]+", "_", league).strip("._")
    if not cache_name:
        raise ValueError(f"Invalid league name: {league!r}")
    return ROOT / "cache" / "poe2" / cache_name


def fetch_all(league, cfg, refresh):
    cache = cache_dir(league)
    query = urllib.parse.urlencode({"league": league})
    data = {"exchange": {}}
    for item_type in cfg["exchange"]["types"]:
        url = f"{NINJA}/economy/exchange/current/overview?{query}&type={urllib.parse.quote(item_type)}"
        data["exchange"][item_type] = fetch_json(
            url, cache / f"ex_{item_type}.json", cfg["cache_minutes"], refresh)
    return data


def divine_per_primary(core):
    """Divines per 1 unit of the feed's primary currency (rates = units per 1 primary)."""
    if core.get("primary") == "divine":
        return 1.0
    rate = core.get("rates", {}).get("divine")
    return float(rate) if isinstance(rate, (int, float)) and rate > 0 else None


def price_exchange(data):
    """Return name -> (price in divines, feed type, traded volume in divines)."""
    prices = {}
    for item_type, feed in data["exchange"].items():
        core = feed.get("core", {})
        factor = divine_per_primary(core)
        if feed.get("lines") and factor is None:
            raise ValueError(f"{item_type} feed has prices but no conversion to divine: {core}")
        names = {item.get("id"): item.get("name") for item in feed.get("items", [])}
        for line in feed.get("lines", []):
            name = names.get(line.get("id"))
            value = line.get("primaryValue")
            volume = line.get("volumePrimaryValue", 0)
            if not name or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                continue
            if not isinstance(volume, (int, float)) or not math.isfinite(volume):
                volume = 0
            price = (value * factor, item_type, volume * factor)
            if name not in prices or price[0] > prices[name][0]:
                prices[name] = price
    return prices


def per_divine(prices, name):
    """How many `name` buy 1 divine (e.g. chaos per divine), or None if unpriced."""
    return 1 / prices[name][0] if name in prices else None


def fmt(div, prices):
    """Price in the unit players think in: div, else chaos, else exalted."""
    if div >= 1:
        return f"{div:.2f} div"
    for name, unit in (("Chaos Orb", "c"), ("Exalted Orb", "ex")):
        rate = per_divine(prices, name)
        if rate and div * rate >= 1:
            return f"{div * rate:.1f}{unit}"
    rate = per_divine(prices, "Exalted Orb")
    return f"{div * rate:.2f}ex" if rate else f"{div:.4f} div"


def reliable(cfg, value, volume):
    """Enough trade to trust the price: min_volume divines traded, and either min_units items
    or trusted_volume divines (expensive items trade few units)."""
    ex = cfg["exchange"]
    return (volume >= ex["min_volume"]
            and (volume / value >= ex["min_units"] or volume >= ex["trusted_volume"]))


def item_key(name, item_type):
    """-> (BaseType, GemLevel or None)."""
    match = LEVELED.match(name) if item_type in LEVELED_FEEDS else None
    return (match.group(1), int(match.group(2))) if match else (name, None)


def item_conditions(names, level):
    return [f"BaseType == {q(names)}"] + ([f"GemLevel == {level}"] if level else [])


def reference_basetypes(text):
    """Every BaseType named in an active (uncommented) reference block."""
    names = set()
    for line in text.splitlines():
        if line.strip().startswith("BaseType"):
            names.update(re.findall(r'"([^"]+)"', line))
    return names


def reference_body(text):
    """NeverSink's rules from the first section holding a block, calmed to our style:
    border/background only on tink (white background) blocks."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(("Show", "Hide", "Minimal")))
    while first > 0 and lines[first - 1].startswith("#"):
        first -= 1
    chunks = "\n".join(lines[first:]).split("\n\n")
    calm = []
    for chunk in chunks:
        if TINK_BACKGROUND not in chunk:
            chunk = "\n".join(line for line in chunk.split("\n")
                              if not line.strip().startswith(("SetBorderColor", "SetBackgroundColor")))
        calm.append(chunk)
    return "\n\n".join(calm) + "\n"


def maximize_item_sizes(text):
    """Every shown item at full text size (hidden ones stay small)."""
    out = []
    for blk in re.split(r"(?m)(?=^(?:Show|Hide|Minimal)\b)", text):
        if blk.startswith(("Show", "Minimal")):
            blk = re.sub(r"(?m)^(\s*SetFontSize\s+)\d+\b", r"\g<1>45", blk)
        out.append(blk)
    return "".join(out)


def build_text(cfg, data, league, reference_text):
    prices = price_exchange(data)
    tiers = Tiers(cfg)
    ref_names = reference_basetypes(reference_text)
    singles = {}    # (tier, shape, level) -> [basetype]
    stacks = {}     # (target tier, count, shape) -> [basetype]
    deferred = []   # thin market, NeverSink tiers it
    for name, (value, item_type, volume) in prices.items():
        if name in PINNED_TOP:
            continue
        base, level = item_key(name, item_type)
        shape = SHAPES.get(item_type, "Diamond")
        if not reliable(cfg, value, volume):
            if base in ref_names:
                deferred.append(name)
                continue
            tier = "unknown"
        else:
            tier = tiers.of(value)
        singles.setdefault((tier, shape, level), []).append(base)
        if tier == "unknown" or item_type in NO_STACK:
            continue
        for target, threshold in tiers.ordered:
            count = math.ceil(threshold / value - 1e-9)
            if 1 < count <= cfg["exchange"]["max_stack"] and not tiers.hidden(target):
                stacks.setdefault((target, count, shape), []).append(base)

    rates = "   ".join(f"{label} = {rate:.1f}" for label, rate in
                       (("chaos/div", per_divine(prices, "Chaos Orb")),
                        ("ex/div", per_divine(prices, "Exalted Orb"))) if rate)
    tier_line = ", ".join(f"{name} {fmt(value, prices)}" for name, value in tiers.ordered)
    header = (f"# PoE2 price filter - generated {datetime.now():%Y-%m-%d %H:%M}\n"
              f"# League: {league}   {rates}\n"
              f"# Tiers: {tier_line}\n"
              f"# Prices: poe.ninja exchange ({', '.join(data['exchange'])}), tiered in divines.\n"
              "# Below the price rules: NeverSink's PoE2 filter (reference/), calmed.\n"
              "# Do not edit - edit config_poe2.toml and rerun build_filter_poe2.py\n")
    out = [header]
    for name in sorted(PINNED_TOP):
        out.append(block("Show", [f"BaseType == {q([name])}"], tiers.style(tiers.ordered[0][0], "Circle"),
                         f"pinned {name}"))

    out.append("\n# Price tiers. Stack-size blocks: a full stack reaches a higher tier.\n")
    for target, _ in tiers.ordered:
        for (tier, count, shape), names in sorted(stacks.items()):
            if tier == target:
                out.append(block(tiers.action(tier), [f"StackSize >= {count}", f"BaseType == {q(names)}"],
                                 tiers.style(tier, shape), f"{tier} stack x{count}"))
        for (tier, shape, level), names in sorted(singles.items(), key=lambda kv: (kv[0][1], kv[0][2] or 0)):
            if tier == target:
                out.append(block(tiers.action(tier), item_conditions(names, level),
                                 tiers.style(tier, shape), tier))

    for (tier, _, level), names in sorted(singles.items(), key=lambda kv: (kv[0][1], kv[0][2] or 0)):
        if tier == "unknown":
            out.append(block("Show", item_conditions(names, level), STYLES["unknown"],
                             "thin market, not in NeverSink: never hide"))
        elif tier == "hide":
            out.append(block("Hide", item_conditions(names, level), HIDDEN_STYLE,
                             "priced below lowest tier"))

    if not cfg.get("show_gold", False):
        out.append(GOLD_HIDE)
    out.append("\n# ===== NeverSink PoE2 rules (gear, uniques, waystones, unpriced items) =====\n\n")
    out.append(reference_body(reference_text))
    return apply_palette(cfg, maximize_item_sizes("".join(out))), {"prices": prices, "tiers": tiers, "deferred": deferred}


def load_cfg():
    """config_poe2.toml + the shared colour palette (config.toml [colors], unless set here)."""
    with (ROOT / "config_poe2.toml").open("rb") as f:
        cfg = tomllib.load(f)
    if "colors" not in cfg:
        with (ROOT / "config.toml").open("rb") as f:
            cfg["colors"] = tomllib.load(f)["colors"]
    return cfg


def load_reference(cfg):
    return (ROOT / cfg["reference"]).read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="ignore price cache")
    parser.add_argument("--league", help="override league name")
    args = parser.parse_args()
    cfg = load_cfg()
    league = detect_league(cfg, args)
    print(f"PoE2 league: {league}")
    data = fetch_all(league, cfg, args.refresh)
    text, result = build_text(cfg, data, league, load_reference(cfg))
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
    prices = result["prices"]
    print(f"Priced items: {len(prices)}  (thin market left to NeverSink: {len(result['deferred'])})")
    for name in ("Chaos Orb", "Exalted Orb"):
        if name in prices:
            print(f"{name}: {fmt(prices[name][0], prices)} = {prices[name][0]:.4f} div")
    print(f"Written: {out_file}")
    import report_poe2  # imports this module; keep it out of the import-time cycle
    print(f"Report:  {report_poe2.write(cfg, text, result, league, ROOT / 'out' / 'report_poe2.html')}")


if __name__ == "__main__":
    main()
