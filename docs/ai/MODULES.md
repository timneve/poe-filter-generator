# NeverSink -> own modules (migration plan, living doc)

Goal: every feature the user's FilterBlade filter (`reference/league.filter`) has exists in our
filter as OUR rule module, with the same options (per-block on/off like FilterBlade). The build
never reads `reference/` (only `tools/import_neversink.py` / `tools/import_fallback_tiers.py` do;
test `NoReference`). PoE2 has its own modules (`rules/modules_poe2/`, section "PoE2" below).
Price-driven systems (poe.ninja tiers) stay; a module only covers what price can't decide
(mods, item states, leveling, map progression ...).

## Module system (done)

- `rules/modules/<name>.filter`: our blocks. `Show # <key>` / `Hide # <key>`, section lines
  `# [NNNN] title` (NeverSink numbering kept so emitters can pick ranges). Borders / bg dropped.
- `modules.toml` `[<name>.blocks]`: every key -> true/false (default = FilterBlade on/off; a
  commented-out `#Show` / `#Hide` there = false). `league_start` turns every off Show block on (`league_start_values`, except `LS_KEEP_SECTIONS`) and
  every on Hide off (except `LS_KEEP_HIDES`: maps [3302] tier Hides, leveling). A string value (importer `--config-key REGEX=NOTE`) = block decided by the emitter from
  config.toml (`module_blocks(driven=)`), e.g. rares `"rr.t1" = "config.toml [rares]"`: one
  source of truth when config.toml already has richer options for those blocks.
- Block header may carry NeverSink strictness tags after the key (`Show # key %D3`, `%H2`,
  `!utility_layer`; importer keeps them, `load_module` -> `tags`); only leveling uses them.
- `config.toml [<name>] enabled`: whole module on/off (user-facing, documented there;
  leveling: `[leveling] enabled`).
