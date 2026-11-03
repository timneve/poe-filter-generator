# Architecture (PoE1 `build_filter.py` unless noted)

## Pipeline

```
main()
  load_cfg()            config.toml -> split_tiers -> + unique_tiers.toml -> apply_league_start
  detect_league()       "auto" = first poe.ninja economy league not Standard/HC/SSF/Ruthless
  fetch_all()           -> data dict (cached JSON, cache_minutes)
  build_text(cfg,data)  -> (filter_text, r)    # pure: no network, no writes. Tests call this
  write out/<output_name>.filter, copy to output_dirs, print summary
  report.write()        -> out/report.html
```

## `data` dict (from `fetch_all`)

| Key | Shape | Source |
|---|---|---|
| `exchange[T]` | `{core:{primary,rates:{divine}}, items:[{id,name}], lines:[{id,primaryValue,volumePrimaryValue}]}` | poe.ninja exchange, T in `EXCHANGE_TYPES` |
| `stash[T]` | `{lines:[{name,baseType,chaosValue,listingCount,count,variant,links,levelRequired,itemType}]}` | poe.ninja stash, T in `STASH_STACKABLE_TYPES + UNIQUE_TYPES + ["BaseType"]` |
| `nomap` | `{unique name: reason}` | wiki: can't drop in normal map (boss/encounter/recipe) |
| `wiki_bases` | `{base: {unique names}}` | wiki drop-enabled uniques per base |
| `content` | `{module: {base: {names}}}` | wiki restricted uniques matching `[content.X].sources` |
| `drop_anywhere` | `{names}` | wiki enabled + not restricted |

Cache files: `cache/<league>/ex_<T>.json`, `st_<T>.json`, `cache/wiki_uniques.json`, `cache/index-state.json`. PoE2: `cache/poe2/...`.

## `build_text` steps

1. `price_stackables` (pre-divine tiers) -> `prices {name: (chaos, type)}`, `divine` chaos value.
2. `apply_divine_tiers` rewrites `cfg["tiers"]` from `div` fractions (min 1c) -> new `Tiers(cfg)`.
3. Ancient Wombgift floored to `minor`.
4. Pricing:
   - `price_unique_bases` -> `{base: (tier, cheapest, best, best_name, ev_or_None)}`
   - `price_foulborn_bases` -> `{base: (tier, cheapest, best, label)}`
   - `price_linked_jackpots` -> `{links: {bases}}` (5L/6L unique >= jackpot)
   - `price_crafting_bases` -> `[(tier, ilvl_min, ilvl_max|None, influence|None, base, chaos)]`
   - `reference_card_tiers` / `reference_currency_tiers` -> fallback tiers parsed from `reference/*.filter`
5. Emit, concatenated in this order (first non-`Continue` match wins in game):

| # | Emitter | Content |
|---|---|---|
| 1 | header | league, divine, tiers |
| 2 | `emit_forbidden_tome` | `hide_forbidden_tome` |
| 3 | `emit_content_overrides` | `[content.X.drops]` true/false |
| 4 | `emit_defaults` | `Continue` blocks: font 45, no border, gear text colour |
| 5 | `emit_pinned_stackables` | Divine/Mirror/Hinekora tink |
| 6 | `hand_rules("top")` | `rules/top.filter` (+ `# BEGIN/END show_5_links/show_6_links/show_mirrored` sections toggled) |
| 7 | `emit_leveling` | NeverSink campaign rules + build module, all `AreaLevel <= area_level_max` |
| 8 | `emit_overrides` | `[overrides]` (wrapped by `campaign_unhide`) |
| 9 | `emit_overquality` | `[overquality]` |
| 10 | `emit_stackables` | singles + stack-size lift blocks (wrapped by `campaign_unhide`) |
| 11 | `emit_uniques` | unique/foulborn/linked/maps + `emit_corrupted_uniques` |
| 12 | `emit_crafting_bases` | ilvl/influence blocks |
| 13 | `hand_rules("bottom")` | maps, gems, hide gear, blue safety net |

6. Post-process whole text: `hidden_game_colours` (hidden blocks keep game rarity colour), `maximize_item_sizes`.
7. Return `r = {tiers, prices, divine, ubases, fbases, linked, cbases, ref_cards, ref_currency, card_volumes}`.

## Tiers

