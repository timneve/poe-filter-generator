# AI guide (start here)

PoE1 + PoE2 loot-filter generators. Visibility/style = poe.ninja price tier. Python 3.11+, stdlib only,
no network in tests. Player-facing behavior: `README.md`. Read only the doc you need:

| Need | Read |
|---|---|
| **How every item gets its tier (all pricing / visibility systems)** - read before any pricing change | `docs/ai/TIERING.md` |
| Pipeline, data shapes, function index, filter block order | `docs/ai/ARCHITECTURE.md` |
| What a `config.toml` key does + which function reads it | `docs/ai/CONFIG.md` |
| How to do common changes, gotchas, test patterns | `docs/ai/RECIPES.md` |
| NeverSink -> own modules: system, rules, migration checklist | `docs/ai/MODULES.md` |

## Files (size = read cost)

| File | Lines | Role |
|---|---|---|
| `build_filter.py` | ~2700 | PoE1: fetch (every poe.ninja category, `NINJA_TYPES`) -> price -> emit filter text -> write + report. Entry `main()`; `build_text()` = no-network core |
| `config.toml` | ~1260 | PoE1 settings, heavily commented. Source of truth for tiers/styles/toggles |
| `config_standard.toml` | ~1260 | Full copy of `config.toml` for Standard league (own `league` / `output_name`); `build_filter.py --config config_standard.toml`. Key added to config.toml -> add here too |
| `modules.toml` | ~670 | per-block on/off of our rule modules (FilterBlade-style options), `[<module>.blocks]` |
| `rules/modules/*.filter` | - | Our rule modules (imported once from NeverSink, then ours). See `docs/ai/MODULES.md` |
| `tools/import_neversink.py` | ~200 | Make / refresh a module from `reference/league.filter` sections (`--game poe2`: PoE2 export -> `rules/modules_poe2/`; `--stock`: note blocks differing from stock NeverSink) (owns the NeverSink parser `parse_ref_blocks`) |
| `tools/import_fallback_tiers.py` + `fallback_tiers.toml` | ~90 / ~970 | NeverSink currency / card group per name (fallback when poe.ninja has no confident price); tool makes the TOML once, build reads the TOML |
| `tools/league_start.py` | ~300 | League start as real values: `start` (backup to `league_start/backup/`, gitignored, then writes `build_filter.league_start_values` into config.toml / modules.toml as text, comments kept), `status`, `restore [KEY]`, `finish`; `--root` for tests. Player guide `docs/LEAGUE_START.md` |
| `leagues.toml` / `leagues_poe2.toml` | small | Generated every build (`write_league_list`): poe.ninja league names (current / no_prices / old) to pick `league` from. Don't edit |
| `unique_tiers.toml` | ~200 | unique name -> drop-rarity tier 0..5 (for `[uniques.ev]` drop weights) |
| `rules/top.filter` / `rules/bottom.filter` | 66 / 22 | Hand-written blocks before / after price rules |
| `rules/leveling/rf.filter`, `minion.filter` | 156 / 120 | Campaign build modules (`[leveling] build = "rf"` / `"minion"`) |
| `filtersim.py` | ~140 | Mini filter evaluator (tests + report), PoE1 + PoE2 + every `reference/league.filter` condition. Unknown condition -> raises |
| `report.py` | ~720 | Writes `out/report.html` (mostly an embedded HTML/JS `PAGE` string) |
| `assets/chaos.png`, `assets/divine.png` | - | Currency icons, inlined into the report as data URIs by `report.icon()` |
| `report_poe2.py` | ~130 | Writes `out/report_poe2.html`: tier values in ex, rates, priced items |
| `build_filter_poe2.py` + `config_poe2.toml` | ~400 / 65 | PoE2, separate: poe.ninja exchange prices tiered in divines, then our PoE2 rule modules (`[modules]` on/off) |
| `rules/modules_poe2/*.filter` + `modules_poe2.toml` | - / ~530 | PoE2 rule modules (imported from `reference/league-filterblade-poe2.filter` by `tools/import_neversink.py --game poe2`, then ours) + per-block toggles |
| `tests/test_filter.py` | ~2880 | `Synthetic` (fake data) + `LiveCache` (replays `cache/`, every poe.ninja feed) |
| `tests/test_filter_poe2.py` | ~320 | PoE2 synthetic (fake module) + `Poe2Modules` (files == toggles == export) + `Poe2LiveCache` (replays `cache/poe2/`) |
| `tests/test_league_start.py` | ~200 | `tools/league_start.py` on temp copies: comments kept, start-written files == `league_start = true` (same filter text, Synthetic + live cache), status / restore round trip, double start refused |
| `tests/test_parity.py` | ~340 | `Parity`: items league.filter shows must be shown by ours or explained (cache + per-block corpus); `NoReference`: build reads no `reference/` |
| `reference/*.filter` | big | NeverSink/FilterBlade exports. Builds never read them (only `tools/import_*.py` + tests); `regular-neversink-poe2.filter` = stock PoE2 (importer `--stock`). Don't read whole; grep |
| `cache/`, `out/` | gitignored | poe.ninja/wiki JSON cache; generated filter + report. Never edit `out/` |

