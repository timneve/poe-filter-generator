# Recipes + gotchas

## Common changes

| Want | Do |
|---|---|
| Force an item's tier | `[overrides]` in config (stackable/any BaseType) or `[unique_overrides]` (unique base) |
| Change tier thresholds | `tiers.*` in config; everything refers to tiers by name |
| Change look of a tier | `[style.<tier>]` lines. Keep: no border/bg except `top`; icon shape is set by code |
| New hand rule | `rules/top.filter` (before prices) or `rules/bottom.filter` (after). Tag `Hide # league_start` if it should show at league start |
| New toggle section in top rules | wrap in `# BEGIN key` / `# END key`, handle in `hand_rules` (expects exactly one section) |
| New config key | add commented default in `config.toml`, read with `cfg.get(...)` default, add to `apply_league_start` if LS should change it, document in `README.md` + `docs/ai/CONFIG.md` |
| New price source / poe.ninja type | build warns / `LiveCache.test_every_ninja_category_handled` fails on a new poe.ninja category. Put it in exactly one of `EXCHANGE_TYPES` / `STASH_STACKABLE_TYPES` / `UNIQUE_TYPES` / `BASE_TYPES` (priced) / `CHECK_TYPES` (only tested: add a drop model to `LiveCache.ninja_drop`) / `SKIPPED_TYPES` (reason); `SHAPE` entry for stackables; `empty_data()` / `load_cache` pick it up automatically |
| New cluster enchant | `test_valuable_ninja_items_visible` fails: add poe.ninja text -> in-game node name to `CLUSTER_NODES` (node names are checked against NeverSink's reference for valuable ones) |
| New emitted section | write `emit_x(cfg, ...)` returning `section(...) + block(...)...`, insert in `build_text` list at the right priority |
| New filter condition | add to `filtersim._match` (+ `NUMERIC`/`BOOL` map) first |
| Campaign build module | copy `rules/leveling/rf.filter`, edit, set `[leveling] build` |
| Add vendor recipe | Check ingredients on poewiki via the API (`api.php?action=parse&page=Vendor recipe&prop=wikitext` with `UA`; the HTML pages are bot-blocked). `[vendor_recipes.<name>]` table in `config.toml` (`enabled`, `tier`, `class`, `bases` or `conds` + `rarity`, optional `any`, `note`); never hand-write recipe blocks in `rules/*.filter` (no floor there). Conditions in `conds` / `any` must be in `filtersim._match`; `report.recipe_sample` must know how to fake them (add a `RECIPE_BASE` example for new classes); `emit_vendor_recipes` + report pick it up automatically |
| Report UI | edit `PAGE` string in `report.py` (PoE2: `report_poe2.py`); data rows from `collect()` |
| PoE2 change | `build_filter_poe2.py` / `config_poe2.toml` only; no shared code with PoE1 (except `filtersim`) |
| PoE2 new poe.ninja feed | add to `[exchange].types` + `SHAPES` (+ `NO_STACK` if it never stacks, `LEVELED_FEEDS` if "(Level N)" means GemLevel) |
| PoE2 gear/uniques/waystones look | not ours: replace `reference/league-filterblade-poe2.filter` with a new FilterBlade export; new conditions in it -> `filtersim` (`Poe2LiveCache.test_filter_fully_modelled`) |

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
- Synthetic `setUp` disables `tiers_follow_divine`, `uniques.ev`, `variable_jackpot_only`, `always_show_bases`, content drops; re-enable in the test if needed (`ev_setup()` for EV).
- `LiveCache` uses real `cache/`; skips some checks when `variable_jackpot_only` is on.

## Gotchas

- `apply_divine_tiers` mutates `cfg["tiers"]` in place. Tests use `copy.deepcopy(cfg)`; `Synthetic.setUp` sets `tiers_follow_divine = False` + `FIXED_TIERS` chaos so numbers stay stable.
- Block order = priority. First non-`Continue` match decides. Defaults are `Continue` blocks.
- `hidden_game_colours` + `maximize_item_sizes` post-process the whole text; font size 45 everywhere except content always-show style (block comment must start `content override show:` to keep its small size).
- Divination card exchange quotes are NOT trusted (no buy/sell direction). Cards priced only via `[exchange.card_rewards]`, else NeverSink fallback when volume < `card_fallback_min_volume`, else `unknown`.
- Shards/splinters priced from finished item, never own quotes; skipped if finished item unpriced.
- Low-volume stackable prices may SHOW an item, never hide it.
- Unique base tier = cheapest unique (not best). Linked (5L/6L) lines excluded from unlinked pricing; handled by `price_linked_jackpots`.
- Boss-only uniques (`data["nomap"]`) excluded unless content module enabled (not for "cheapest" either: Lab-only Winds of Change must not hide Hateforge's base); Foulborn names stripped of `"Foulborn "` prefix for that check.
- PoE filters can't see unique names or drop source before ID: every unique rule is base-wide.
- `reference/*.filter` are huge; grep, don't read. Parsed by tag (`%D<n>`, `%H<n>`, `$tier->...`).
- `wiki_uniques.json` fetch failure -> old cache or no boss skipping (warning on stderr).
- Windows: read/write files with `encoding="utf-8"`.
- poe.ninja ClusterJewel `levelRequired` = ilvl bucket start (`CLUSTER_ILVL`), `variant` = "N passives", `name` = enchant text (not the filter's `EnchantmentPassiveNode` name: `CLUSTER_NODES`).
- poe.ninja SkillGem lines are per level/quality/corrupt variant; only uncorrupted level 1 (q0 / q20) can drop. Alternate gems (transfigured "Cyclone of Tumult", `gemKind` "trarthus" "Heavy Strike of Trarthus"; trade type has a `discriminator`, see `alt_gem`): the name is NOT a BaseType (BaseType = plain gem) and the game rejects the whole filter, so `price_gems` skips them; blue `TransfiguredGem True` block instead. `gemKind` "exceptional" (Empower etc.) are normal BaseTypes.
- `ninja_categories` scrapes poe.ninja's site JS (sidebar config, `type:`...`url:`); cached `cache/ninja_categories.json` a day. Layout change -> warning only.
- Any poe.ninja value test: `LiveCache.test_valuable_ninja_items_visible` (>= `SAFETY_DIVINE`, >= `uniques.min_listings`), maps exempt (`MAP_TYPES`, hidden by `rules/bottom.filter` on purpose).

## PoE2 gotchas

- `config_poe2.toml`: plain keys after `[tiers]` land inside that table; top-level keys go above it.
- poe.ninja `volumePrimaryValue` is in the feed's primary currency; `price_exchange` converts it to divines.
- PoE2 class names: runes/soul cores/idols = `Augment`, currency = `Stackable Currency`, omens = `Omen`. Our price blocks match BaseType only.
- PoE2 tests: `tests/test_filter_poe2.py` passes a tiny fake `REFERENCE` to `build_text`; `add_item(data, feed, name, div, volume_div)`.
