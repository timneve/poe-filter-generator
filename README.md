# poe-filter-generator

PoE1 loot filter where visibility = poe.ninja price. Python 3.11+, no dependencies.

## Setup (Windows)

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/). During
   setup, enable **Add Python to PATH**.
2. Clone this repository and open a terminal in the `poe-filter` folder.
3. Run `update.bat` for PoE1, or `update_poe2.bat` for PoE2. The first run needs an internet
   connection to download current price data. No additional Python packages are required.
4. In Path of Exile, open **Options -> Game -> Item Filter**, select `pricefilter` (PoE1) or
   `pricefilter_poe2` (PoE2), and reload after future updates.

The generated filters are saved under `out/`. By default, each script also copies its filter
to the corresponding Path of Exile folder under `Documents\My Games` when that folder exists.
You can run the Python scripts directly instead of the batch files:
`python build_filter.py --refresh` or `python build_filter_poe2.py --refresh`.

- `config.toml` - tiers (fractions of a divine: top 1, high 1/4, mid 1/16, minor 1/64, low 1/256,
  brown 1/1024, dust = everything cheaper), variable line (divine), confidence limits, overrides, styles,
  `show_gold` (default off: all gold hidden)
- Visible item labels use maximum font size 45; explicit content-module always-show overrides
  retain their deliberately smaller size.
- `hide_forbidden_tome` in `config.toml` hides Forbidden Tome regardless of price; set it to
  `false` to show it normally.
- `show_5_links` and `show_6_links` in `config.toml` independently control generic 5-link and
  6-link item alerts.
- `show_mirrored` in `config.toml` controls the optional blue, non-tink mirrored-item rule
  (disabled by default).
- Vendor recipes (`[vendor_recipes.<name>]`): show a recipe's ingredients (any rarity) with a
  Diamond icon in the recipe's `tier` style. The tier is a floor: an ingredient whose own price tier
  is better keeps it (a tink Fugitive Ring stays a tink, a blue unique base stays blue, a pricey
  ilvl 86 crafting base or an `[overrides]` base keeps its tier); a cheap or hidden one gets the
  recipe tier. Ingredients are `bases` (exact base types) or `conds` (filter conditions, e.g.
  RGB sockets) with optional `class` / `rarity`.
  `tier` can also be `"variable"` (blue). Tier order: top, high, mid, minor, variable, low,
  brown, dust (`variable_after`), so a blue recipe only lifts low / brown / dust / hidden items.
  `grasping_mail` (on, tier variable): Cryonic / Enthalpic / Fugitive / Organic / Synaptic Ring, any
  rarity incl. unique, any state (poewiki: unidentified, corrupted or split are fine; Formless
  Ring is not part of it).
  Currency recipes as in NeverSink's regular filter (tier low; jeweller off by default): `chromatic` (R-G-B linked,
  any size), `jeweller` (6 sockets), `gemcutter` (gems with any quality; Awakened / 20% gems keep
  their own rules), `glassblower` (20% quality white flasks). Normal / magic / rare.
- `[overquality]` - quality thresholds for non-mirrored, non-corrupted gear (30% on by default;
  27% and 21% are optional)

## PoE2
Run `update_poe2.bat` (or `python build_filter_poe2.py --refresh`). This writes
`out/pricefilter_poe2.filter` and copies it to `Documents/My Games/Path of Exile 2` when that
folder exists. Settings are in `config_poe2.toml`; price data is cached under `cache/poe2/`.

Prices come from all poe.ninja PoE2 exchange feeds (currency, fragments, abyss, uncut and lineage
gems, essences, soul cores, idols, runes, omens, expedition, delirium, breach). Tiers are fractions
of a divine in `[tiers]` of `config_poe2.toml` (top = 1 div, high = 1/4, mid = 1/16, minor = 1/64,
low = 1/256, brown = 1/1024, dust = everything cheaper), so they follow the economy: early league
exalts, later chaos. Which tiers hide or go quiet: `hide_tiers` / `quiet_tiers`. A stack big enough
to reach a higher tier gets its own alert. Gold is hidden unless `show_gold = true`. Every shown
item uses full text size.
Divine, Mirror and Hinekora's Lock are always top.

A price is trusted only with enough trade volume. Thin-market items never tink: they use
NeverSink's tier if NeverSink lists them, else show blue.

Each build also writes `out/report_poe2.html`: tier values in exalts (plus divine fractions), the
div:ex and div:chaos rates, and every priced item with its tier and whether the filter shows it.

Everything else (gear, rares, uniques, waystones, campaign, unpriced items) comes from the
NeverSink/FilterBlade PoE2 export in `reference/league-filterblade-poe2.filter`, appended below the
price rules with borders and backgrounds removed except on its top tier. To change that part,
export a new filter from FilterBlade and replace the file.

