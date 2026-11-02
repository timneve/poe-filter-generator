# poe-filter-generator

PoE1 loot filter where visibility = poe.ninja price. Python 3.11+, no dependencies.

Run `update.bat` (or `python build_filter.py --refresh`), then in game pick `pricefilter`
(Options -> Game -> Item Filter) and press reload after updates.

- `config.toml` - tiers (chaos), variable line (divine), confidence limits, overrides, styles

## League start
Set `league_start = true` (top of `config.toml`), run `update.bat`. Shows (almost) everything:
no hidden tiers, wrist saver off, all min tiers at the lowest tier, "hide" overrides shown,
content modules on, and rules-file blocks tagged `Hide # league_start` (maps, gems, small
gold) shown. Only items priced below the lowest tier, plain gear in maps and white crafting
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
campaign. `show_gems`: all skill / support gems in the campaign. `show_magic_rare_cells = 4`: magic/rare of every class up to 4 inventory cells (class
size = biggest base) shown in the campaign to vendor for currency, build Hides don't apply. `reference/pohx-campaign.filter` is Pohx's FilterBlade filter, reference only.
- `rules/top.filter` - hand rules before price rules (quest items, gold, 6L)
- `rules/bottom.filter` - hand rules after (maps, gems, hide gear, blue safety net)
- `reference/league.filter` - old FilterBlade/NeverSink filter, reference only
- `cache/` - downloaded prices, `out/` - built filter (also copied to My Games/Path of Exile)

## Price sources
- Stackables (currency, cards, scarabs, essences, fossils, oils, omens, tattoos, fragments, ...):
  poe.ninja Currency Exchange data. Stack sizes count (10x 0.5c = 5c tier).
- Uniques: poe.ninja listings. A base is tiered by its CHEAPEST unique (no clicking 1c junk
  for a maybe-20c). Exception: any unique on the base >= `jackpot_divine` -> variable style.
- Jackpot (`jackpot_divine`, top of config): ANY item worth that much is never hidden. Unique,
  Foulborn and 5L/6L unique bases and crafting base ilvl ranges with a jackpot go variable.
  Per unique the cheapest variant is used (Mageblood = 2-flask price).
- Uniques that can't drop in a normal map (uber/pinnacle bosses, Breachlords, Atziri, Syndicate,
  Delve, Heist + Replicas, Incursion temple, Lab, recipes, upgrades) are skipped from pricing,
  so a boss chase never makes a junk base blue. Source: poewiki drop-restricted flag + drop
  source (`cache/wiki_uniques.json`); `[uniques] map_sources` / `[uniques.map_drop]` to tune.
  Bossing: toggle the filter off in game. Report lists them as category "No map drop".
- Content modules (`[content.<name>]`, toggle): while farming content (Ultimatum), its uniques'
  bases show small and silent (`[style.content]`) to loot after the fight. Off in normal maps.
- Foulborn uniques: own tiers per base (cheapest variant = tier, best variant >= jackpot_divine = blue), hidden below `foulborn.min_tier`.
- Unknown value (`unknown_as_variable`, toggle): a unique base is only tiered when every unique the
  wiki says can drop on it has a confident poe.ninja price; otherwise blue variable.
- Wrist saver (`[small_loot]`, toggle): non-stackable loot (uniques, Foulborn, invitations, wombgifts) below tier `min_tier` (default mid = 1/16 div) is hidden. Jackpots still show.
- Crafting bases: poe.ninja base prices by ilvl + influence, only at `bases.min_tier` and up.
  `[bases]` requires both `min_listings` and `min_samples`; raise these thresholds to ignore
  prices with too little supporting market data.

Blue item in game = value unknown or variable. Add it to `[overrides]` or a rules file.

## Tests
`python -m unittest discover tests` - checks nothing valuable gets hidden. Synthetic tests
check the pricing rules; live tests build the filter from `cache/` and replay every priced
unique (unidentified, >= 1 div), stackable, card and crafting base through
`filtersim.py` (a small filter evaluator). Run after changing config or rules.

## Report
Each build writes `out/report.html`. Open it in a browser. "Look at these first" groups the
hidden items worth >= safety by why they hide (jackpot leak, linked unique, chase unique on a
junk base, crafting base with real volume), with the config knob to change. The table, "Hidden, worth a
look", lists items the filter hides even though they're priced >= tier `[report] review_tier`,
with the rule that hides them. Below it, "All items" has every priced item with its in-game
look, searchable and filterable by category and shown / hidden.
