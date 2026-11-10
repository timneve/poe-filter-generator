# Recipes + gotchas

## Common changes

| Want | Do |
|---|---|
| Force an item's tier | `[overrides]` in config (stackable/any BaseType) or `[unique_overrides]` (unique base) |
| Change tier thresholds | `tiers.*` in config; everything refers to tiers by name |
| Change look of a tier | `[style.<tier>]` lines. Keep: no border/bg except `top`; icon shape is set by code |
| New hand rule | `rules/top.filter` (before prices) or `rules/bottom.filter` (after). Should it show at league start: give it a config key (e.g. `Hide # gems.show_all` + `[gems] show_all`, `hand_rules`) and set that key in `league_start_values` |
| New toggle section in top rules | wrap in `# BEGIN key` / `# END key`, handle in `hand_rules` (expects exactly one section) |
| New config key | add commented default in `config.toml`, read with `cfg.get(...)` default, add to `league_start_values` if LS should change it (flag + `tools/league_start.py` both use it), document in `README.md` + `docs/ai/CONFIG.md` |
| New price source / poe.ninja type | build warns / `LiveCache.test_every_ninja_category_handled` fails on a new poe.ninja category. Put it in exactly one of `EXCHANGE_TYPES` / `STASH_STACKABLE_TYPES` / `UNIQUE_TYPES` / `BASE_TYPES` (priced) / `CHECK_TYPES` (only tested: add a drop model to `LiveCache.ninja_drop`) / `SKIPPED_TYPES` (reason); `SHAPE` entry for stackables; `empty_data()` / `load_cache` pick it up automatically |
| Category removed by a patch (Scarab, 2026-11-13 patch) | build keeps working: `fetch_feed` turns the 4xx feed into `{}` + warning; `check_ninja_categories` warns "no longer on poe.ninja". Cleanup when confirmed gone: drop from `*_TYPES` + `SHAPE` (+ `report.STACK_CLASS`), `[exchange.card_rewards]` pointing at its items (card falls back to NeverSink tier), synthetic tests using it (`add_exchange(..., "Scarab", ...)`), docs mentioning it; refresh `reference/` + `tools/import_fallback_tiers.py`. Delete stale `cache/<league>/ex_<T>.json` |
| New cluster enchant | `test_valuable_ninja_items_visible` fails: add poe.ninja text -> in-game node name to `CLUSTER_NODES` (name = RePoE `cluster_jewels.json` "name"; valuable ones must be in NeverSink's reference or the test's `VERIFIED_CLUSTER_NODES`) |
| New emitted section | write `emit_x(cfg, ...)` returning `section(...) + block(...)...`, insert in `build_text` list at the right priority |
| New filter condition | add to `filtersim._match` (+ `NUMERIC`/`BOOL` map) first |
| Campaign build module | copy `rules/leveling/rf.filter` or `minion.filter`, edit, set `[leveling] build`. A `Show` with `Class ==` + `Rarity <= Rare`/`Magic` keeps those weapon classes past `hide_magic_after` (`build_magic_weapons`) |
| Add vendor recipe | Check ingredients on poewiki via the API (`api.php?action=parse&page=Vendor recipe&prop=wikitext` with `UA`; the HTML pages are bot-blocked). `[vendor_recipes.<name>]` table in `config.toml` (`enabled`, `tier`, `class`, `bases` or `conds` + `rarity`, optional `any`, `note`); never hand-write recipe blocks in `rules/*.filter` (no floor there). Conditions in `conds` / `any` must be in `filtersim._match`; `report.recipe_sample` must know how to fake them (add a `RECIPE_BASE` example for new classes); `emit_vendor_recipes` + report pick it up automatically. Recipe that turns a unique into a stackable (Harbinger -> Fracturing Shard): `uniques` + `reward` + `reward_count` instead (value floor, no blocks) |
| Report UI | edit `PAGE` string in `report.py` (PoE2: `report_poe2.py`); data rows from `collect()` |
| PoE2 change | `build_filter_poe2.py` / `config_poe2.toml` only; no shared code with PoE1 (except `filtersim`, `apply_palette` + `config.toml` `colors`) |
| PoE2 new poe.ninja feed | add to `[exchange].types` + `SHAPES` (+ `NO_STACK` if it never stacks, `LEVELED_FEEDS` if "(Level N)" means GemLevel) |
| PoE2 gear/uniques/waystones look | our modules `rules/modules_poe2/` (edit freely) + toggles `modules_poe2.toml`. Refresh from a new FilterBlade export: save it as `reference/league-filterblade-poe2.filter`, rerun the per-module `python tools/import_neversink.py --game poe2 --stock reference/regular-neversink-poe2.filter <module> <ranges>` (ranges = `[modules]` comments in `config_poe2.toml`; last = `3300:end`; keeps toggle values, overwrites the .filter); new conditions -> `filtersim` (`Poe2LiveCache.test_filter_fully_modelled`) |

