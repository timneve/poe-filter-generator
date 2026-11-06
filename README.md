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
  `show_gold` (default off: all gold hidden; on: in maps stacks of at least `gold_min_stack` (10000) shown,
  smaller ones hidden; every stack in the campaign), `always_top_classes` (default Reliquary keys:
  always top tier / tink, priced or not, never hidden)
- Visible item labels use maximum font size 45; explicit content-module always-show overrides
  retain their deliberately smaller size.
- `hide_forbidden_tome` in `config.toml` hides Forbidden Tome regardless of price; `false` shows it
  (beats the map module's Sanctum Research Hides).
- `show_contracts = false` (default) hides every Heist contract, any rarity; `true` shows them all
  (beats the map module's plain-contract Hide). Quest contracts always show.
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
  any size; `sizes` = small / medium / large and `area_level` = [68, 83] give FilterBlade's RGB
  options), `jeweller` (6 sockets), `gemcutter` (gems with any quality; Awakened / 20% gems keep
  their own rules), `glassblower` (20% quality white flasks). Normal / magic / rare.
  `harbinger` (on): no blocks of its own; Harbinger uniques (Torrent's Reclamation, Yielding
  Mortality, ...) vendor for a Fracturing Shard, so unique pricing / EV counts each at least the
  shard price (Fracturing Orb / 20). Off = poe.ninja price only. Recipes with `uniques` +
  `reward` + `reward_count` work the same way.
- `[overquality]` - quality thresholds for non-mirrored, non-corrupted normal / magic / rare gear
  (30% on by default, tink look; 27% and 21% are optional). Works even with `[gear_special]` off.
- `[gear_special]` - your FilterBlade filter's influenced / eldritch / exotic-base / perfection
  rules (our module `rules/modules/gear_special.filter`, per-rule on / off in
  `modules.toml [gear_special.blocks]`, FilterBlade defaults): t1 influenced rare bases (ilvl 82+
  per influence, plus exclusive bases), heist / ritual / Kalandra / talisman / unique-only bases,
  Iron Flask, Grasping Mail, Cord Belt, Stygian Vise (abyssal or ilvl 86), Sacrificial Garb,
  Pearlescent Amulet, 28% / 21%+ quality top armour bases, 28% / 24%+ ilvl 83+ top weapon bases.
  Off by default: lower influenced tiers, Exarch / Eater implicit items, runic bases. A base with
  a poe.ninja price keeps its price look. On by default.
- `[crafting]` - FilterBlade's link / crafting / chancing rules (module
  `rules/modules/crafting.filter`, `modules.toml [crafting.blocks]`): early endgame crafting bases
  (Amethyst / Two-Stone Ring, Kinetic Wand in area 68-75) on; 5-links, ilvl 83-86 crafting matrix,
  chancing bases off. RGB and 6-socket items are the chromatic / jeweller vendor recipes. On by default.
- `[flasks]` - NeverSink's normal / magic flask + tincture rules: identified ones with good mods,
  fractured utility flasks, 21%+ quality (any flask; tinctures and utility flasks need ilvl 82+ in
  maps, 26% = louder), corrupted 30% utility flasks. A 21%+ white flask uses this look, not the
  glassblower one. Per-rule on / off in `modules.toml [flasks.blocks]` (FilterBlade defaults). On by default.
- `[exotics]` - exotic gear, shown the way your FilterBlade filter shows it (our module
  `rules/modules/exotics.filter`, per-rule on / off in `modules.toml [exotics.blocks]`, FilterBlade
  defaults): memory strands, veiled / incursion / necropolis / bestiary / delve / mercenary /
  warband / essence mods, synthesised / imbued items, voidstones, trinkets, fishing rods, unique
  pieces, quest items, rare relics, double-corrupted rares, abyss-socketed gear, fractured jewels /
  heist gear, enchanted / anointed gear, crucible items. Uniques (fishing rods, relics) keep their
  price. On by default.
- `[id_mods]` - identified gear with good mods, shown the way `reference/league.filter` shows
  them: mod combinations per slot (weapons, armour, jewellery, quivers, jewels), dual mods,
  top-value / uncorrupted single mods, veiled exceptions, corrupted items with good mods.
  Comes before crafting-base / rare Hides, so a good identified rare is never hidden. On by default.

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
Step by step (recommended): `python tools/league_start.py start` backs up `config.toml` +
`modules.toml` to `league_start/backup/` (gitignored) and writes "show (almost) everything"
values into them; over the first week `python tools/league_start.py status` lists what is
still loose and you tighten line by line (`restore KEY`, then `finish`). Guide:
[docs/LEAGUE_START.md](docs/LEAGUE_START.md).