- Code: `tools/import_neversink.py` `parse_ref_blocks` (NeverSink export -> blocks), `load_module`, `module_on`,
  `module_blocks(cfg, name, label, sections=, classes=, only=, drop_classes=, unhide=, extra_conds=)`
  (`classes` / `drop_classes` / `only` / `unhide` per block; `extra_conds` = {key: [lines]} added to one block, e.g.
  `Rarity <= Rare` so a priced unique isn't caught), `_transform_block`.
- Make / refresh: `python tools/import_neversink.py <name> <first>:<after> ...` (keeps values;
  the exact command per module is in the comment above its emitter, e.g. rares needs `--config-key`).
- Tests: `test_modules_keys_match_modules_toml` (file keys == toml keys, unique),
  `test_module_missing_key_raises`; per module a Synthetic filtersim test (shown, toggled off,
  LS, enabled=false).

## Rules for every module task

1. Import with the tool; never hand-copy NeverSink text.
2. Emit at the position league.filter has the section relative to our emitters (see
   ARCHITECTURE block order); explain the order in the emitter docstring.
3. Price beats module only where league.filter also lets economy decide (e.g. uniques, bases).
   Jackpot / blue "variable" rules (AGENTS.md) still hold: a module may never hide a jackpot.
4. New condition -> `filtersim._match` first.
5. Tests: filtersim visibility of real items per block family + toggle + LS + enabled=false.
   LiveCache must still pass.
6. Docs same change: config.toml comment + CONFIG.md row, ARCHITECTURE.md row, TIERING.md
   section 9, README bullet, tick the checklist below.

## Checklist (section -> module)

| Sections | Module | Status |
|---|---|---|
| [[0600]] [[0700]] [0801] [0802] [[1000]] ID mods | `id_mods` | done |
| [0803] [1303] [[2500]] flasks | `flasks` | done |
| [0902] memory strands, [[1100]] exotic mods (all, not only fractured), [[1200]] exotic classes + relics, [[1300]] variations (double corrupt, abyss-jeweled, fractured, enchanted, crucible) | `exotics` | done (after `id_mods`; uniques stay priced: `EXOTIC_NOT_UNIQUE`) |
| [0302] influenced gear, [[0400]] eldritch, [[0500]] exotic bases, [0901] perfection / overquality | `gear_special` | done (`emit_perfection` after id_mods; `emit_priced_bases_first` + `emit_gear_special` after exotics (id-mod / exotic look beats base price, price beats gear_special); `[overquality]` drives its 3 overquality keys, independent of `[gear_special]` (`emit_overquality` gone); [[0500]] conditional entries `s0500_*` -> price / grasping_mail recipe) |
| [[1700]]-[[2200]] endgame rare decorators / veiled / corrupted / conditional hides / ARB / droplevel, [2602] remaining rares, [[2700]] hide layer | `rares` | done (`emit_rares` + `emit_rare_hide_layer`; rr base tiers config-driven; [[2600]] animated-weapon `#Show`s imported off, excluded from LS) |
| [[1400]] links, [[2300]] crafting, [[2400]] chancing, [2601] RGB | `crafting` | done (`emit_links` after exotics, `emit_endgame_crafting` before `emit_rare_hide_layer`; RGB / 6-socket keys -> `[vendor_recipes.chromatic/jeweller]`, no block; top.filter show_5_links/6_links kept (tink, any rarity: not a duplicate); [[2600]] animated weapons in `rares`; [2302] not LS-unlocked) |
| [2801] [2803] [2804] jewels, [2805] [2806] clusters | `jewels` | done (`emit_jewels`; cluster node names: `module_cluster_nodes`; [2805] off blocks = empty eco tiers, not LS-unlocked) |
| [[2900]] heist gear | `heist` | done (`emit_heist`, after jewels) |
| [0301] [3201]-[3204] special maps, [3302] progression, [[3400]] pseudo-map items, [[3500]] misc map items | `maps` | done (`emit_special_maps` incl. [3400]-[3500] after stackables, `emit_map_progression`) |
| [[0100]] 6L overrides, [[0200]] gold, [[4500]] [[4900]] questlike, [[4600]] enshrouded, [[4700]] idols | `misc` | done (`emit_gold` before top.filter: `show_gold` beats module; `emit_misc` before / after uniques; `6l.*` = `show_6_links` string keys, not emitted; top.filter quest block keeps only Quest Items / Pantheon Souls) |
| [2802] [[3800]] [[5000]]-[[5400]] leveling | `leveling` | done (`leveling_module_blocks` inside `emit_leveling`, after build module + `[leveling]` hides; strictness-tagged keys `"config.toml [leveling] strictness"` -> `leveling_strictness_block`, LS leaves them; FilterBlade-off options false (quicksilver / utility alerts true: as before), LS on; [[3800]] strictness-driven, price first (`leveling_price_first`); [5406]/[5407] = `rules/bottom.filter`) |
| `reference_currency_tiers` / `reference_card_tiers` fallbacks, [[3000]] gems, [[3600]]-[[4400]] currency specials, [[4800]] uniques | price fallbacks + `unique_exceptions` | done: `fallback_tiers.toml` (`tools/import_fallback_tiers.py`), coverage below; [4801] / [4803] / [4804] overqual -> module `unique_exceptions` |
| Parity test: items league.filter shows (filtersim on reference) are shown by ours unless price-hidden | `tests/test_parity.py` | done (summary below) |
| Build reads no `reference/` (only importer) | cleanup | done (`neversink_blocks` + unused read removed, parser moved to `tools/import_neversink.py`, test `NoReference`) |
| PoE2: FilterBlade export appended whole | `rules/modules_poe2/` | step 1 done (see PoE2 below) |

## Price-fallback coverage (league.filter [[3000]], [[3600]]-[[4400]], [[4800]])

Fallback tiers: `fallback_tiers.toml` (`[currency]` NeverSink tier number, `[cards]` group), made by
`tools/import_fallback_tiers.py`, test `test_fallback_tiers_file_matches_reference_import` = same
names / groups as the old build-time parse. "Price" = poe.ninja tier (stack blocks up to
`max_stack`) decides where confident; differing visibility there is a tier, not a missing feature.

| league.filter feature | Ours | Status |
|---|---|---|
| [3001] exceptional gems (Awakened, Empower / Enlighten / Enhance, corrupted, lvl / qual) | `emit_gems` price + top.filter Awakened / Enlighten / Empower / Enhance Show | covered |
| [3001] conditional Hide Portal / Foulgrasp / Hiveborn / Machinations | price (cheap = hidden by bottom.filter) | covered (price) |
| [3002] transfigured `altany` | `emit_gems` TransfiguredGem blue | covered |
| [3002] economy lists 20/20, 21/20, 20/23, 21/23, vaal 20% | `price_gems` per variant + `emit_gem_fallback` blue 21+ / 23 | covered (price) |
| [3003] lt1 / qt1 (21+ / 23%) | `emit_gem_fallback` blue when unpriced | covered |
| [3003] qt2 20% / lt2 lvl 20 / lt3 lvl 18 / ex6lvlgems | top.filter 20% Show; levels: price (hidden when cheap) | 20% covered; lvl 18-20 = price decision |
| [3003] firstzone / leveling / levelingvaal / qt4lvl (campaign gems) | `emit_leveling` `show_gems` (module `leveling`) | covered (leveling) |
| [3003] rest Hide | bottom.filter gem Hide | covered |
| [3601] scarab tiers, t3stackedex x3 | price + stack blocks | covered (price) |
| [3602] fragment tiers, stacked x3, conditional Hides (Sacrifice / Writhing Invitation / Divine Vessel) | price + stack blocks | covered (price; those Hides = price) |
| [[3700]] lifeforce / Dead Man's Sulphur stack tiers (x20 .. x12500) | `[exchange.big_stacks]` | **added** |
| [[3800]] leveling currency (all off) | `campaign_unhide` (`show_all_stackables`) | covered |
| [3901] conditional stack Shows (t5 lists x5, t6 x14) | priced: stack blocks; unpriced: `[exchange.reference_currency_stacks]` | **added** (unpriced) |
| [3902]-[3906] supply / stacked currency (all off) | price stack blocks | covered |
| [3907] Rogue's Marker >= 2500 Show, rest Hide | `big_stacks` 2500 (price decides: ~0.5c at 2500 = hidden) | **added** (price) |
| [3907] Silver Coin | unpriced -> blue | covered |
| [[4000]] currency tiers t1-t9 | price; unpriced -> `fallback_tiers.toml` | covered |
| [4101]-[4112] vials, delirium, fossils / resonators, ducats, oils, runegrafts, corpses, essences, omens, tattoos, scrying / imprint / lens, wombgifts (+ restex) | price per item; unpriced -> fallback tier / blue catch-all per class | covered |
| [4105] conditional Hide Amber / Clear / Sepia / Verdant Oil | Amber / Verdant: `[exchange.unpriced_tiers]` hide; Clear / Sepia: `[overrides]` dust (user choice) | **added** (Amber / Verdant) |
| [4201]-[4203] splinter stacks | `[exchange.splinters]` price / count + stack blocks | covered |
| [[4300]] card tiers t1-t5, tnew | `card_rewards` price, else `fallback_tiers.toml [cards]` (low volume), else blue | covered |
| [[4300]] exstack (any card x3) / The Fortunate x3 | `card_fallback_stack` for unpriced hidden-group cards; priced cards: price x stack | **added** |
| [[4400]] Scroll Fragment Hide | `[exchange.unpriced_tiers]` hide | **added** |
| [[4400]] restex Stackable Currency | blue unpriced catch-all | covered |
| [4801] influenced / Kaom / Tabula / synth / abyss uniques | module `unique_exceptions` | **added** |
| [4802] t1 / t2 unique bases, conditional base Show | unique price per base (EV / cheapest) | covered (price) |
| [4803] Vestigial, unique idols, 2x corrupted, 2x abyss, crucible | module `unique_exceptions` | **added** |
| [4804] multispecial(high) base lists, Foulborn | unique / Foulborn price (modules.toml string value) | covered (price) |
| [4804] overqual unique (ours 21%+, league.filter 27%+) | module `unique_exceptions` | **added** |
| [4805] unique jewels, corrupted uniques per class | `variable_classes` blue, `[corrupted_implicits]` | covered |
| [4806]-[4807] t3 / boss / hideable tiers + Hides | unique price | covered (price) |

## Parity summary (`tests/test_parity.py`, cache Allflame, 2026-11-05)

Corpus ~20.6k items: every cache item (priced stackables, fallback currency / cards + every card
x3, unique bases unID + Foulborn, poe.ninja bases / gems / clusters / maps) + one item per
league.filter Show block x BaseType x allowed rarity. league.filter shows, ours hides: 0
unexplained. Explained (counts): stackable / card price hidden tier 580, unpriced cheap
NeverSink card groups t4 / t4c / t5 / t5c 484, gem variant price (exact Hides / bottom) ~510,
level 18-20 gems price (user) 330, unique base price 163, Foulborn price 147, card 3-stacks price
(user) 43, gem capped by better variant 33, config toggles (show_gold, show_contracts) 31,
crafting base below `[bases] min_tier` 7, corrupted map tier 3.
Gaps found + fixed: unlisted gems (Item Quantity / Transfusion Support) -> blue
(`emit_unknown_gems`); unpriced corpses -> blue (`CURRENCY_CLASSES` Corpses); Omen of
Refreshment / Soul Devourer -> blue (`[exchange.unpriced_tiers]`); Rogue's Marker 2500+
(`[exchange.show_stacks]`); Reliquary keys always top (`always_top_classes`).
Reverse (ours shows, league.filter hides; informational): ~440, mostly priced cluster jewels
(355: poe.ninja tier vs NeverSink's strict cluster Hides), then priced gems (25), fragments /
currency / cards (~30 priced or blue), uniques on priced / content / variable bases (~20).

## PoE2 (`rules/modules_poe2/`, `modules_poe2.toml`)

Whole `reference/league-filterblade-poe2.filter` imported 1:1 (`--game poe2 --stock
reference/regular-neversink-poe2.filter`), 13 modules by section (ranges in `config_poe2.toml`
`[modules]` comments). `build_filter_poe2.module_rules` emits turned-on blocks in section order,
so the default build has exactly the export's rule sequence (checked once on 2026-11-09: 507
blocks, same action + conditions). Tink (white background) blocks keep border / background;
`no_borders` sets every other border to opacity 0. `modules_poe2.toml` comments: "(off in
FilterBlade)" + "(stock NeverSink: ...)" where the user's export differs from stock.
Tests `Poe2Modules`: file keys == toggles, `[modules]` == files, every export block (key, action,
conditions) in a module, one module per section.

Remaining (next steps):
1. Exchange prices own NeverSink's currency / omen / essence / catalyst / emotion tiers (module
   blocks for priced names become redundant; keep only unpriced).
2. `tools/league_start.py` for PoE2 (loosen module Hides: currency d / e, rr, salvage, t3boss ...).
3. Parity test like `tests/test_parity.py` once modules diverge from the export.
