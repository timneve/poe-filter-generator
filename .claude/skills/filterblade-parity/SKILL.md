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
- DO IT YOURSELF with `fb.py` (this folder, Playwright + Chromium are installed on this PC). No
  browser MCP tool needed, never ask the user for screenshots. Each arg = click the element with
  that exact text (`~text` = substring), in order; writes `OUT/page.txt` (all text) + `page.png`
  + `step<N>.png`. Cookie banner + "Select a game" modal are dismissed automatically:
  ```
  python .claude/skills/filterblade-parity/fb.py <scratchpad>/fb "Customize" "Endgame - Special Bases & Crafting" "Influenced Items" "Specific Influence BaseTypes" "INFLUENCED BASES - CRUSADER"
  ```
  Path: Customize -> category (e.g. "Endgame - Rares") -> section -> subsection -> block title
  (UPPERCASE as shown). Clicking a block title opens its editor: base list, influence /
  ItemLevel conditions, "Edit visuals and sounds". Read the text dump first (cheap), png only for
  layout. `--poe2` for PoE2.
- Raw current filter (exact lists, best source): the site downloads
  `https://www.filterblade.xyz/datafiles/filters/NeverSink_AutoEcoUpdate_tmpstandard/NeverSink's%20filter%20-%200-SOFT.filter`
  (+ `datafiles/optionfiles/optionFile*.options`, `datafiles/other/BasetypeStorage.csv`). Capture it
  with Playwright `page.on("response")` while loading the home page (folder name changes per
  league; plain fetch of a guessed URL may 404). Grep its `# [NNNN]` section like the reference files.
- The website = current NeverSink version (newer than `reference/league.filter` when a patch
  landed): compare its lists with the export and say which differ.

## 3. Before writing code: show the mapping

Short table to the user: FilterBlade option -> our key / block -> condition / style -> default.
Every difference (e.g. PoE2 base lists -> PoE1 bases, AreaLevel 65 -> 68) listed and justified.
Anything with no PoE1 / PoE2 counterpart: ask, don't drop or invent.

## 4. Build

- Prefer a rule module (`rules/modules/<name>.filter`, per-block toggles in `modules.toml`,
  `module_blocks`): every FilterBlade checkbox = one toggle. Import with `tools/import_neversink.py`
  when NeverSink has the section; otherwise generate it from the source structure with a script,
  never hand-type NeverSink text.
- Follow `docs/ai/MODULES.md` rules (position = NeverSink section order, price beats module only
  where FilterBlade lets economy decide, league_start turns off Shows on).

## 5. Prove parity in tests

- A test that our module equals the source structure (keys, order, tier / rarity conditions,
  styles, tags).
- filtersim tests per cell family with real items, one toggle off, `enabled = false`, league start.
- Never delete a test to make a redesign pass without telling the user why it is obsolete and what
  replaces it.