## Writing tests (`tests/test_filter.py`)

```python
class Synthetic(unittest.TestCase):    # setUp: cfg copy, fixed chaos tiers, EV off, empty data (divine=400c)
    def test_x(self):
        add_exchange(self.data, "Currency", "Orb X", 30)          # exchange item at 30c
        add_unique(self.data, "Heavy Belt", "Some Unique", 200)   # stash unique line
        blocks, r = self.build()                                  # -> fs.parse(build_text(...)), r
        self.assertTrue(fs.visible(blocks, unid_unique("Heavy Belt", "Belts")))
```
- Helpers: `empty_data`, `add_exchange`, `add_unique`, `add_foulborn`, `unid_unique`. Item dicts for stackables: `{"basetype":..., "class":..., "stack": n}`.
- Assert visibility through `fs.visible` / `fs.evaluate`, not just `r[...]` tiers.
- Tink check: `not_tink(blocks, cfg, [(label, item)])` -> items whose deciding block lacks the top tier's background + alert sound (`tink_lines`). Guards: `Synthetic.test_very_expensive_items_tink` (one top-priced item per kind + always-tink items), `LiveCache.test_top_priced_items_tink` (every top-priced stackable / crafting base / cluster). New tink-worthy kind -> add it there.
- Synthetic `setUp` disables `tiers_follow_divine`, `uniques.ev`, `variable_jackpot_only`, `always_show_bases`, content drops; re-enable in the test if needed (`ev_setup()` for EV).
- `LiveCache` uses real `cache/`; skips some checks when `variable_jackpot_only` is on.
- Wrong style, not just wrong visibility: `LiveCache.test_unique_price_blocks_match_own_kind` checks every unique / Foulborn base (unID) is decided by a price block of its own kind and tier (block comment `<kind> <tier>`). New per-kind price blocks sharing a base -> give each kind an exclusive condition (`Foulborn True/False`) and extend this test.

## Gotchas

