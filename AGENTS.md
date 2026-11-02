# Assistant guide

This folder is the PoE1 loot-filter generator. Read `README.md` for player-facing
behavior and `config.toml` for thresholds and toggles before changing filter behavior.

## Code map

- `build_filter.py` fetches/caches poe.ninja data, calculates item tiers, and generates
  the filter. `build_text()` is the no-network entry point used by tests.
- `config.toml` is the source of tier thresholds, pricing confidence settings, overrides,
  and style. Keep config comments in sync with behavior changes.
- `rules/top.filter` and `rules/bottom.filter` are hand-written rules around generated
  price rules. Do not edit `out/pricefilter.filter` directly; regenerate it.
- `filtersim.py` evaluates the supported filter syntax for tests. Add simulator support
  before relying on a new filter condition in a test.
- `tests/test_filter.py` contains synthetic pricing tests and live-cache replay tests.
- `report.py` builds `out/report.html` from raw prices and the generated filter.

## Crafting-base pricing

Crafting bases are priced separately by exact base, influence, and item-level range.
`[bases]` controls the minimum tier and the required `listingCount` (`min_listings`) and
sample `count` (`min_samples`) from poe.ninja. A high price with too few samples is not
reliable enough to produce a rule; adjust these thresholds for stricter filtering. Do not
compare prices across item levels to infer confidence: a higher-level base may legitimately
be more valuable due to crafting demand. Keep this pricing separate from unique pricing.

## Validation

Run tests from this folder:

```powershell
python -m unittest discover tests
```

For focused checks, use unittest discovery (the `tests` directory is not a Python package).
Synthetic crafting-base tests should cover low-sample prices being rejected and sufficiently
sampled jackpot prices being shown. Check generated filter visibility, not only the
intermediate price-tier list.
