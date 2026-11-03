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

1. `exchange_divine(data)` -> `apply_divine_tiers` rewrites `cfg["tiers"]` (chaos) = `tiers_divine` fraction x divine, no floor -> `Tiers(cfg)`.
2. `price_stackables` -> `prices {name: (chaos, type)}`, `divine` chaos value.
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
| 6 | `hand_rules("top")` | `rules/top.filter` (+ `# BEGIN/END show_5_links/show_6_links/show_mirrored/show_gold` sections toggled; Awakened + 20% gem Shows) |
| 6b | `emit_overquality` | `[overquality]` (before recipes: keeps its alert) |
| 6c | `emit_vendor_recipes` | `[vendor_recipes.*]`: per `any` condition: `recipe_floor` blocks (better crafting bases / `[overrides]`, own style, + recipe conds), then the recipe block (`bases`: `Rarity < Unique`; `conds`: + `rarity`), then for `bases` a `Rarity Unique` block minus bases whose ubases/fbases tier ranks better (tier = floor); `BASE_SHAPE` icon. Before leveling / price Hides so cheap ingredients still show |
| 7 | `emit_leveling` | NeverSink campaign rules + build module, all `AreaLevel <= area_level_max` |
| 8 | `emit_overrides` | `[overrides]` (wrapped by `campaign_unhide`) |
| 10 | `emit_stackables` | singles + stack-size lift blocks (wrapped by `campaign_unhide`) |
| 11 | `emit_uniques` | unique/foulborn/linked/maps + `emit_corrupted_uniques`; `variable_classes` Class block right after the top tier; content rescue (faded) block after Foulborn catch-all, before hidden normal tiers |
| 12 | `emit_crafting_bases` | ilvl/influence blocks |
| 13 | `emit_rares` | per `RARE_GROUPS` group (`rares.weapons/armour/jewellery` tier lists): NeverSink `$type->rr*` base-tier blocks from `league.filter`, uncommented, + `Class ==` group classes with `rares.show` true; style = `rares.text_color` only; `"all"` = one class block per group |
| 14 | `hand_rules("bottom")` | maps, gem Hide, hide gear, blue safety net |

6. Post-process whole text: `hidden_game_colours` (hidden blocks keep game rarity colour), `maximize_item_sizes`.
7. Return `r = {tiers, prices, divine, ubases, fbases, linked, cbases, ref_cards, ref_currency, card_volumes}`.

## Tiers

- Names (best -> worst): `top`, `high`, `mid`, `minor`, `variable`, `low`, `brown`, `dust`, `unknown`, `hide` (`variable` placed after config `variable_after`). `Tiers.order` / `Tiers.rank()` give this order (lower = better). Jackpot / never-hide code must not rely on variable's rank (foulborn `min_tier`, crafting-base block order special-case it).
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
  Disabled-module uniques (`content_policy` `excluded_names`) also don't set a base's cheapest.
  Enabled-module uniques: priced normally; `valuable_content_bases` (`content_policy` `rescue` bases
  whose best content unique is in a `shown_unique_tiers` tier) -> `emit_uniques` shows those whose
  price tier is hidden in `[style.content]`.
- Then `always_show_bases`, then `[unique_overrides]` applied last.

## Icon shapes (`SHAPE`)

Star = uniques + tink, Square = unique maps, Circle = currency/cards, Hexagon = fragments/scarabs, Diamond = bases/unknown (`BASE_SHAPE`), Moon = league stackables. Shape in config styles is replaced by code.

## Function index (grep `def name`)

- Fetch: `fetch_json`, `detect_league`, `fetch_all`, `fetch_wiki_uniques`, `non_map_drops`, `wiki_unique_bases`, `content_bases`, `content_policy`, `no_map_drop`
- Price: `Tiers`, `exchange_divine`, `apply_divine_tiers`, `price_stackables`, `card_trade_volumes`, `jackpot_chaos`, `never_hide_floor`, `small_loot`, `min_shown_rank`, `shown_unique_tiers`, `unique_drop_weights`, `price_unique_bases`, `price_foulborn_bases`, `price_linked_jackpots`, `price_crafting_bases`, `reference_card_tiers`, `reference_currency_tiers`
- Emit helpers: `q(names)` quoted sorted list, `block(action, conds, style, comment)`, `hidden`, `style_for`, `action_for`, `section`
- Emit: see table above (incl. `emit_rares`); leveling helpers `league_start_unused_whites`, `build_magic_weapons`, `campaign_unhide`, `rarities_of`, `hidden_game_colours`, `maximize_item_sizes`, `campaign_only`, `campaign_icon_sound`
- Main: `load_cfg`, `split_tiers` (config fractions -> `tiers_divine`, `tiers` at `FALLBACK_DIVINE`), `apply_league_start`, `hand_rules`, `build_text`, `main`
- Constants at top: `FALLBACK_DIVINE`, `TOGGLE_OFF`, `EXCHANGE_TYPES`, `STASH_STACKABLE_TYPES`, `UNIQUE_TYPES`, `CURRENCY_CLASSES`, `GEAR_CLASSES`, `RARE_GROUPS`, `HIDDEN_STYLE`, `SHAPE`, `PINNED_TOP_STACKABLES`; mid-file: `LEVELING_SECTIONS`, `VENDOR_CLASSES`, `NORMAL_HIDE_CLASSES`, `WEAPON_CLASSES`