- Vendor recipe `conds` must still match something no earlier block takes: `[vendor_recipes.gemcutter]` stays `Quality >= 1` (top.filter's 20% Show catches every 20% gem first; `Quality >= 20` = dead recipe, low-quality gems fall to bottom's gem Hide; `test_currency_recipes_toggle` fails).
- `apply_divine_tiers` mutates `cfg["tiers"]` in place. Tests use `copy.deepcopy(cfg)`; `Synthetic.setUp` sets `tiers_follow_divine = False` + `FIXED_TIERS` chaos so numbers stay stable.
- Block order = priority. First non-`Continue` match decides. Defaults are `Continue` blocks. Earlier module blocks with their own style can steal a tink item (e.g. [0901] perfection beat 30% overquality): visible is not enough, check tink.
- `hidden_game_colours` + `maximize_item_sizes` post-process the whole text; font size 45 everywhere except content always-show style (block comment must start `content override show:` to keep its small size).
- Divination card exchange quotes are NOT trusted (no buy/sell direction). Cards priced only via `[exchange.card_rewards]`, else NeverSink fallback (`fallback_tiers.toml`) when volume < `card_fallback_min_volume`, else `unknown`.
- New league currency / cards without a fallback tier: refresh the NeverSink exports in `reference/`, run `python tools/import_fallback_tiers.py` (rewrites `fallback_tiers.toml`), commit it. `test_fallback_tiers_file_matches_reference_import` fails while the file is stale. The build never reads `reference/` for fallbacks. Unique rewards skip 5/6-link lines (`links` field): a troll 5L Whispering Ice once tinked The Incantation.
- Shards/splinters priced from finished item, never own quotes; skipped if finished item unpriced.
- Low-volume prices may SHOW an item, never hide it (exchange volume, stash-stackable / gem listings; thin gems show blue).
- Unique base tier = cheapest unique (not best) by default; `base_price = "highest"` = priciest confident one (non-EV path only). Linked (5L/6L) lines excluded from unlinked pricing; handled by `price_linked_jackpots`.
- Boss-only uniques (`data["nomap"]`) excluded unless content module enabled (not for "cheapest" either: Lab-only Winds of Change must not hide Hateforge's base); Foulborn names stripped of `"Foulborn "` prefix for that check.
- PoE filters can't see unique names or drop source before ID: every unique rule is base-wide.
- `reference/*.filter` are huge; grep, don't read. Parsed by tag (`%D<n>`, `%H<n>`, `$tier->...`).
- `wiki_uniques.json` fetch failure -> old cache or no boss skipping (warning on stderr).
- Windows: read/write files with `encoding="utf-8"`.
- poe.ninja ClusterJewel `levelRequired` = ilvl bucket start (`CLUSTER_ILVL`), `variant` = "N passives", `name` = enchant text (not the filter's `EnchantmentPassiveNode` name: `CLUSTER_NODES`). NeverSink's node names (now `module_cluster_nodes`, from rules/modules/jewels.filter) cover only some; names it skips go in `tests/test_filter.py` `VERIFIED_CLUSTER_NODES` only after checking RePoE `cluster_jewels.json` (poewiki HTML is bot-blocked). Never loosen the check: a wrong name never matches, valuable jewel stays unhighlighted.
- poe.ninja SkillGem lines are per level/quality/corrupt variant; only uncorrupted level 1 (q0 / q20) can drop. Alternate gems (transfigured "Cyclone of Tumult", `gemKind` "trarthus" "Heavy Strike of Trarthus"; trade type has a `discriminator`, see `alt_gem`): the name is NOT a BaseType (BaseType = plain gem) and the game rejects the whole filter, so `price_gems` skips them; blue `TransfiguredGem True` block instead. `gemKind` "exceptional" (Empower etc.) are normal BaseTypes. Worse variants often list at ~1 div (price-fix listings, enough volume to look confident): `gem_caps` caps them by the better variant.
- `ninja_categories` scrapes poe.ninja's site JS (sidebar config, `type:`...`url:`); cached `cache/ninja_categories.json` a day. Layout change -> warning only.
- Any poe.ninja value test: `LiveCache.test_valuable_ninja_items_visible` (>= `SAFETY_DIVINE`, >= `uniques.min_listings`), maps included (`map_drop` helper: tier from name, conqueror / Elder guardian prefix -> influence).
- Module blocks FilterBlade has off because they are EMPTY (cluster [2805] eco tiers without an `EnchantmentPassiveNode` list) match everything when turned on: keep them out of league_start (`LS_KEEP_SECTIONS`). Same for blocks too broad to auto-on (rares [[2600]] animated weapons = every normal / magic weapon).
- New league-start behaviour = a value in `league_start_values` (add a config key with its default if
  none exists), never an `if cfg.get("league_start")` in an emitter: the flag and `tools/league_start.py`
  (writes values into the files; `set_values` errors on a key missing from the file) must stay equal.
  `tests/test_league_start.py` checks start-written files == flag (whole filter text); its `load_cfg(root)`
  loads config.toml / modules.toml from a temp dir. Tests setting `cfg["league_start"] = True` need no
  `apply_league_start` before `build_text` (it applies to a copy); a direct emitter call does.
- Module blocks whose on/off config.toml already decides with richer options (rares `rr` base tiers: per group tier lists, per class, ilvl): import them with `--config-key REGEX=NOTE` (modules.toml value = string pointing to config.toml) and pass `module_blocks(driven=)`; never keep two toggles for one block. Blocks another system
  owns (vendor recipes, price: RGB, 6 sockets, FilterBlade "Conditional Entry" untagged `sNNNN_k`
  keys) the same way with `driven=module_elsewhere` (no block) and a NOTE naming the owner. Untagged
  keys number per section in file order: re-check them after a reference refresh.
- Strictness-tagged NeverSink blocks (leveling): the importer keeps `%D<n>` / `%H<n>` / `!utility_layer` after the key in the block header (`load_module` -> `tags`); import them `--config-key ...=config.toml [leveling] strictness` and decide in a `driven` from the tag (`leveling_strictness_block`). FilterBlade exports leveling as Hide / `#Show` (leveling off): never take the export's action as-is for them.
- New item section: grep BOTH reference filters first; league.filter decides shown / hidden + style, its `#Show` / Hide rules = league-start toggles (`off=`, `unhide=`). Never hand-write a blanket class Hide.

## Patch prep: PoE1 item tiers (2026-11-13 patch, not built yet)

Expected: PoE1 gear gets PoE2-style item tiers (unid "Tier N"). When the patch lands:
1. New FilterBlade exports into `reference/`; grep for new conditions (`UnidentifiedItemTier`, or a
   new name). `filtersim` already models `UnidentifiedItemTier` (item field `unid_tier`, PoE2); a new
   name -> `filtersim._match` first (`LiveCache.test_filter_fully_modelled` / parity tests fail otherwise).
2. Diff NeverSink's gear blocks (rares hide layer, crafting bases, chancing): PoE2 export uses
   `UnidentifiedItemTier <= 3` + `Sockets 0` + `Quality 0` hiders at `AreaLevel >= 65` (see
   `reference/league-filterblade-poe2.filter` "c3.gear.any.hiding").
3. Hooks for ours: rare hide (`RARE_GROUPS`, `[rares.*]`) = min tier to show per group; crafting bases
   (`price_crafting_bases`, priced per ilvl range) = only if poe.ninja `BaseType` lines gain a tier field
   (check `cache/<league>/st_BaseType.json`), else unchanged. New keys: write defaults in `config.toml`
   (no hidden settings), loosen in `league_start_values`, docs (CONFIG / TIERING / README).
4. Never hide a tier the price feed can't see: unpriced tier -> blue, not hidden.

## PoE2 gotchas

- `config_poe2.toml`: plain keys after `[tiers]` land inside that table; top-level keys go above it.
- poe.ninja `volumePrimaryValue` is in the feed's primary currency; `price_exchange` converts it to divines.
- PoE2 class names: runes/soul cores/idols = `Augment`, currency = `Stackable Currency`, omens = `Omen`. Our price blocks match BaseType only.
- PoE2 tests: `tests/test_filter_poe2.py` passes a tiny fake module (`MODULE`, toggles `MODULE_TOGGLES`, `cfg["modules"] = {"test": True}`) to `build_text`; `add_item(data, feed, name, div, volume_div)`.
- Colours: only in config `[colors]`. Styles, `rules/*.filter`, code write names (`SetTextColor red`); unknown name -> ValueError. New colour = new `[colors]` entry. Report reads config style lines: resolve names (`report.tier_strip`).
- `reference/league.filter` = user's FilterBlade customization (Very Strict); `regular-neversink.filter` = stock. The build never reads `reference/` (test `NoReference.test_build_without_reference` guards `Path.read_text/read_bytes/open`): NeverSink blocks become our modules via `tools/import_neversink.py` (owns `parse_ref_blocks`; `apply_palette` snaps their colours to `[colors]`), fallback tiers via `tools/import_fallback_tiers.py`. Commented-out `#Show` blocks = off keys LS turns on.
- Parity test (`tests/test_parity.py`, needs `cache/<league>/` + `reference/league.filter`): `python -m unittest discover tests -p test_parity.py`; `python tests/test_parity.py` prints gaps grouped, explained-reason counts and the reverse direction (ours shows, league.filter hides) per class. A gap = fix the filter, or add a specific reason: our deciding block comment -> `EXPLAINED` regex, item-level price -> `price_reason`, user decision -> `reason_for`. Corpus items come from block conditions (`items_for_block`): a new league.filter condition needs `filtersim._match` and `items_for_block` support. ~20 s.
- Quality-threshold module block (overquality / perfection / flask / unique quality): modules.toml value `"config.toml [overquality]"` + entry in `OVERQUALITY_TOGGLES` + key in config.toml `[overquality]`. Parity explains league.filter shows by an off key (`overquality_reason`).