## League start
Set `league_start = true` (top of `config.toml`), run `update.bat`. Shows (almost) everything:
no hidden tiers, wrist saver off, all unique tiers on, other min tiers at the lowest tier, "hide" overrides shown,
content modules on, and rules-file blocks tagged `Hide # league_start` (maps, gems, small
gold when `show_gold`) shown. Only plain gear in maps and white crafting
bases the `[leveling] build` never uses (rf: pure ES, unused weapons; unless worth
`bases.min_tier`, `league_start_hide_unused`) stay hidden.
Set it back to `false` after a few days.

## Campaign
`[leveling]` copies NeverSink's leveling rules (flasks, rares, links, early currency, ...)
from `reference/league.filter` each build, at a NeverSink `strictness` (0 soft .. 4 very
strict). Every block is gated `AreaLevel <= 67` (and `Rarity <= Rare`), so it does nothing
in maps and never hides a unique.

Build module: `[leveling] build = "rf"` puts `rules/leveling/rf.filter` first (Pohx RF:
armour/evasion only, never pure ES, 2H axes until the RF swap, guide uniques, Iron/Ruby
rings, transmutes, RF-colour links). Other build: copy the file, edit, change `build`.
White gear: only the types in the build's `Show # whites` block, up to area
`hide_normal_after` (no build: all white gear up to there). Magic gear: up to area
`hide_magic_after` (`keep_build_weapons_magic`: the build's magic weapons still show). Small gold shows in the
campaign. `show_gems`: all skill / support gems in the campaign. `show_magic_vendor` and
`show_rare_vendor` independently enable magic and rare vendor items; `show_magic_rare_cells = 4`
limits them to actual base dimensions (Width x Height), so a small shield can show even when
other bases in the Shields class are larger. Vendor Shows take priority over campaign gear Hides.
`reference/pohx-campaign.filter` is Pohx's FilterBlade filter, reference only.
- `rules/top.filter` - hand rules before price rules (quest items, gold, 6L)
- `rules/bottom.filter` - hand rules after (maps, gems, hide gear, blue safety net)
- `reference/league.filter` - old FilterBlade/NeverSink filter, reference only
- `cache/` - downloaded prices, `out/` - built filter (also copied to My Games/Path of Exile)

## Price sources
- Stackables (currency, cards, scarabs, essences, fossils, oils, omens, tattoos, fragments, ...):
  poe.ninja Currency Exchange data. Stack sizes count (10x 0.5c = 5c tier).
- Currency shards use one twentieth of the finished currency's price rather than sparse shard
  quotes; configured splinters use the finished item price divided by the completion count.
- Divination-card quotes are not used because the available poe.ninja exchange data does not
  distinguish buy orders from sell quotes. Configured deterministic rewards use the exact
  reward item's price (currency-exchange items, including fragments/scarabs, named unique
  items/maps from listings, or another configured exact card reward) divided by the set size.
  The exact reward valuation wins even when the aggregate card quote differs by 10× or more.
  Random, selectable, corrupted, variable-
  outcome, and generic-category rewards are excluded. Other unpriced cards use the regular NeverSink
  divination-card groups only when exchange activity is below
  `[exchange].card_fallback_min_volume` (default 5 chaos-equivalent volume). The feed has no
  buy/sell direction or exact trade count, so cards with activity at/above the threshold but
  no reliable price stay unknown (blue beam/icon, grey-white text, no drop sound), not treated
  as priced. Only configured guaranteed rewards are used; random item rewards are not.
- Divine Orb, Mirror of Kalandra, and Hinekora's Lock are pinned to the top/tink style
  regardless of their poe.ninja prices or manual overrides.
- Uniques: poe.ninja listings. A base is tiered by its CHEAPEST unique (no clicking 1c junk
  for a maybe-20c). Exception: any unique on the base >= `jackpot_divine` -> variable style.
  Which price tiers show: `[uniques] show.<tier> = true/false` (default top/high/mid on).
  Unique jewels (`variable_classes`, Jewels + Abyss Jewels) are always blue, unless every unique
  on the base is >= 1 div (tink).
- Jackpot (`jackpot_divine`, top of config): ANY item worth that much is never hidden. Unique,
  Foulborn and 5L/6L unique bases and crafting base ilvl ranges with a jackpot go variable.
  Per unique the cheapest variant is used (Mageblood = 2-flask price).
- Uniques that can't drop in a normal map (uber/pinnacle bosses, Breachlords, Atziri, Syndicate,
  Delve, Heist + Replicas, Incursion temple, Lab, recipes, upgrades) are skipped from pricing,
  so a boss chase never makes a junk base blue and a junk boss unique never drags a base down
  (Lab-only Winds of Change doesn't hide Hateforge's Ancient Gauntlets). Enabling the matching `[content.<name>]` module
  opts those drops into normal poe.ninja pricing (+ faded show when price hides them). Source: poewiki drop-restricted flag + drop
  source (`cache/wiki_uniques.json`); `[uniques] map_sources` / `[uniques.map_drop]` to tune.
  Bossing: toggle the filter off in game. Report lists them as category "No map drop".