Quick switch: `league_start = true` (top of `config.toml`) applies the same values at build
time without editing the files (one line back to `false`). Shows (almost) everything:
no hidden tiers, wrist saver off, all unique tiers on, other min tiers at the lowest tier, "hide" overrides /
unpriced tiers shown, content modules, vendor recipes and rule modules on, every normal map tier and corrupted map
shown, every gem (`[gems] show_all`), all gold (`show_gold` + `show_small_gold`: small stacks keep their small
look), 5L / 6L / mirrored / overquality / contracts / Forbidden Tome shown, every endgame rare (`[rares]`
base tiers "all" from ilvl 68), every module Show block that is off in FilterBlade on (not animated weapons,
the empty cluster economy tiers, the crafting matrix) and every module Hide off (not the map tier Hides, which
progression shows anyway, and the campaign's leveling Hides). Only plain gear in maps and white crafting
bases the `[leveling] build` never uses (rf: pure ES, unused weapons; unless worth
`bases.min_tier`: `[leveling] unused_whites_min_tier`, `league_start_hide_unused`) stay hidden.
Set it back to `false` after a few days.

## Campaign
`[leveling]` uses our module `rules/modules/leveling.filter`: NeverSink's leveling rules
(jewels, flasks, rares, links, normal / magic gear, early-currency styles) from the FilterBlade
filter, each block on / off in `modules.toml [leveling.blocks]`. Most blocks follow a NeverSink
`strictness` (0 soft .. 4 very strict), also the campaign currency sounds / icons (a price
tier that shows the item, or its stack, still wins). FilterBlade-off options: quicksilver /
utility flask alerts on (as before), rare / magic size decorators and spirit shields `false`
(league_start turns them on). Every block is gated `AreaLevel <= 67`
(and `Rarity <= Rare`), so it does nothing in maps and never hides a unique.

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
- Colours: `config.toml` `colors.*` is the palette; styles and rules use its names. Blocks copied from
  league.filter snap to the nearest palette colour (their white -> our white). Hidden gear's Alt view keeps game colours.
  PoE2 uses the same palette (its NeverSink export snaps to it too).
- `rules/top.filter` - hand rules before price rules (quest items, 5L / 6L, mirrored, gems)
- `rules/bottom.filter` - hand rules after (gems, hide gear, blue safety net)
- `rules/modules/*.filter` + `modules.toml` - our rule modules (maps, jewels + clusters, heist,
  ID mods, ...): every block on / off like FilterBlade
- `reference/league.filter` - old FilterBlade/NeverSink filter, reference only
- `cache/` - downloaded prices, `out/` - built filter (also copied to My Games/Path of Exile)

## Price sources
- Every poe.ninja PoE1 category is handled (`NINJA_TYPES` in `build_filter.py`). Each build
  reads poe.ninja's category list and warns when a new one appears; tests fail on it too.
- Stackables (currency, cards, scarabs, essences, fossils, oils, omens, tattoos, fragments,
  ducats, enshrouding crystals, corpses, incubators, memories, ...): poe.ninja Currency
  Exchange / listing data. Stack sizes count (10x 0.5c = 5c tier). Thin volume / listings
  may show an item, never hide it; unpriced currency, corpses and vials use NeverSink's tiers
  (`fallback_tiers.toml`, made once by `tools/import_fallback_tiers.py`); a hidden one still shows
  in stacks (NeverSink t5 x5, t6 x14: `[exchange.reference_currency_stacks]`).
  Items that drop in huge stacks (lifeforce, Dead Man's Sulphur, Rogue's Marker) are priced per
  stack up to `[exchange.big_stacks]` (a 1000-stack of Vivid Lifeforce gets its real tier).
  `[exchange.show_stacks]` forces a stack size to show whatever its price (Rogue's Marker 2500+,
  as FilterBlade). Fixed tiers when unpriced (`[exchange.unpriced_tiers]`: Scroll Fragment, Amber /
  Verdant Oil hidden; Omen of Refreshment / of the Soul Devourer blue). Clear Oil and Sepia Oil are always white (minor) via `[overrides]`.
- Currency shards use one twentieth of the finished currency's price rather than sparse shard
  quotes; configured splinters use the finished item price divided by the completion count.
- Divination-card quotes are not used because the available poe.ninja exchange data does not
  distinguish buy orders from sell quotes. Configured deterministic rewards use the exact
  reward item's price (currency-exchange items, including fragments/scarabs, named unique
  items/maps from listings (unlinked lines only; 5/6-link listings ignored), or another configured exact card reward) divided by the set size.
  The exact reward valuation wins even when the aggregate card quote differs by 10× or more.
  Random, selectable, corrupted, variable-
  outcome, and generic-category rewards are excluded. Other unpriced cards use the regular NeverSink
  divination-card groups (`fallback_tiers.toml [cards]`) only when exchange activity is below
  `[exchange].card_fallback_min_volume` (default 5 chaos-equivalent volume). The feed has no
  buy/sell direction or exact trade count, so cards with activity at/above the threshold but
  no reliable price stay unknown (blue beam/icon, grey-white text, no drop sound), not treated
  as priced. Only configured guaranteed rewards are used; random item rewards are not.
  A stack of 3+ unpriced cards from a hidden group still shows (`card_fallback_stack`).
