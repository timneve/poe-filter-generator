# AI guide (start here)

PoE1 + PoE2 loot-filter generators. Visibility/style = poe.ninja price tier. Python 3.11+, stdlib only,
no network in tests. Player-facing behavior: `README.md`. Read only the doc you need:

| Need | Read |
|---|---|
| Pipeline, data shapes, function index, filter block order | `docs/ai/ARCHITECTURE.md` |
| What a `config.toml` key does + which function reads it | `docs/ai/CONFIG.md` |
| How to do common changes, gotchas, test patterns | `docs/ai/RECIPES.md` |

## Files (size = read cost)

| File | Lines | Role |
|---|---|---|
| `build_filter.py` | ~1400 | PoE1: fetch -> price -> emit filter text -> write + report. Entry `main()`; `build_text()` = no-network core |
| `config.toml` | ~690 | PoE1 settings, heavily commented. Source of truth for tiers/styles/toggles |
| `unique_tiers.toml` | ~200 | unique name -> drop-rarity tier 0..5 (for `[uniques.ev]` drop weights) |
| `rules/top.filter` / `rules/bottom.filter` | 66 / 42 | Hand-written blocks before / after price rules |
| `rules/leveling/rf.filter` | 156 | Build module for campaign (`[leveling] build = "rf"`) |
| `filtersim.py` | ~120 | Mini filter evaluator (tests + report), PoE1 + PoE2 conditions. Unknown condition -> raises |
| `report.py` | ~480 | Writes `out/report.html` (mostly an embedded HTML/JS `PAGE` string) |
| `assets/chaos.png`, `assets/divine.png` | - | Currency icons, inlined into the report as data URIs by `report.icon()` |
| `report_poe2.py` | ~130 | Writes `out/report_poe2.html`: tier values in ex, rates, priced items |
| `build_filter_poe2.py` + `config_poe2.toml` | ~340 / 40 | PoE2, separate: poe.ninja exchange prices tiered in divines, NeverSink PoE2 export appended below |
| `tests/test_filter.py` | ~1200 | `Synthetic` (fake data) + `LiveCache` (replays `cache/`) |
| `tests/test_filter_poe2.py` | ~210 | PoE2 synthetic (fake reference) + `Poe2LiveCache` (replays `cache/poe2/`) |
| `reference/*.filter` | big | NeverSink/FilterBlade exports. Parsed at build (`league.filter`, `regular-neversink.filter`; PoE2: `league-filterblade-poe2.filter` appended whole). Don't read whole; grep |
| `cache/`, `out/` | gitignored | poe.ninja/wiki JSON cache; generated filter + report. Never edit `out/` |

## Hard rules

- Never edit `out/*.filter`; change config / rules / code and rebuild.
- New filter condition in rules or emitted code -> add it to `filtersim._match` first (else `LiveCache.test_filter_fully_modelled` fails).
- Behavior change -> update the matching comment in `config.toml` and `README.md`.
- Docs stay current, same change as the code (task not done until docs match):
  - config key added/removed/renamed/LS-affected -> `docs/ai/CONFIG.md`
  - function, emitter, filter block order, `data`/`r` shape, constant, file added/removed -> `docs/ai/ARCHITECTURE.md` (+ file table here)
  - new workflow, test helper or gotcha learned -> `docs/ai/RECIPES.md`
  - player-visible behavior -> `README.md`
  - Keep docs terse; reference functions by name, not line numbers. Wrong doc = fix it when seen.
- Style rule (user pref): no borders / backgrounds except top tier (tink); gear text white/brown; calm look.
- Divine, Mirror, Hinekora's Lock always top/tink (`PINNED_TOP_STACKABLES`), not overridable.
- Any vendor / crafting recipe (Grasping Mail, chromatic, jeweller, gemcutter, glassblower, new ones)
  = a `[vendor_recipes.*]` entry, all grouped there, tier = FLOOR: ingredient worth more keeps its own
  tier (uniques, crafting bases, overrides), cheap / hidden ones get the recipe tier. Never hand-write
  recipe blocks in `rules/*.filter` or as plain toggles.
- Jackpot (`jackpot_divine`) items must never be hidden; group can't tell -> "variable" (blue).
- Crafting bases priced per exact base + influence + ilvl range; need `min_listings` AND `min_samples`; each confident price covers only its own ilvl range (higher ilvl does not floor lower). Keep separate from unique pricing.
- Check generated filter visibility (via `filtersim`) in tests, not just intermediate tier dicts.
- Syntax reference: https://www.pathofexile.com/item-filter/about

## Commands (run in this folder)

```
python -m unittest discover tests          # all tests (tests/ is not a package)
python -m unittest discover tests -k ev    # filter by name
python build_filter.py [--refresh] [--league NAME]
python build_filter_poe2.py [--refresh]
```
`LiveCache` tests need `cache/<league>/` populated (run a build once).