## filtersim.py

- `parse(text) -> [Block(action, comment, line_no, conds, style, cont)]`
- `evaluate(blocks, item) -> (deciding_block|None, style_lines)`; `visible(blocks, item)`.
- Item dict keys: `rarity, basetype, class, influence[], mods[], socket_group` + `NUMERIC` values (`stack, ilvl, quality, links, corrupted_mods, sockets, drop_level, width, height, area_level` (default 83), `armour, evasion, es`) + `BOOL` values (`corrupted, mirrored, identified, foulborn`). PoE2: `gem_level, waystone_tier, unid_tier` + bools `enchanted, twice_corrupted, vaal_unique, vaal_unique_mod, always_show`. Missing = 0/False.
- Modelled conditions: Class, BaseType, Rarity, numeric (`NUMERIC`), bool (`BOOL`), SocketGroup, HasExplicitMod (incl. `>=N` count form), HasInfluence. Anything else -> `NotImplementedError`.

## report.py

`write(cfg, data, text, r, league, path)`: meta incl. `tier_strip()` (tier chaos + div fraction + hidden/quiet + `look()` of the tier's `[style.*]` lines (quiet merged), header chips styled like in-game) and `unique_tier_strip()` (`[uniques] show` toggles + small_loot floor -> "Unique tiers" Shown / Hidden vertical lists in `#utiers`); `collect()` replays every priced item through filtersim -> rows; `content_modules()` per `[content.*]` module: its bases dropped as unID uniques through filtersim + content uniques' prices (payload `content`, rendered in `#cm` as one collapsed `<details>` per module, above "Hidden, worth a look"); `vendor_recipes()` per `[vendor_recipes.*]` (off ones still list) drops each base x `any` condition x rarity (normal .. unID unique; `conds` recipes: `recipe_sample()` item from the conditions on a `RECIPE_BASE` example base, per `rarity`) through the built filter (payload `vendor`, rendered in `#vr` one `<details>` per recipe, below content modules); `browser_rules()` serializes blocks for the in-browser "Check an item" tool; injects JSON into `PAGE` (`__DATA__`, `__LEAGUE__`). Edit HTML/JS inside `PAGE`. `icon(name)` inlines `assets/<name>.png` as a data URI into `__CHAOS__` / `__DIVINE__` (JS `CI` / `DI` img snippets used instead of "c" / "div").

## PoE2 (`build_filter_poe2.py`)

Self-contained, no shared import with PoE1. `load_cfg` (config_poe2.toml) -> `detect_league` -> `fetch_all` (exchange feeds in `[exchange].types`, cache `cache/poe2/<league>/ex_<T>.json`) -> `build_text(cfg, data, league, reference_text)` (pure) -> write + copy.

- Unit = divine. `divine_per_primary(core)` (1 if primary is divine, else `rates.divine`); `price_exchange` -> `{name: (div, feed, volume_div)}` (max over feeds). `fmt` prints div / chaos / ex for the header; `per_divine` = chaos or ex per div.
- `Tiers(cfg)`: `[tiers]` are plain div fractions, sorted high -> low; `of`, `hidden`, `style` (quiet swap, top = Star), `action`.
- `reliable(cfg, value, volume)`: `volume >= min_volume` and (`volume/value >= min_units` or `volume >= trusted_volume`). Unreliable -> left to NeverSink if `reference_basetypes` names it (`r["deferred"]`), else blue `unknown` (never hidden, no tink).
- `item_key(name, feed)`: `LEVELED_FEEDS` (UncutGems) "X (Level N)" -> `BaseType == X` + `GemLevel == N`; other feeds' level names are literal BaseTypes.
- Constants: `PINNED_TOP` (Divine, Mirror, Hinekora's Lock), `SHAPES` per feed, `NO_STACK` feeds, `STYLES`, `QUIET_STYLE`, `HIDDEN_STYLE`.

Block order: header (rates, tier values) -> pinned top -> per tier top..dust: stack-size blocks (`StackSize >= n`, skipped for hidden targets and `NO_STACK`) then singles -> blue unknown -> `Hide` below lowest tier -> `reference_body(reference)`: NeverSink from the first section holding a block, `SetBorderColor`/`SetBackgroundColor` stripped except in white-background (tink) blocks. NeverSink handles gear, rares, uniques, waystones, gold, leveling, unpriced/thin items and its pink catch-all.

`GOLD_HIDE` block before NeverSink unless `show_gold`. Whole text through `maximize_item_sizes` (Show/Minimal -> font 45).

`r = {prices, tiers, deferred}`. `main` then `report_poe2.write` -> `out/report_poe2.html` (`collect`: every priced item replayed through filtersim, `FEED_CLASS` guesses item class; header chips: div:ex, div:chaos, tier values in ex).