- Divine Orb, Mirror of Kalandra, and Hinekora's Lock are pinned to the top/tink style
  regardless of their poe.ninja prices or manual overrides.
- Uniques: poe.ninja listings. A base is tiered by its CHEAPEST unique (no clicking 1c junk
  for a maybe-20c); `[uniques] base_price = "highest"` tiers by its priciest unique instead
  (only without `[uniques.ev]`). Exception: any unique on the base >= `jackpot_divine` -> variable style.
  Which price tiers show: `[uniques] show.<tier> = true/false` (default top/high/mid on).
  Unique jewels (`variable_classes`, Jewels + Abyss Jewels) are always blue, unless every unique
  on the base is >= 1 div (tink).
- Unique exceptions (`[unique_exceptions]`, `rules/modules/unique_exceptions.filter`, per-rule
  on / off in `modules.toml [unique_exceptions.blocks]`, FilterBlade defaults): variants the base
  price can't tell apart are shown even on a hidden base: Shaper + Elder Impresence, influenced
  Forge swords, Kaom's Heart (no sockets), 6L Tabula, synthesised, 2-4 abyss-socket, Vestigial,
  unique idols, double-corrupted, crucible and 27%+ quality uniques.
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
  valuable encounter drop isn't missed (Foulborn too: Foulborn Amber Amulet faded for a Foulborn Xoph's Blood); cheap content uniques stay hidden; normal mapping is otherwise unchanged. Off: those uniques are
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
- Wrist saver (`[small_loot]`, toggle): non-stackable loot (uniques, Foulborn, gems, invitations, wombgifts) below tier `min_tier` (default minor = 1/64 div) is hidden. Jackpots still show. Ancient Wombgift is guaranteed at least the minor (white) tier; higher prices use their normal price tier.
- Crafting bases: poe.ninja base prices by ilvl + influence, only at `bases.min_tier` and up.
  `[bases]` requires both `min_listings` and `min_samples`; raise these thresholds to ignore
  prices with too little supporting market data. A confident listing prices only its own ilvl
  range; a cheaper higher-ilvl listing does not floor it.