- Names (best -> worst): `variable`, `top`, `high`, `mid`, `minor`, `low`, `brown`, `dust`, `unknown`, `hide`. `Tiers.rank()` gives this order (lower = better).
- `Tiers.of(chaos)` -> highest tier with threshold <= chaos, else `"hide"`.
- `hidden(cfg,tier)`: `"hide"` or in `hide_tiers`. `style_for` uses `[style.<tier>].lines`; `quiet_tiers` swap to `[style.quiet]` keeping font size; top tier forces Star icon.
- `variable` / `unknown` = blue: value unknown or varies inside the group.
- `jackpot_chaos(cfg, divine)` = `jackpot_divine * divine`.

## Unique pricing rules (`price_unique_bases`)

- Base tier = CHEAPEST confident (`listingCount >= min_listings`) unique on base; per unique its cheapest variant.
- `best` = best variant of any listing. Base would hide but best >= jackpot -> `variable` (or >= `never_hide_tier` when `variable_jackpot_only=false`).
- `[uniques.ev]` on: tier by expected value of one unID drop, weights from `unique_tiers.toml` x `tier_weights`.
- `unknown_as_variable`: any wiki unique on base lacking a confident price -> `variable`.
- `nomap` uniques skipped (boss-only can't make junk base blue) unless their content module enabled.
- Then `always_show_bases`, then `[unique_overrides]` applied last.

## Icon shapes (`SHAPE`)

Star = uniques + tink, Square = unique maps, Circle = currency/cards, Hexagon = fragments/scarabs, Diamond = bases/unknown (`BASE_SHAPE`), Moon = league stackables. Shape in config styles is replaced by code.

## Function index (grep `def name`)

- Fetch: `fetch_json`, `detect_league`, `fetch_all`, `fetch_wiki_uniques`, `non_map_drops`, `wiki_unique_bases`, `content_bases`, `content_policy`, `no_map_drop`
- Price: `Tiers`, `apply_divine_tiers`, `price_stackables`, `card_trade_volumes`, `jackpot_chaos`, `never_hide_floor`, `small_loot`, `min_shown_rank`, `unique_drop_weights`, `price_unique_bases`, `price_foulborn_bases`, `price_linked_jackpots`, `price_crafting_bases`, `reference_card_tiers`, `reference_currency_tiers`
- Emit helpers: `q(names)` quoted sorted list, `block(action, conds, style, comment)`, `hidden`, `style_for`, `action_for`, `section`
- Emit: see table above; leveling helpers `league_start_unused_whites`, `build_magic_weapons`, `campaign_unhide`, `rarities_of`, `hidden_game_colours`, `maximize_item_sizes`, `campaign_only`, `campaign_icon_sound`
- Main: `load_cfg`, `split_tiers`, `apply_league_start`, `hand_rules`, `build_text`, `main`
- Constants at top: `EXCHANGE_TYPES`, `STASH_STACKABLE_TYPES`, `UNIQUE_TYPES`, `CURRENCY_CLASSES`, `GEAR_CLASSES`, `HIDDEN_STYLE`, `SHAPE`, `PINNED_TOP_STACKABLES`; mid-file: `LEVELING_SECTIONS`, `VENDOR_CLASSES`, `NORMAL_HIDE_CLASSES`, `WEAPON_CLASSES`

## filtersim.py

- `parse(text) -> [Block(action, comment, line_no, conds, style, cont)]`
- `evaluate(blocks, item) -> (deciding_block|None, style_lines)`; `visible(blocks, item)`.
- Item dict keys: `rarity, basetype, class, influence[], mods[], socket_group` + `NUMERIC` values (`stack, ilvl, quality, links, corrupted_mods, sockets, drop_level, width, height, area_level` (default 83), `armour, evasion, es`) + `BOOL` values (`corrupted, mirrored, identified, foulborn`). Missing = 0/False.
- Modelled conditions: Class, BaseType, Rarity, numeric (`NUMERIC`), bool (`BOOL`), SocketGroup, HasExplicitMod, HasInfluence. Anything else -> `NotImplementedError`.

## report.py

`write(cfg, data, text, r, league, path)`: `collect()` replays every priced item through filtersim -> rows; `browser_rules()` serializes blocks for the in-browser "Check an item" tool; injects JSON into `PAGE` (`__DATA__`, `__LEAGUE__`). Edit HTML/JS inside `PAGE`.

## PoE2 (`build_filter_poe2.py`)

Self-contained copy of the pattern, no shared import. `load_cfg` (config_poe2.toml) -> `fetch_all` (exchange Currency, Runes) -> `currency_conversion` + `price_exchange` -> `build_text` -> write. Own `Tiers`, `STYLES`, `QUIET_STYLE`, `SHAPES`. Hides normal/magic `[gear].classes` from `hide_normal_magic_after_area`. No uniques/bases yet. Stack-size rules only for Currency.
