---
name: filterblade-parity
description: Use whenever the user says a feature should work "like NeverSink", "like FilterBlade", "like the PoE2 filter", "same options as FilterBlade", or shows a FilterBlade screenshot. Forces checking the real NeverSink / FilterBlade filter file AND the FilterBlade website before building, and mirroring the structure 1:1 (same options, cells, keys, defaults, styles) instead of inventing a simpler design.
---

# Like NeverSink / FilterBlade = copy it 1:1, check both sources first

The user's words "like NeverSink / FilterBlade" mean: the SAME options a FilterBlade user sees
(every checkbox / cell / grid), the same keys, defaults and styles. Never a "simpler" or
"equivalent" design of your own. A wrong filter in a live league is the failure to avoid.

## 1. Read the filter file (always, before any design)

- PoE1: `reference/league.filter` (user's FilterBlade export), `reference/regular-neversink.filter`
  (stock), our modules `rules/modules/*.filter` + `modules.toml`.
- PoE2: `reference/league-filterblade-poe2.filter`, `reference/regular-neversink-poe2.filter`,
  our `rules/modules_poe2/*.filter` + `modules_poe2.toml`.
- Grep the section (`# [NNNN]` / block key prefix like `ut->`), then read EVERY block of it:
  key, strictness tag (`%D5`), each condition, style lines, default on/off (`modules*.toml`,
  `#Show` = off). List the full structure (e.g. rarity x group x tier x rank grid + extras).
- Don't read whole reference files (huge): grep, then read the section range.

## 2. Check the FilterBlade website

- https://www.filterblade.xyz/ (PoE1) / https://www.filterblade.xyz/?game=Poe2 : open the
  section the user means, note every option name / group / checkbox, its default and preview.
- Use a browser tool: load the `anthropic-skills:chrome-browser` skill (Claude in Chrome,
  `mcp__claude-in-chrome__*`) or `anthropic-skills:built-in-browser` (`mcp__Claude_Browser__*`),
  then navigate. A plain web fetch can't render FilterBlade (JS app).
- No browser tool in the session: say so in the FIRST reply, before building, and ask for
  screenshots of the section. Never silently skip the website.

## 3. Before writing code: show the mapping

Short table to the user: FilterBlade option -> our key / block -> condition / style -> default.
Every difference (e.g. PoE2 base lists -> PoE1 bases, AreaLevel 65 -> 68) listed and justified.
Anything with no PoE1 / PoE2 counterpart: ask, don't drop or invent.

## 4. Build

- Prefer a rule module (`rules/modules/<name>.filter`, per-block toggles in `modules.toml`,
  `module_blocks`): every FilterBlade checkbox = one toggle. Import with `tools/import_neversink.py`
  when NeverSink has the section; otherwise generate it from the source structure with a script
  (e.g. `tools/make_unid_tier.py`), never hand-type NeverSink text.
- Follow `docs/ai/MODULES.md` rules (position = NeverSink section order, price beats module only
  where FilterBlade lets economy decide, league_start turns off Shows on).

## 5. Prove parity in tests

- A test that our module equals the source structure (keys, order, tier / rarity conditions,
  styles, tags), e.g. `test_unid_tier_module_matches_poe2_grid`.
- filtersim tests per cell family with real items, one toggle off, `enabled = false`, league start.
- Never delete a test to make a redesign pass without telling the user why it is obsolete and what
  replaces it.
