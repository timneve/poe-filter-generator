# poe-filter-generator

PoE1 loot filter where visibility = poe.ninja price. Python 3.11+, no dependencies.

Run `update.bat` (or `python build_filter.py --refresh`), then in game pick `pricefilter`
(Options -> Game -> Item Filter) and press reload after updates.

- `config.toml` - tiers (chaos), variable line (divine), confidence limits, overrides, styles
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
- Foulborn uniques: own tiers per base (cheapest variant = tier, best variant >= jackpot_divine = blue), hidden below `foulborn.min_tier`.
- Wrist saver (`[small_loot]`, toggle): non-stackable loot (uniques, Foulborn, invitations, wombgifts) below `min_chaos` is hidden. Jackpots still show.
- Crafting bases: poe.ninja base prices by ilvl + influence, only at `bases.min_tier` and up.

Blue item in game = value unknown or variable. Add it to `[overrides]` or a rules file.

## Tests
`python -m unittest discover tests` - checks nothing valuable gets hidden. Synthetic tests
check the pricing rules; live tests build the filter from `cache/` and replay every priced
unique (unidentified, >= 125c), stackable, card and crafting base through
`filtersim.py` (a small filter evaluator). Run after changing config or rules.

## Report
Each build writes `out/report.html`. Open it in a browser. The top table, "Hidden, worth a
look", lists items the filter hides even though they're priced >= `[report] review_chaos`,
with the rule that hides them. Below it, "All items" has every priced item with its in-game
look, searchable and filterable by category and shown / hidden.
