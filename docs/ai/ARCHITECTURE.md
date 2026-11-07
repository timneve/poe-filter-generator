# Architecture (PoE1 `build_filter.py` unless noted)

## Pipeline

```
main()
  load_cfg()            config.toml -> split_tiers -> + unique_tiers.toml, modules.toml, fallback_tiers.toml -> apply_league_start (league_start_values written into cfg; build_text does it on a copy when a test sets the flag)
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
| `stash[T]` | `{lines:[{name,baseType,chaosValue,listingCount,count,variant,links,levelRequired,itemType}]}` (gems also `gemLevel,gemQuality,corrupted,metadata.gemKind`) | poe.ninja stash, T in `STASH_TYPES` = `STASH_STACKABLE_TYPES + UNIQUE_TYPES + BASE_TYPES + CHECK_TYPES` |
| `nomap` | `{unique name: reason}` | wiki: can't drop in normal map (boss/encounter/recipe) |
| `wiki_bases` | `{base: {unique names}}` | wiki drop-enabled uniques per base |
| `content` | `{module: {base: {names}}}` | wiki restricted uniques matching `[content.X].sources` |
| `drop_anywhere` | `{names}` | wiki enabled + not restricted |

Cache files: `cache/<league>/ex_<T>.json`, `st_<T>.json`, `cache/wiki_uniques.json`, `cache/index-state.json`, `cache/ninja_categories.json` (`ninja_categories`: poe.ninja sidebar types; `main` -> `check_ninja_categories` warns on any not in `NINJA_TYPES`). PoE2: `cache/poe2/...`.

## `build_text` steps

1. `exchange_divine(data)` -> `apply_divine_tiers` rewrites `cfg["tiers"]` (chaos) = `tiers_divine` fraction x divine, no floor -> `Tiers(cfg)`.
2. `price_stackables` -> `prices {name: (chaos, type)}`, `divine` chaos value.
3. Ancient Wombgift floored to `minor`.
4. Pricing:
   - `price_unique_bases` -> `{base: (tier, cheapest, best, best_name, ev_or_None)}`
   - `price_foulborn_bases` -> `{base: (tier, cheapest, best, label)}`
   - `price_linked_jackpots` -> `{links: {bases}}` (5L/6L unique >= jackpot)
   - `price_crafting_bases` -> `[(tier, ilvl_min, ilvl_max|None, influence|None, base, chaos)]` (feeds `BASE_TYPES`: BaseType + Flask)
   - `price_clusters` -> `{(tier, base, passives, ilvl_lo, ilvl_hi|None, node|None): chaos}` (ClusterJewel, `CLUSTER_ILVL` buckets, `CLUSTER_NODES` enchant -> node; unknown enchant -> variable, no node cond)
   - `price_gems` -> `{(tier, level, quality, corrupted): {names}}` (SkillGem/ImbuedGem, every poe.ninja variant, price capped by `gem_caps` (cheapest confident strictly better variant: same corrupted, level >=, quality >=); thin listings -> variable whatever the price unless capped into a hidden tier; `alt_gem` lines skipped; confident below `[gems] min_tier` / `small_loot` / hidden tier dropped, or tier "hide" if `gem_special` (level / quality 21+))
   - `fallback_tiers(cfg, "cards" / "currency")` (currency, corpses, vials) -> fallback tiers from `fallback_tiers.toml` (made by `tools/import_fallback_tiers.py`; the build does not read `reference/` for them)
5. Emit, concatenated in this order (first non-`Continue` match wins in game):

| # | Emitter | Content |
|---|---|---|
| 1 | header | league, divine, tiers |
| 2 | `emit_visibility_toggles` | `hide_forbidden_tome`, `show_contracts` (Hide blocks) |
| 3 | `emit_content_overrides` | `[content.X.drops]` true/false |
| 4 | `emit_defaults` | `Continue` blocks: font 45, no border, gear text colour |
| 5 | `emit_pinned_stackables` | Divine/Mirror/Hinekora tink (`PINNED_TOP_STACKABLES`), then `always_top_classes` (`Class ==`, e.g. Vault Keys = Reliquary keys) top style: beats prices / `[overrides]` / modules (module `maps` relickeys* = string keys -> `module_elsewhere`) |
| 5b | `emit_gems` | `price_gems` Show blocks (tier, then most specific variant: `Corrupted`, `GemLevel >=`, `Quality >=`), then blue `TransfiguredGem True`. Before top's 20% / Awakened Shows and the gemcutter recipe floor |
| 5c | `emit_gold` | `show_gold` false: one gold Hide. true: module `misc` `GOLD_SECTION` [[0200]] keys all config-driven (`driven`): `gold.stack3` style for `StackSize >= gold_min_stack`, `gold.anyother` = one Hide `AreaLevel >= GOLD_MAP_AREA_LEVEL` (none in LS / `gold_min_stack <= 1`), other tier keys nothing; then small gold Show (`GOLD_SMALL_STYLE`, campaign). Not tied to `[misc] enabled` |
| 6 | `hand_rules("top")` | `rules/top.filter` (+ `# BEGIN/END show_5_links/show_6_links/show_mirrored` sections toggled; quest items / Pantheon souls; Awakened + 20% gem Shows) |
| 6b2 | `emit_flasks` | `[flasks]`: `module_blocks` of module `flasks` ([0803] ID mods, [1303] fractured, [[2500]] quality/ilvl incl. [2501]-[2505]), `Class` narrowed to `FLASK_CLASSES`. LS: every Show on. Before recipes: 21% white flask beats glassblower |
| 6b3 | `emit_id_mods` | `[id_mods]`: `module_blocks` of module `id_mods` (`modules.toml` per-block toggles; [[0600]] combos + [0617] veiled, [[0700]] dual, [0801]-[0802] single, [[1000]] corrupted; minus `FLASK_CLASSES`), league.filter's own style. LS: + commented-out blocks |
| 6b3a | `emit_perfection` | module `gear_special` `PERFECTION_SECTION` [0901] (quality / perfection top bases), every block + `Rarity <= Rare`; `OVERQUALITY_TOGGLES` (other quality blocks: perfection, flasks, unique 21%; `module_blocks` maps the modules.toml string to `[overquality] <name>`); `OVERQUALITY_KEYS` (modules.toml value `"config.toml [overquality]"`) via `driven=overquality_driven`: `[overquality] quality_30/27/21` (30%: `style_for` top tier = tink incl. border/bg, emitted first in [0901] so the ilvl 83+ perfection blocks cannot catch a 30% item; LS ignores them). `[gear_special]` off: only the overquality blocks. After id_mods, before exotics / recipes (30% RGB keeps its alert) |
| 6b4 | `emit_exotics` | `[exotics]`: `module_blocks` of module `exotics` ([0902] memory strands, [[1100]] exotic mods, [[1200]] exotic classes + [1201] relics, [[1300]] corruptions / abyss sockets / fractured / enchanted / crucible; minus `FLASK_CLASSES`; `EXOTIC_NOT_UNIQUE` adds `Rarity <= Rare` to imbued / fishing-rod blocks), league.filter's own style. After id_mods (league.filter order), before recipes / stackables / uniques. LS: every Show on |
| 6b4a | `emit_priced_bases_first` | copy of the `cbases` crafting-base Shows (shown tiers up to `[leveling] unused_whites_min_tier` or else `[bases] min_tier`, + `variable`, no Hides) when `[gear_special]` or `[crafting]` is on: a priced base keeps its price tier over the gear_special / crafting Shows. After id_mods / flasks / perfection / exotics (their look wins: more info than base price), before recipes (same tier as `recipe_floor`) |
| 6b4b | `emit_gear_special` | `[gear_special]`: module `gear_special` `GEAR_SPECIAL_TOP_SECTIONS` ([0302] influenced rares, [[0400]] eldritch, [[0500]] exotic bases), league.filter's own style. `driven=module_elsewhere` (no block) for the [[0500]] FilterBlade conditional entries `s0500_1..5` (Stacked Deck = price, breach rings = `[vendor_recipes.grasping_mail]`, unique Opal Ring / Abyssal Axe = price). After exotics + priced bases (league.filter has it before [0600]; Shows only, style differs), before recipes. LS: every Show on |
| 6b5 | `emit_links` | `[crafting]`: module `crafting` `LINK_SECTION` [1401] 5-link Shows (all off). RGB / 6-socket keys = `"config.toml [vendor_recipes.chromatic/jeweller]"` -> `module_elsewhere` (no block: vendor recipes). After exotics, before recipes (league.filter [1400] before [1500]) |
| 6c | `emit_vendor_recipes` | `[vendor_recipes.*]`: per `any` condition x `sizes` set (`RECIPE_SIZES`; + `area_level` AreaLevel range): `recipe_floor` blocks (better crafting bases / `[overrides]`, own style, + recipe conds), then the recipe block (`bases`: `Rarity < Unique`; `conds`: + `rarity`), then for `bases` a `Rarity Unique` block minus bases whose ubases/fbases tier ranks better (tier = floor); `BASE_SHAPE` icon. Before leveling / price Hides so cheap ingredients still show |
| 6c2 | `emit_gem_fallback` | exact-variant Hides (`gem_variant_conds`) for `price_gems` "hide" keys, then blue `GemLevel >= 21` / `Quality >= 21` Shows (unpriced, probably valuable). Off when `variable` hidden. After recipes + top's 20% Show |
| 6d | `emit_cluster_prices` | `price_clusters` Show blocks (Rarity <= Rare, ilvl bucket, EnchantmentPassiveNum, BaseType, EnchantmentPassiveNode), tier style. Before leveling: beats build-module jewel Hides |
| 7 | `emit_leveling` | Campaign, all `AreaLevel <= area_level_max`: `[leveling]` extras (jewellery, gems, vendor fodder, magic hide), build module `rules/leveling/<build>.filter`, white hide, then `leveling_module_blocks` (module `leveling`: [2802] [[3800]] [[5000]]-[[5405]], + `Rarity <= Rare` on gear; strictness keys -> `leveling_strictness_block` / `leveling_strictness_action` from the block's `%D`/`%H`/`!utility_layer` tag; [[3800]] via `leveling_price_first` with `leveling_price_shown(cfg, tiers, prices)` passed by `build_text`). Reads no `reference/` |
| 8 | `emit_overrides` | `[overrides]` (wrapped by `campaign_unhide`) |
| 10 | `emit_stackables` | `[exchange.show_stacks]` Shows for unpriced names, then singles + stack-size lift blocks (`show_stacks` name whose price x stack is hidden: extra `show_stacks_tier` stack entry, emitted before the hidden tiers), fallbacks (wrapped by `campaign_unhide`) |
| 10b | `emit_special_maps` | `[maps] enabled`: `module_blocks` of module `maps` (league.filter's own style, `modules.toml [maps.blocks]`): `UNIQUE_MAP_SECTION` [3201] when `uniques.hide_maps`, `NIGHTMARE_MAP_SECTION` [3202] Valdo/Nightmare/Shaper guardian, `[maps] corrupted_min_tier` Hide (corrupted non-unique below tier), `SPECIAL_MAP_SECTIONS` ([0301] influenced, [3203]-[3204] blighted/Vaal Temple/8-mod/enchanted/implicit), then `MAP_ITEM_SECTION` ([[3400]] unique/enchanted contracts + blueprints, logbooks, charts, plain contract + Sanctum Research Hides; [[3500]] reliquary keys, Chronicle, Inscribed Ultimatum; `show_contracts` true / `hide_forbidden_tome` false turn the contract / sanctum Hides off via `MAP_ITEM_CONFIG_OVERRIDES`). Before uniques (league.filter order); after stackables (price / unpriced-fragment fallback wins). LS: every Show block on |
| 10c | `emit_misc(MISC_BEFORE_UNIQUES)` | `[misc] enabled`: module `misc` [4500] heist targets, [4600] enshrouded gear, [4700] idols (Shows; before uniques like league.filter: "override uniques") |
| 11 | `emit_uniques` | unique/foulborn/linked/maps + `emit_corrupted_uniques` + `emit_unique_exceptions` (module `unique_exceptions`, `[unique_exceptions] enabled`; after shown price tiers, before hidden ones); `variable_classes` Class block right after the top tier; normal content rescue (faded) after Foulborn catch-all, before hidden normal tiers |
| 11a | `emit_misc(MISC_AFTER_UNIQUES)` | module `misc` [4900] Maven's invitations, lab / incursion items (stackable prices / unpriced fragment fallback decide first) |
| 11b | `emit_map_progression` | module `maps` `MAP_PROGRESSION_SECTION` [3302] tier Hides + restex Show; `[maps] progression` "all"/"auto" first emits them as Shows via `module_blocks(unhide=)` ("auto": + `AreaLevel <= 67+tier`). After uniques (unique maps priced there) |
| 12 | `emit_crafting_bases` | ilvl/influence blocks |
| 13 | `emit_rares` | `rares.enabled`: `module_blocks` of module `rares`, `RARE_SECTIONS` ([[1700]] decorators (Continue) + talismans, [[1800]] veiled, [[1900]] breach rings, [[2000]] conditional hides, [[2100]] amulet/ring/belt tiers, [[2200]] droplevel hides, [2201] gear tiers), league.filter's own style except decorators: `restyle=rare_decorator_style` swaps NeverSink's yellow `SetTextColor` for `rares.text_color`. Keys matching `RARE_TIER_KEY` (`rr...tN`, modules.toml value `"config.toml [rares]"`) go to `driven=rare_tier_blocks`: per `RARE_GROUPS` group (`rares.base_tiers`, `rares.weapons/armour/jewellery` tier lists) the block + `Class ==` group classes with `rares.show` true, `ItemLevel >= rares.min_ilvl`; style = `rares.text_color` only; `"all"` = one class block per group at the first rr block; LS ignores them. After crafting bases (league.filter order) |
| 13-2 | `emit_endgame_crafting` | `[crafting]`: module `crafting` `ENDGAME_CRAFTING_SECTIONS` ([2301] early endgame crafting, [[2400]] chancing; LS: Shows on), then `NO_LS_CRAFTING_SECTIONS` ([2302] crafting matrix, not LS-unlocked: empty t1_83 tier = every ilvl 83+ base; [2601] RGB keys -> `module_elsewhere`, `[vendor_recipes.chromatic]`). Between 13 and 13a (league.filter order) |
| 13a | `emit_rare_hide_layer` | module `rares` `RARE_ANIMATED_SECTION` ([[2600]] animated-weapon Shows, off, LS forced off: would show every normal/magic weapon), then `RARE_HIDE_LAYER_SECTIONS` ([2602] rr.t5 + FilterBlade corrupted-unique entry, [[2700]] hide layer: normal/magic gear `AreaLevel >= 68`, rares ilvl 68+). `emit_endgame_crafting` ([[2300]]/[[2400]]/[2601]) goes right before it |
| 13b | `emit_jewels` | `[jewels] enabled`: `module_blocks` of module `jewels` (`modules.toml [jewels.blocks]`): `JEWEL_SECTIONS` ([2801] special, [2803] abyss, [2804] generic), `CLUSTER_SECTIONS` ([2805] eco = `CLUSTER_ECO_SECTION`, not LS-unlocked: off blocks are empty eco tiers; [2806] random). League.filter order: after rares |
| 13c | `emit_heist` | `[heist] enabled`: module `heist` ([[2900]] cloak / brooch / gear / tool base tiers). Right after jewels as in league.filter |
| 13d | `emit_unknown_gems` | gem feed present: Hide gems poe.ninja lists (no shown price; not with `[gems] show_all`), then blue Show for every other gem (not on poe.ninja, e.g. new exceptional supports). Last gem rule |
| 14 | `hand_rules("bottom")` | gem Hide, hide gear, corpse-class hide (unpriced corpses: blue `CURRENCY_CLASSES` fallback first), blue safety net |

6. Post-process whole text: `apply_palette` (every `Set*Color`: `[colors]` name -> value, numbers e.g. NeverSink copies -> nearest palette colour, text by RGB never from `NON_TEXT_COLORS`, border/bg by RGBA, alpha 0 -> an alpha-0 entry (`clear`); `COLOR_LINE`), `hidden_game_colours` (hidden blocks keep game rarity colour), `maximize_item_sizes`.
7. Return `r = {tiers, prices, divine, ubases, unique_ev, fbases, linked, cbases, ref_cards, ref_currency, card_volumes, clusters, gems}`.

## Tiers

- Names (best -> worst): `top`, `high`, `mid`, `minor`, `variable`, `low`, `brown`, `dust`, `unknown`, `hide` (`variable` placed after config `variable_after`). `Tiers.order` / `Tiers.rank()` give this order (lower = better). Jackpot / never-hide code must not rely on variable's rank (foulborn `min_tier`, crafting-base block order special-case it).
- `Tiers.of(chaos)` -> highest tier with threshold <= chaos, else `"hide"`.
- `hidden(cfg,tier)`: `"hide"` or in `hide_tiers`. `style_for` uses `[style.<tier>].lines`; `quiet_tiers` swap to `[style.quiet]` keeping font size; top tier forces Star icon.
- `variable` / `unknown` = blue: value unknown or varies inside the group.
- `jackpot_chaos(cfg, divine)` = `jackpot_divine * divine`.

## Unique pricing rules (`price_unique_bases`)

- Base tier (non-EV) = CHEAPEST confident (`listingCount >= min_listings`) unique on base (`base_price = "highest"`: priciest); per unique its cheapest variant. Jackpot / never_hide rescue unchanged.
- `best` = best variant of any listing. Base would hide but best >= jackpot -> `variable` (or >= `never_hide_tier` when `variable_jackpot_only=false`).
- `[uniques.ev]` on: tier by expected value of one unID drop, weights from `unique_tiers.toml` x `tier_weights`.
- `unknown_as_variable`: any wiki unique on base lacking a confident price -> `variable`.
- `vendor` (`unique_vendor_values`, `[vendor_recipes.*]` with `uniques`): each variant price floored at the vendor value (cheapest, best, EV); unlisted / thin = confident at that value, never unknown. Restricted (`nomap`) still skipped.
- `nomap` uniques skipped (boss-only can't make junk base blue) unless their content module enabled. `non_map_drops`: every `Replica ` name = Heist only, even without the wiki restricted flag.
  Disabled-module uniques (`content_policy` `excluded_names`) also don't set a base's cheapest.
  Enabled-module uniques: priced normally; `valuable_content_bases` (`content_policy` `rescue` bases
  whose best content unique is in a `shown_unique_tiers` tier) -> `emit_uniques` shows those whose
  price tier is hidden in `[style.content]`. Normal uniques only: no Foulborn rescue (Foulborn
  come from Wombgifts, never content drops).
- Then `always_show_bases`, then `[unique_overrides]` applied last.

## Icon shapes (`SHAPE`)

Star = uniques + tink, Square = unique maps, Circle = currency/cards, Hexagon = fragments/scarabs, Kite = splinters (`SPLINTER_SHAPE`, by name via `shape_of`), Pentagon = cluster jewels (`CLUSTER_SHAPE`, `emit_cluster_prices`; module eco tiers same), Diamond = bases/unknown (`BASE_SHAPE`), Moon = league stackables. Shape in config styles is replaced by code.

## Function index (grep `def name`)

- Fetch: `fetch_json`, `detect_league`, `fetch_all`, `ninja_categories`, `check_ninja_categories`, `fetch_wiki_uniques`, `non_map_drops`, `wiki_unique_bases`, `content_bases`, `content_policy`, `no_map_drop`
- Price: `Tiers`, `exchange_divine`, `apply_divine_tiers`, `price_stackables`, `card_trade_volumes`, `jackpot_chaos`, `never_hide_floor`, `small_loot`, `min_shown_rank`, `shown_unique_tiers`, `unique_drop_weights`, `unique_vendor_values`, `price_unique_bases`, `price_foulborn_bases`, `price_linked_jackpots`, `price_crafting_bases`, `price_clusters`, `module_cluster_nodes`, `alt_gem`, `price_gems`, `gem_caps`, `gem_special`, `gem_variant_conds`, `fallback_tiers`, `fallback_groups`
- Emit helpers: `q(names)` quoted sorted list, `block(action, conds, style, comment)`, `hidden`, `style_for`, `action_for`, `section`
- Emit: see table above (incl. `emit_special_maps`, `emit_map_progression`, `emit_rares`, `emit_rare_hide_layer`, `rare_tier_blocks`, `rare_decorator_style`, `emit_cluster_prices`, `emit_jewels`, `emit_heist`, `emit_gold`, `emit_misc`, `emit_flasks`, `emit_exotics`, `emit_id_mods`, `emit_priced_bases_first`, `emit_gear_special`, `emit_perfection` (`overquality_driven`), `emit_links`, `emit_endgame_crafting`, `module_elsewhere` (driven for keys decided by price / a vendor recipe: no block), `emit_gems`, `emit_gem_fallback`, `emit_unknown_gems`, `emit_unique_exceptions`, `fallback_stacks` (stack Shows for unpriced items in a hidden fallback tier, inside `emit_stackables`); `module_blocks` = our `rules/modules` blocks with `modules.toml` toggles (docs/ai/MODULES.md; `extra_conds` = per-key extra condition lines; `driven(block)` = emitter for keys whose toggle is a string, else ValueError; `restyle(key, style)` = per-block style change); `_transform_block` = one module block -> text (`classes` / `drop_classes` / `only` / `unhide`). NeverSink export parsing (`parse_ref_blocks`, `section_heads`) lives in `tools/import_neversink.py`: the build never reads `reference/` (test `NoReference`); leveling helpers `leveling_module_blocks`, `leveling_strictness_block`, `leveling_strictness_action`, `leveling_price_shown`, `leveling_price_first`, `unused_white_hides`, `build_magic_weapons`, `campaign_unhide`, `rarities_of`, `hidden_game_colours`, `maximize_item_sizes`, `campaign_only`, `campaign_icon_sound`
- Main: `load_cfg`, `split_tiers` (config fractions -> `tiers_divine`, `tiers` at `FALLBACK_DIVINE`), `apply_league_start` (writes `league_start_values` into cfg + `cfg["modules"]` once, `_league_start_applied`), `league_start_values(conf, modules)` -> (config changes, modules changes) as {key path: value} = THE league-start table (also `tools/league_start.py`), `set_path`, `_has`, `hand_rules` (`Hide # gems.show_all` -> Show with `[gems] show_all`), `build_text`, `main`. No emitter reads `league_start` (only the header line)
- Constants at top: `FALLBACK_DIVINE`, `TOGGLE_OFF`, `EXCHANGE_TYPES`, `STASH_STACKABLE_TYPES`, `UNIQUE_TYPES`, `BASE_TYPES`, `CHECK_TYPES` (fetched, only tested), `SKIPPED_TYPES` (not fetched, reason), `NINJA_TYPES` (all), `STASH_TYPES`, `CURRENCY_CLASSES`, `GEAR_CLASSES`, `RARE_GROUPS`, `HIDDEN_STYLE`, `SHAPE`, `SPLINTER_SHAPE`, `CLUSTER_SHAPE`, `PINNED_TOP_STACKABLES`; mid-file: `RARE_SECTIONS`, `RARE_ANIMATED_SECTION`, `RARE_HIDE_LAYER_SECTIONS`, `RARE_TIER_KEY`, `LS_KEEP_SECTIONS` (module -> sections whose off Shows league start leaves off), `LS_KEEP_HIDES` (on Hides it leaves on), `LS_ENABLE_TABLES` (config tables whose `enabled` it sets), `NO_LS_CRAFTING_SECTIONS`, `JEWEL_SECTIONS`, `CLUSTER_SECTIONS`, `CLUSTER_ECO_SECTION`, `EXOTIC_NOT_UNIQUE`, `SPECIAL_MAP_SECTIONS`, `UNIQUE_MAP_SECTION`, `MAP_PROGRESSION_SECTION`, `MAP_ITEM_SECTION`, `MAP_ITEM_CONFIG_OVERRIDES` (config toggles beating module Hides), `GOLD_SECTION`, `MISC_BEFORE_UNIQUES`, `MISC_AFTER_UNIQUES`, `GOLD_MAP_AREA_LEVEL`, `GOLD_SMALL_STYLE`, `FLASK_CLASSES`, `CLUSTER_ILVL`, `CLUSTER_NODES`, `LEVELING_SECTIONS`, `VENDOR_CLASSES`, `NORMAL_HIDE_CLASSES`, `WEAPON_CLASSES`

## filtersim.py

- `parse(text) -> [Block(action, comment, line_no, conds, style, cont)]`
- `evaluate(blocks, item) -> (deciding_block|None, style_lines)`; `visible(blocks, item)`.
- Item dict keys: `rarity, basetype, class, influence[], mods[], socket_group` + `NUMERIC` values (`stack, ilvl, quality, links, corrupted_mods, sockets, drop_level, width, height, area_level` (default 83), `armour, evasion, es, cluster_passives, memory_strands, map_tier`) + `BOOL` values (`corrupted, mirrored, identified, foulborn, transfigured, fractured, blighted, uber_blighted, zana_memory, implicit, imbued, synthesised, crucible, vestigial, replica`) + `TEXT` names (`class, basetype, cluster_node`). PoE2: `gem_level, waystone_tier, unid_tier` + bools `enchanted, twice_corrupted, vaal_unique, vaal_unique_mod, always_show`. Missing = 0/False.
- Modelled conditions: Class, BaseType, EnchantmentPassiveNode (`TEXT`), Rarity, numeric (`NUMERIC`), bool (`BOOL`), SocketGroup, HasExplicitMod (incl. `>=N` count form), HasInfluence. Anything else -> `NotImplementedError`.
- Covers every condition of `reference/league.filter` too (`Replica` -> `replica`; `tests/test_parity.py` evaluates it).

## report.py

`write(cfg, data, text, r, league, path)`: meta incl. `tier_strip()` (tier chaos + div fraction + hidden/quiet + `look()` of the tier's `[style.*]` lines (quiet merged), header chips styled like in-game) and `unique_tier_strip()` (`[uniques] show` toggles + small_loot floor -> "Unique tiers" Shown / Hidden vertical lists in `#utiers`); `collect()` replays every priced item through filtersim -> rows; `unique_ev()` per `[uniques.ev]` base: EV, tier, cheapest, unID drop through filtersim + per unique drop share / avg price / drop tier from `r["unique_ev"]` (filled by `price_unique_bases(..., ev_detail)`; payload `uev`, rendered in `#ub` inside collapsed `#uevd` with search, above content modules); `content_modules()` per `[content.*]` module: its bases dropped as unID uniques through filtersim + content uniques' prices (payload `content`, rendered in `#cm` as one collapsed `<details>` per module, above "Hidden, worth a look"); `vendor_recipes()` per `[vendor_recipes.*]` (off ones still list) drops each base x `any` condition x rarity (normal .. unID unique; `conds` recipes: `recipe_sample()` item from the conditions on a `RECIPE_BASE` example base, per `rarity`; `uniques` recipes: `unique_vendor_recipe(key, rec, blocks, data)`, one unID unique per base they roll on) through the built filter (payload `vendor`, rendered in `#vr` one `<details>` per recipe, below content modules); `browser_rules()` serializes blocks for the in-browser "Check an item" tool (EnchantmentPassiveNode -> uncertain: pasted enchant text isn't the node name); injects JSON into `PAGE` (`__DATA__`, `__LEAGUE__`). Edit HTML/JS inside `PAGE`. `icon(name)` inlines `assets/<name>.png` as a data URI into `__CHAOS__` / `__DIVINE__` (JS `CI` / `DI` img snippets used instead of "c" / "div").

## PoE2 (`build_filter_poe2.py`)

Self-contained except `build_filter.apply_palette` (shared colours). `load_cfg` (config_poe2.toml + `config.toml` `colors` unless it has its own) -> `detect_league` -> `fetch_all` (exchange feeds in `[exchange].types`, cache `cache/poe2/<league>/ex_<T>.json`) -> `build_text(cfg, data, league, reference_text)` (pure) -> write + copy.

- Unit = divine. `divine_per_primary(core)` (1 if primary is divine, else `rates.divine`); `price_exchange` -> `{name: (div, feed, volume_div)}` (max over feeds). `fmt` prints div / chaos / ex for the header; `per_divine` = chaos or ex per div.
- `Tiers(cfg)`: `[tiers]` are plain div fractions, sorted high -> low; `of`, `hidden`, `style` (quiet swap, top = Star), `action`.
- `reliable(cfg, value, volume)`: `volume >= min_volume` and (`volume/value >= min_units` or `volume >= trusted_volume`). Unreliable -> left to NeverSink if `reference_basetypes` names it (`r["deferred"]`), else blue `unknown` (never hidden, no tink).
- `item_key(name, feed)`: `LEVELED_FEEDS` (UncutGems) "X (Level N)" -> `BaseType == X` + `GemLevel == N`; other feeds' level names are literal BaseTypes.
- Constants: `PINNED_TOP` (Divine, Mirror, Hinekora's Lock), `SHAPES` per feed, `NO_STACK` feeds, `STYLES`, `QUIET_STYLE`, `HIDDEN_STYLE`.

Block order: header (rates, tier values) -> pinned top -> per tier top..dust: stack-size blocks (`StackSize >= n`, skipped for hidden targets and `NO_STACK`) then singles -> blue unknown -> `Hide` below lowest tier -> `reference_body(reference)`: NeverSink from the first section holding a block, `SetBorderColor`/`SetBackgroundColor` stripped except in white-background (tink) blocks. NeverSink handles gear, rares, uniques, waystones, gold, leveling, unpriced/thin items and its pink catch-all.

`GOLD_HIDE` block before NeverSink unless `show_gold`. Whole text through `maximize_item_sizes` (Show/Minimal -> font 45).

`STYLES` / `QUIET_STYLE` use `[colors]` names; `build_text` ends with `apply_palette` (NeverSink export snapped too). `r = {prices, tiers, deferred}`. `main` then `report_poe2.write` -> `out/report_poe2.html` (`collect`: every priced item replayed through filtersim, `FEED_CLASS` guesses item class; header chips: div:ex, div:chaos, tier values in ex).
