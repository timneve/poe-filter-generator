# League start: show everything, then tighten over the week

At league start prices are thin and you are poor, so the filter should show (almost) all loot.
Over the first week you hide more, step by step. `tools/league_start.py` does this with real
values in `config.toml` / `modules.toml` (not a hidden switch), so you see every loosened line
and can change them one by one.

All commands run in the `poe-filter` folder. After every change: `python build_filter.py`
(or `update.bat`), then reload the filter in game.

## Before the league (day 0)

1. `python tools/league_start.py start --dry-run` - shows what will change (~140 lines).
2. `python tools/league_start.py start` - copies `config.toml` + `modules.toml` to
   `league_start/backup/` (your late-league settings), then writes the loose values.
3. `python build_filter.py --refresh`

What `start` loosens (same list as the `league_start = true` flag, which still works as a
quick one-line switch):

- `hide_tiers` -> `[]` (brown + dust shown), `[small_loot] enabled` -> false
- `[uniques] show.*` all true, `variable_jackpot_only` / `hide_maps` -> false
- `[foulborn]` / `[bases]` / `[gems] min_tier` -> `"dust"`, `[gems] show_all` -> true
- "hide" in `[overrides]`, `[exchange.reference_card_tiers]`, `[exchange.unpriced_tiers]`,
  `unpriced` settings -> `"dust"`
- `show_5_links`, `show_6_links`, `show_mirrored`, `show_contracts` -> true,
  `hide_forbidden_tome` -> false
- `show_gold` + `show_small_gold` -> true: all gold, big stacks keep the big look, small ones
  the small look
- every `[overquality]` key, every `[vendor_recipes.*]`, `[content.*]` and rule module
  `enabled` -> true (a content drop set to `false` -> `"price"`)
- `[maps] progression` -> `"all"`, `corrupted_min_tier` -> 0
- `[rares] base_tiers` -> true, `weapons` / `armour` / `jewellery` -> `["all"]`,
  `min_ilvl.*` -> 68: every endgame rare shown
- `[leveling] unused_whites_min_tier` -> your `bases.min_tier`: white bases your build never
  uses stay hidden in maps (rf: wands, pure ES, ...)
- `modules.toml`: every `Show` block that is `false` -> `true` (FilterBlade's off rules: lower
  flask / strand / cluster / heist tiers, fractured items, ...), every `Hide` block that is
  `true` -> `false` (abyss / generic / cluster junk, heist t3, talismans, rare hide layer,
  contract / tome Hides ...; that gear then falls to the bottom gear Hide or a price).
  Kept as they are:
  - rares [[2600]] animated weapons (Show, off): would show every normal / magic weapon
  - jewels [2805] cluster eco tiers (Show, off): empty tiers, would highlight every enchant
  - crafting [2302] matrix (Show, off): every ilvl 83+ base
  - maps [3302] tier Hides (on): `progression = "all"` already shows each tier in its own
    style; off would give every map the generic look
  - leveling Hides (on: outdated campaign flasks): campaign preset, like `strictness`

Not touched: `[leveling]` campaign hides (`hide_normal_after`, `hide_magic_after`,
`strictness`). Only plain gear in maps stays hidden.

## Day 1-7: tighten

`python tools/league_start.py status` lists every value that still differs from the backup,
per table, `backup -> now`, with its line number. Tighten by editing that line back (or to
something in between), or put the backup value back with `restore KEY` (a table name restores
the whole table). Rebuild after each step. Typical order (`ls` = `python tools/league_start.py`):

| When | What | Command |
|---|---|---|
| day 1 | junk rares | `ls restore rares.min_ilvl rares.weapons rares.armour rares.jewellery rares.base_tiers` (or step `["t1","t2","t3"]` -> `["t1"]`) |
| day 1 | rare hide layer, junk jewels / heist gear | `ls restore rares.blocks jewels.blocks heist.blocks` |
| day 1-2 | dust tier | edit `hide_tiers = ["dust"]` |
| day 2 | small gold piles | `ls restore show_small_gold` (later `show_gold`) |
| day 2 | generic 5L / mirrored / overquality | `ls restore show_5_links show_mirrored overquality` |
| day 2 | ilvl 82+ junk bases | `ls restore bases.min_tier leveling.unused_whites_min_tier` |
| day 2-3 | low-tier uniques | `ls restore uniques.show` (or set `show.dust` / `show.brown` false first) |
| day 3 | wrist saver | `ls restore small_loot` |
| day 3 | cheap gems | `ls restore gems` |
| day 3 | cheap stackables NeverSink hides | `ls restore exchange.unpriced_tiers overrides exchange.reference_card_tiers` |
| day 3 | contracts, Forbidden Tome | `ls restore show_contracts hide_forbidden_tome maps.blocks` |
| day 4 | normal maps, low corrupted maps | `ls restore maps.progression maps.corrupted_min_tier` (or `"auto"` in between) |
| day 4 | vendor recipes you don't do | `ls restore vendor_recipes.chromatic vendor_recipes.jeweller` |
| day 4-5 | brown tier | `ls restore hide_tiers` |
| day 5 | module extras | `ls restore flasks.blocks exotics.blocks crafting.blocks gear_special.blocks` ... (one block: `ls restore "flasks.blocks.endgameflasks.anyutility"`) |
| day 5-7 | the rest | `ls status`, then `ls restore` single keys you don't want loose any more |

## End of the week

- `status` says "nothing differs": `python tools/league_start.py finish` deletes the backup.
- Back to your old files in one go: `python tools/league_start.py restore` (no key) puts both
  files back byte for byte and deletes the backup. It also drops any OTHER edit made since
  `start`, so prefer `restore KEY` / `finish` if you changed other settings meanwhile.
- You want to keep some loose values: `python tools/league_start.py finish --force`.

`league_start/` is in `.gitignore` (personal state). Only `start`, `restore` (no key) and
`finish` touch the backup.