- Flask bases (poe.ninja Flasks feed) are priced like crafting bases.
- Cluster jewels (normal/magic/rare): poe.ninja price per base x passive count x enchant x
  ilvl bucket (1-49, 50-67, 68-74, 75-83, 84+) shows it in its price tier, also in the campaign
  (beats the build module's jewel Hide). The rest uses NeverSink's economy cluster tiers
  (`[jewels]`, module `jewels` [2805]-[2806]); its junk clusters stay hidden.
- Gems: poe.ninja price per level / quality / corrupted variant (1, 1/20, 20/20, 21/23c ...,
  like NeverSink's leveled and quality gem rules) shows valuable gems in their tier, before the
  20% / Awakened hand rules and the gemcutter recipe (a priced gem keeps its tier), from
  `[gems] min_tier` up (default mid: level 1 gems list at 5-10c nobody pays). Fewer than
  `uniques.min_listings` listings: shown blue, whatever the price (probably valuable, no exact
  price). A variant is never priced above a confidently priced better one (same corruption,
  level and quality at least as high: poe.ninja's 1 div "20" Spectral Helix vs 9c for 20/20 =
  price-fix listings). Level 21+ / quality 21+ gems without a confident price: blue too; a confident price
  below `min_tier` hides that exact variant. Transfigured gems always show (blue, NeverSink
  does the same). A gem poe.ninja doesn't list at all (new exceptional supports) shows blue; the
  rest stays hidden. Cheap level 18-20 gems are left to price (FilterBlade shows every one).
- Not used: Beasts (captured, never a ground drop).
- Maps (`[maps]`, module `maps`, every block toggled in `modules.toml [maps.blocks]`): shown /
  hidden as the FilterBlade filter, its own style. Always shown:
  Valdo, Nightmare, Shaper guardian, Zana / Elder / conqueror influenced, blighted +
  blight-ravaged, T16 Vaal Temple, enchanted, implicit, 8-mod corrupted. Unique maps:
  `uniques.hide_maps` = league.filter's rule (corrupted shown, rest hidden). Normal T1-T16:
  `progression` "none" (hidden, late league) / "all" (league start) / "auto" (a tier shows
  while you're in maps of that tier or lower: in a T1 map T1+ show, in a T5 map T5+).
  `corrupted_min_tier` (default 16): corrupted non-unique maps below it hidden, whatever rule
  would show them (8-mod, implicit, influenced, blighted, progression); Valdo / Nightmare /
  Shaper guardian and unique maps keep their rule. 0 = off. Map items: unique / enchanted
  contracts + blueprints, blueprints, logbooks, charts, reliquary keys shown; plain contracts and
  Sanctum Research hidden (unless `show_contracts` / `hide_forbidden_tome = false`); a poe.ninja price (Voidborn key) or the blue unpriced-fragment rule
  (Chronicle, Inscribed Ultimatum) wins. `enabled = false`: no map rules at all.
- Jewels (`[jewels]`, module `jewels`): corrupted-implicit jewels, uncorrupted ones with a top
  mod, corrupted rare / ilvl 83+ abyss jewels shown, other rare / magic jewels hidden (priced
  bases, ID-mod and fractured jewels decided before).
- Heist gear (`[heist]`, module `heist`): cloaks / brooches / gear / tools on top bases shown
  (ilvl 83+ louder), the rest hidden.
- Misc (`[misc]`, module `misc`): heist targets, enshrouded gear, magic / rare idols (event
  leagues), Maven's invitations, lab / incursion items shown with FilterBlade's look.
- Endgame rares (`rares.*`, top of `config.toml`; `rares.enabled` = the whole FilterBlade rare part,
  each block on/off in `modules.toml [rares.blocks]`): bigger muted-yellow text (`rares.text_color`)
  on ilvl 68+ rares, optional animated-weapon rules (off, also at league start), veiled
  rares, breach rings and top talismans shown; corrupted / mirrored unidentified rares without an
  implicit, your ilvl < 83 two-hander / body-armour hide and the endgame hide layer hide the rest.
  Priced crafting bases, jackpots and good identified rares are decided before these hides.
  `rares.base_tiers = true` also shows rares by base: poe.ninja has no rare prices, so ilvl 68+
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
`filtersim.py` (a small filter evaluator), plus every other poe.ninja feed (clusters, gems,
flasks, forbidden jewels, relics, scrying orbs, temples, maps): anything >= 1 div with
enough listings must be visible as it drops. `tests/test_parity.py` replays those items plus one
item per Show block of your FilterBlade filter (`reference/league.filter`) through both filters:
anything FilterBlade shows and ours hides must have a known reason (confident cheap price or a
listed decision). Run after changing config or rules.

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
hidden), the content uniques with prices, and the deciding rule. "Unique base EV" (collapsed,
searchable, above content modules) lists every unique base tiered by `[uniques.ev]`: EV of one
unidentified drop, tier, cheapest unique, each unique with its drop tier, drop chance on that
base and average price, and how the drop looks now. "Vendor recipes" has one
collapsed dropdown per `[vendor_recipes.*]` recipe (on/off, tier, shown / hidden counts): each
ingredient dropped as normal, magic, rare and unidentified unique (`conds` recipes: one example
item per `rarity`; with the recipe's `any`
condition, if set), allowed states + `note`, its look now, and the deciding rule (a better unique tier wins over the recipe). The table, "Hidden, worth a
look", lists items the filter hides even though they're priced >= tier `[report] review_tier`,
with the rule that hides them; hidden 6L / 5L uniques sit in their own collapsed sections below it.
Below it, "All items" has every priced item with its in-game
look, searchable and filterable by category and shown / hidden.