- Content modules (`[content.<name>]`, toggle): Ultimatum, Blight, Breach (boss / encounter /
  instance-only uniques). On: its uniques are priced normally (Breach on: Titan Greaves blue from
  1c Red Trail), and a base the price rules would hide still shows small + faded when one of its
  content uniques is itself in a shown unique tier (Amber Amulet: 2 div Xoph's Blood), so the
  valuable encounter drop isn't missed; cheap content uniques stay hidden; normal mapping is otherwise unchanged. Off: those uniques are
  ignored on shared bases (Titan Greaves = Kaom's Roots tier); bases with only that content's
  uniques stay blue. `[content.<name>.drops]`: `"price"` (default), `true` to always show faded,
  or `false` to always hide a specific unique's base. PoE filters cannot
  distinguish drop sources or unique names before identification, so pricing and overrides
  apply globally to the base and can affect other uniques sharing it. Always-show drops use
  the small, silent `[style.content]` with a slightly translucent label background.
  `league_start = true` enables all content modules.
- Foulborn uniques: own tiers per base (cheapest variant = tier, best variant >= jackpot_divine = blue), hidden below `foulborn.min_tier`.
- Unknown value (`unknown_as_variable`, toggle): a unique base is only tiered when every unique the
  wiki says can drop on it has a confident poe.ninja price; otherwise blue variable.
- Wrist saver (`[small_loot]`, toggle): non-stackable loot (uniques, Foulborn, invitations, wombgifts) below tier `min_tier` (default minor = 1/64 div) is hidden. Jackpots still show. Ancient Wombgift is guaranteed at least the minor (white) tier; higher prices use their normal price tier.
- Crafting bases: poe.ninja base prices by ilvl + influence, only at `bases.min_tier` and up.
  `[bases]` requires both `min_listings` and `min_samples`; raise these thresholds to ignore
  prices with too little supporting market data. A confident listing prices only its own ilvl
  range; a cheaper higher-ilvl listing does not floor it.
- Endgame rares (`rares.*`, top of `config.toml`): poe.ninja has no rare prices, so ilvl 68+
  rares use NeverSink's FilterBlade base tiers (`t1` best .. `t5`). Separate tier lists for
  `rares.weapons`, `rares.armour` and `rares.jewellery` (amulets, rings, belts); `"all"` = every
  base, `[]` = none. `rares.show."<Class>" = false` hides one class (e.g. Helmets, Two Hand Swords)
  whatever its tier. `rares.min_ilvl.weapons` / `.armour` / `.jewellery` (default 75, floor 68) drop low item levels per group. Shown rares (default `t1`, `t2`) get muted yellow (`rares.text_color`), no
  sound/beam/icon; other rares stay hidden. League start `["all"]`, then tighten to `[]`.

Blue item in game = value unknown or variable. Add it to `[overrides]` or a rules file.

## Tests
`python -m unittest discover tests` - checks nothing valuable gets hidden. Synthetic tests
check the pricing rules; live tests build the filter from `cache/` and replay every priced
unique (unidentified, >= 1 div), stackable, card and crafting base through
`filtersim.py` (a small filter evaluator). Run after changing config or rules.

## Report
Each build writes `out/report.html`. Open it in a browser. The header shows 1 div in chaos and each
tier's chaos value (with its divine fraction; hidden/quiet tiers marked), plus "Unique tiers":
vertical Shown / Hidden lists of the unique tiers (`[uniques] show`, or `[small_loot]`; hover for why). Paste copied in-game item text into
"Check an item" to see matching rules and the first rule that decides visibility. Set the area
level to where the item dropped; the report defaults it to 83. Corrupted implicit count can be
entered when relevant, and optional properties absent from copied text are reported unresolved
instead of guessed. "Look at these first" groups the
hidden items worth >= safety by why they hide (jackpot leak, linked unique, chase unique on a
junk base, crafting base with real volume), with the config knob to change. "League content
modules" has one collapsed dropdown per `[content.*]` module (on/off, shown / faded / hidden counts)
listing every base its uniques drop on: how an unidentified drop looks now (price tier, faded,
hidden), the content uniques with prices, and the deciding rule. "Vendor recipes" has one
collapsed dropdown per `[vendor_recipes.*]` recipe (on/off, tier, shown / hidden counts): each
ingredient dropped as normal, magic, rare and unidentified unique (`conds` recipes: one example
item per `rarity`; with the recipe's `any`
condition, if set), allowed states + `note`, its look now, and the deciding rule (a better unique tier wins over the recipe). The table, "Hidden, worth a
look", lists items the filter hides even though they're priced >= tier `[report] review_tier`,
with the rule that hides them; hidden 6L / 5L uniques sit in their own collapsed sections below it.
Below it, "All items" has every priced item with its in-game
look, searchable and filterable by category and shown / hidden.