## Hard rules

- Never edit `out/*.filter`; change config / rules / code and rebuild.
- New filter condition in rules or emitted code -> add it to `filtersim._match` first (else `LiveCache.test_filter_fully_modelled` fails).
- Behavior change -> update the matching comment in `config.toml` and `README.md`.
- Docs stay current, same change as the code (task not done until docs match):
  - config key added/removed/renamed/LS-affected -> `docs/ai/CONFIG.md`
  - function, emitter, filter block order, `data`/`r` shape, constant, file added/removed -> `docs/ai/ARCHITECTURE.md` (+ file table here)
  - tier / visibility decision added or changed (any item kind) -> `docs/ai/TIERING.md`
  - new workflow, test helper or gotcha learned -> `docs/ai/RECIPES.md`
  - player-visible behavior -> `README.md`
  - Keep docs terse; reference functions by name, not line numbers. Wrong doc = fix it when seen.
- Style rule (user pref): no borders / backgrounds except top tier (tink); gear text white/brown; calm look.
  Beams always permanent (no `PlayEffect ... Temp`); every crafting / quality Show has an icon + beam.
- Divine, Mirror, Hinekora's Lock always top/tink (`PINNED_TOP_STACKABLES`), not overridable.
- Any vendor / crafting recipe (Grasping Mail, chromatic, jeweller, gemcutter, glassblower, new ones)
  = a `[vendor_recipes.*]` entry, all grouped there, tier = FLOOR: ingredient worth more keeps its own
  tier (uniques, crafting bases, overrides), cheap / hidden ones get the recipe tier. Never hand-write
  recipe blocks in `rules/*.filter` or as plain toggles.
- Jackpot (`jackpot_divine`) items must never be hidden; group can't tell -> "variable" (blue).
- Blue "variable" = probably valuable, no exact price (thin volume, unlisted variant), app-wide:
  unconfident -> blue, never hidden or guessed. Confident price in a config-hidden tier -> hidden
  (exact Hide before any blue catch-all).
- Crafting bases priced per exact base + influence + ilvl range; need `min_listings` AND `min_samples`; each confident price covers only its own ilvl range (higher ilvl does not floor lower). Keep separate from unique pricing.
- No hidden settings (user pref): every key / per-item option the code reads must be written out in
  `config.toml` with its default value, so a reader sees all they CAN toggle. Optional per-name tables
  (e.g. `[content.<mod>.drops]`) list every known name (default `"price"`). New key -> add it there too.
  Tests that use fake data clear such full lists in `Synthetic.setUp`.
- Check generated filter visibility (via `filtersim`) in tests, not just intermediate tier dicts.
- Syntax reference: https://www.pathofexile.com/item-filter/about

## Commands (run in this folder)

```
python -m unittest discover tests          # all tests (tests/ is not a package)
python -m unittest discover tests -k ev    # filter by name
python build_filter.py [--refresh] [--league NAME]
python build_filter.py --config config_standard.toml   # Standard filter (pricefilter-standard)
python build_filter_poe2.py [--refresh]
```
`LiveCache` tests need `cache/<league>/` populated (run a build once).
