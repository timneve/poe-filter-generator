# Tiering: how every item gets its tier (READ BEFORE touching pricing / visibility)

Simple steps per item kind. Code names in `backticks`. Block order (which rule wins in game):
`ARCHITECTURE.md` emit table. Keep this file current with the code (AGENTS.md hard rule).

## 0. Tiers (everything points here)

- Tier = price as fraction of 1 divine (live poe.ninja rate): top 1, high 1/4, mid 1/16,
  minor 1/64, low 1/256, brown 1/1024, dust 0. `Tiers.of(chaos)`.
- Blue = `variable` / `unknown`: probably valuable, exact price unknown. Never hidden.
- `hide_tiers` -> hidden. `quiet_tiers` -> brown look. `variable_after` = blue's rank.
- **Jackpot** = `jackpot_divine` (13 div). Any item >= jackpot never hidden. A group the
  filter can't split (unique base, Foulborn base, 5L/6L base, crafting base ilvl range)
  with a jackpot inside -> blue.
- **Wrist saver** `[small_loot]`: non-stackables (uniques, Foulborn, `types`) below
  `min_tier` hidden. Jackpots / never_hide still show.
- `league_start = true` overrides many settings (list in config.toml top) = `league_start_values`;
  `tools/league_start.py start` writes the same values into the files (docs/LEAGUE_START.md).
- League start also turns module Hides off (except `LS_KEEP_HIDES`) and shows every rare
  (`[rares]` base tiers all, ilvl 68+), all gold (`show_small_gold`: small look kept).
- `[gems] show_all`: every gem shown (bottom.filter `Hide # gems.show_all` -> Show, no known-gem Hide).
- `[leveling] unused_whites_min_tier` (with `build`): white bases the build module hides stay hidden in
  maps unless priced at that tier (`unused_white_hides`, in `emit_crafting_bases`).

## 1. Normal uniques (`price_unique_bases`)

What counts on a base: uniques that can drop in maps.
- Out: boss / encounter / recipe / removed (`non_map_drops`, wiki), every `Replica` (Heist),
  disabled `[content.*]` module uniques. `[uniques.map_drop]` fixes the wiki per name.
- In: enabled `[content.*]` module uniques (priced like any unique).
- Price per unique = its CHEAPEST confident variant (`min_listings`). Vendor value floor
  (`[vendor_recipes.*]` with `uniques`) raises it.

### 1a. EV path (`[uniques.ev]` on AND base has drop-anywhere uniques)
1. EV = sum(drop chance x avg price) of drop-anywhere uniques. Chance = `tier_weights` of its
   `unique_tiers.toml` tier / uniques in that tier. Content / boss uniques NOT in EV.
2. EV tier off (`[uniques.show]`, small_loot) -> **hidden** (even with a jackpot unique in the pool!).
3. EV tier on, but cheapest unique's tier off -> **blue**.
4. Still hidden, but a non-pool unique (content) >= jackpot -> **blue**.
5. `unknown_as_variable` + unpriced chase unique (tier <= `unknown_chase_tier`) -> **blue**.

### 1b. Fallback path (EV off, or no drop-anywhere uniques on the base)
1. `base_price`: "lowest" = cheapest unique, "highest" = priciest unique -> tier.
2. Best variant (any listing) >= jackpot and tier not top -> **blue**.
3. Tier off -> **hidden**.
4. Hidden but best >= never_hide floor -> **blue** (`variable_jackpot_only` = true: floor = jackpot,
   else `never_hide_tier`).
5. `unknown_as_variable` + any unique on base without confident price -> **blue**.

### 1c. After both paths
- Base with only boss-only uniques (none enabled) -> **blue**.
- `always_show_bases` hidden -> **blue**.
- `[unique_overrides]` base = tier, last word.
- No price at all -> `[uniques] unpriced`.

### 1d. Extra show rules (blocks in `emit_uniques`)
- `variable_classes` (Jewels...) -> **blue** unless top.
- `price_linked_jackpots`: 5L/6L unique base with a linked variant >= jackpot -> **blue** (`LinkedSockets`).
- `[corrupted_implicits]`: unique with corrupted implicit in listed classes/bases -> shown (style).
- **Unique exceptions** (module `unique_exceptions`, `emit_unique_exceptions`, after the shown price
  tiers, before the hidden ones): variants a base price can't see -> shown in league.filter's style
  even on a hidden base: influenced Impresence / Forge swords, Kaom's Heart (`Sockets < 1`), Tabula
  6L, synthesised, 2-4 abyss sockets, `Vestigial`, unique idols, double corrupted, crucible,
  21%+ quality (ours; league.filter 27%; `[overquality] uniques_21`). A base priced in a shown tier keeps its price style (block comes later). Shows only.
- Unique maps: `hide_maps` -> NeverSink [3201] rules, else priced like uniques.
- **Faded content rescue** (`valuable_content_bases`): base hidden by price, enabled module,
  module's uniques priced -> if that price is a shown tier -> **faded** (`[style.content]`).
  Code today: takes the PRICIEST module unique (= "highest"), ignores `base_price`.
  Not for Foulborn: they come from Wombgifts only, never content drops; `[foulborn]` price decides.
- `[content.<mod>.drops]` per unique: "price" default, true = always faded show, false = base hidden.

## 2. Foulborn uniques (`price_foulborn_bases`)

Filter sees only `Foulborn True` + base. No EV (no drop rates).
1. Per unique: listings summed over variants >= `[foulborn] min_listings` = confident.
2. Base price = CHEAPEST variant of any confident Foulborn unique (code ignores `base_price`).
3. Best variant >= `[foulborn] jackpot_divine` (own, lower than the top-level one: Wombgift-only
   drops) and not top -> **blue**. Never-hide floor in 5 uses this jackpot too.
4. Below `[foulborn] min_tier` / small_loot -> **hidden**.
5. Hidden but best >= never_hide floor -> **blue**. `unknown_as_variable` + thin unique -> **blue**.
6. Only boss-only Foulborn uniques on base -> hidden. No price -> `[foulborn] unpriced`.
7. No faded content rescue (Wombgift-only, never content drops).
Foulborn only ever takes its own price: normal unique tier blocks carry `Foulborn False` (else a hidden
5c Foulborn Cutlass fell into the shown normal Cutlass tier, 780c United in Dream -> red), and the
Foulborn catch-all (`[foulborn] unpriced`) sits before the hidden normal tiers.

## 3. Stackables: currency, fragments, scarabs, essences, ... (`price_stackables`, `emit_stackables`)
1. Divine / Mirror / Hinekora's Lock -> **top**, fixed (`PINNED_TOP_STACKABLES`).
2. poe.ninja exchange price, volume >= `[exchange] min_volume`. Thin price: only used to SHOW.
3. Stack blocks: N x price tiered up to `max_stack` (splinters: up to conversion count;
   `[exchange.big_stacks]` per name: lifeforce / Dead Man's Sulphur / Rogue's Marker up to 1250-12500).
4. Splinters `[exchange.splinters]` = finished item / count.
5. No price: `[exchange.unpriced_tiers]` fixed (Scroll Fragment, Amber / Verdant Oil hidden), else
   `unpriced_currency` ("reference" = NeverSink tier number from `fallback_tiers.toml [currency]`
   via `[exchange.reference_currency_tiers]`, else blue). Reference tier hidden: stack >=
   `[exchange.reference_currency_stacks]` (t5 x5, t6 x14) shown in `fallback_stack_tier` (`fallback_stacks`).
6. `[overrides]` beat price (not pinned three).
7. Campaign (`[leveling] show_all_stackables`): nothing hidden.

## 4. Divination cards
1. Card quotes never set price (no buy/sell side).
2. `[exchange.card_rewards]`: price = reward price x qty / set size.
3. Else exchange volume < `card_fallback_min_volume` -> NeverSink group (`fallback_tiers.toml
   [cards]`) via `[exchange.reference_card_tiers]`. Else **blue** (silent).
4. Fallback group hidden: stack >= `card_fallback_stack` (3) shown in `fallback_stack_tier`.
   Priced (card_rewards) cards: price x stack decides (user decision: a confident cheap 3-stack stays
   hidden although league.filter's exstack shows any 3 cards).
5. Unpriced low-volume cards in NeverSink groups t4 / t4c / t5 / t5c -> hidden (`reference_card_tiers`):
   NeverSink ranks them cheap, so not "maybe valuable" (the user's league.filter shows t4 / t4c).

## 5. Gems (`price_gems`)
1. Every poe.ninja variant (level / quality / corrupted) priced; capped by a confident better variant.
2. >= `[gems] min_tier` -> its tier. Below -> hidden (bottom.filter), except top.filter Awakened / 20%.
3. Thin listings -> **blue**. Level 21+ / quality 21+ without confident price -> **blue**.
4. Transfigured gems -> **blue**.
5. Gem poe.ninja doesn't list at all (new exceptional supports: Item Quantity / Transfusion) -> **blue**
   (`emit_unknown_gems`, last gem rule); listed gems no rule showed -> hidden there.
6. Cheap level 18-20 gems: price decides (user decision; league.filter lt2 / lt3 show every one).

## 6. Crafting bases (`price_crafting_bases`)
1. Per exact base + influence + ilvl range. Needs `min_listings` AND `min_samples`.
2. Each price covers only its own ilvl range.
3. Below `[bases] min_tier` -> not shown by price. Jackpot inside group -> **blue**.
4. Shown-tier / blue entries also copied before the gear modules (`emit_priced_bases_first`): price
   style beats gear_special / crafting Shows, not id_mods / flasks / perfection / exotics (section 9).

## 7. Cluster jewels (`price_clusters`)
Per base + passives + ilvl bucket + enchant node; unknown enchant -> **blue**. Emitted before leveling;
the rest by module `jewels` [2805] eco tiers / [2806] random (`[jewels]`, after rares).

## 8. Vendor recipes (`[vendor_recipes.*]`)
Ingredient shown at recipe `tier` = FLOOR: worth more keeps its own tier, cheaper / hidden gets recipe tier.
`uniques` recipes: vendor value floors unique prices (section 1).

## 9. Copied NeverSink rules (no poe.ninja price)
Flasks `[flasks]` (module `flasks`), identified good mods `[id_mods]`, exotic gear `[exotics]`
(module `exotics`: strands, exotic mods, exotic classes, relics, corruptions, abyss sockets,
fractured, enchanted, crucible) - all before recipes / bases / stackables / uniques / rares:
never hidden by them. Exotics vs uniques: only normal / magic / rare decided by the module,
uniques keep their price (`EXOTIC_NOT_UNIQUE` adds `Rarity <= Rare` to imbued / fishing rods;
relics are Normal-Rare in league.filter). Exception: unique Harbinger pieces (`Rarity Unique`,
no poe.ninja price) shown as league.filter. Rare relics / trinkets shown (FilterBlade default).
Gear special `[gear_special]` (module `gear_special`: [0302] influenced rares, [[0400]] eldritch,
[[0500]] exotic bases after exotics; [0901] perfection + `[overquality]` (own option, also with
the module off; 30% = top tink style, first in [0901]: beats the ilvl 83+ perfection blocks) after id_mods, before exotics / recipes) and crafting
`[crafting]` (module `crafting`: [1401] 5-links after exotics; [2301] early crafting, [2302]
matrix, [[2400]] chancing after the rare gear tiers, before the hide layer): Shows only. Price vs
module: `emit_priced_bases_first` puts the crafting-base Shows (confident price at a shown
`[bases]` tier, jackpot -> blue) after id_mods / flasks / perfection / exotics (an identified
good-mod / fractured / strand / perfect item keeps that look: more info than base price) but
before gear_special / crafting, so a priced base keeps its price tier over those. Bases priced below `min_tier` are not decided by price (no base Hide
exists, league.filter's [1500] economy bases only Show too), so the module Show applies. Uniques
never match (blocks Normal-Rare; [0901] + `Rarity <= Rare`). Recipes stay `[vendor_recipes.*]`:
[1401] / [2601] RGB = `chromatic`, 6 sockets = `jeweller`, [[0500]] breach-ring entries =
`grasping_mail` (no module block); Stacked Deck = stackable price.
Maps `[maps]` (module `maps`: special maps always, `progression`, `corrupted_min_tier`).
Campaign `[leveling]` (module `leveling`, `AreaLevel <= area_level_max` only, gear `Rarity <= Rare`:
never a unique; after recipes / cluster prices, before stackables / uniques / bases, so campaign
Shows beat price Hides): build module + `[leveling]` hides first, then [2802] jewels, [[3800]]
currency styles (visibility stays `campaign_unhide` + price), [[5000]] outdated
flask Hides, [[5100]]-[[5405]] flasks / rares / normal + magic gear. Most keys follow `strictness`
(NeverSink tag: `%D<n>` Show while < n, `%H<n>` Hide from n, magic blockers Hide from 3, untagged
Hides Show); [[3800]] too, but price first (`leveling_price_shown` / `leveling_price_first`: names a
price rule shows dropped, `StackSize < n` below the stack reaching a shown tier; pinned / overrides
count); options: quicksilver / utility alerts true (as before), decorators / spirit shields false;
league_start turns options on, not strictness keys. [5406] / [5407] = `rules/bottom.filter`.
Map items (module `maps` [[3400]] / [[3500]], after stackables, before uniques): price decides first
where poe.ninja has one; reliquary keys (`Vault Keys`) are always top (`always_top_classes`, section 3);
unpriced `Map Fragments` / `Misc Map Items` (Chronicle of Atzoatl, Inscribed Ultimatum) hit the
stackable unpriced fallback (blue) first, so their module blocks only act if that fallback changes.
Unpriced others keep league.filter's look: unique / enchanted
contracts + blueprints, logbooks, charts shown; plain contracts (`heist->contract.handpicked`) and
Sanctum Research (Forbidden Tome) hidden as FilterBlade. Explicit config toggles beat these
module defaults both ways: `show_contracts` = false / `hide_forbidden_tome` = true hide before
everything; `show_contracts` = true / `hide_forbidden_tome` = false skip those module Hides
(`MAP_ITEM_CONFIG_OVERRIDES`): all contracts / tomes shown. None of these is a poe.ninja category, so no
jackpot can sit behind those Hides.
Jewels `[jewels]` (module `jewels`, after rares): [2801] corrupted-implicit / top-mod jewels shown,
[2803] abyss (corrupted rare, ilvl 83+ / 86+ shown, rest hidden), [2804] other rare / magic jewels
hidden; priced clusters / jewel bases, ID-mod and fractured jewels decided earlier.
Heist gear `[heist]` (module `heist`, after jewels): top / good bases shown, rest hidden; priced
crafting bases decided earlier.
Rares `rares.*` (module `rares`): after crafting bases, before jewels / heist (league.filter order).
[[1700]] decorators (Continue: size 45, `rares.text_color`, ilvl 68+ rares), talisman t1 shown / t2-t3
hidden, [[1800]] veiled rares + [[1900]] breach rings shown, [[2000]] Hides (corrupted / mirrored
unID rares without implicit, FilterBlade entry `s2000_1`: rares ilvl < 83 two-handers / bows /
staves / body armours), [[2200]] droplevel Hides (off), base-tier Shows (`rares.base_tiers` +
group tier lists, after the [[2000]] Hides like FilterBlade), [[2600]] animated-weapon Shows (off,
league_start keeps them off (`LS_KEEP_SECTIONS`): every normal / magic weapon), [[2700]] hide layer (normal / magic
gear in maps, rares 68+). Every Hide there comes after recipes, id_mods, exotics, flasks, uniques
(rarity Unique never matched), cluster prices and the crafting-base Shows (priced / jackpot
`variable` bases), so no priced, jackpot or blue item reaches them; jewels / heist classes aren't
in their `Class` lists. `s2602_1` (FilterBlade corrupted-unique Show) off: `[corrupted_implicits]`
does it inside `emit_uniques`. Leveling `[leveling]`.
Gold (`emit_gold`, first): `show_gold` false = all hidden; true = in maps (`AreaLevel >= 68`) stacks
>= `gold_min_stack` shown (module `misc` gold.stack3 look), smaller hidden; campaign gold shown small;
`show_small_gold` (LS on): no small-gold Hide, smaller stacks keep the small look. Module gold.* keys are config-driven (one source of truth). Misc `[misc]`
(module `misc`): heist targets, enshrouded gear, magic / rare / normal
idols: Shows after special maps, before uniques (league.filter "override uniques": a unique-rarity
heist target / enshrouded item keeps this look; none is a poe.ninja category, Shows hide no
jackpot). Maven's invitations, lab / incursion items ([4900]): after uniques; stackable prices
(Maven's chisels / writ) and the unpriced Map Fragments / Misc Map Items blue fallback decide
first, so `questlike.invitations` only acts on unpriced non-fragment "Maven's" items. [0100]
6L overrides (`6l.*`): `show_6_links` (top.filter, superset) instead.

## 10. Hand rules / toggles
`rules/top.filter` (5L/6L, mirrored, quest items, Awakened / 20% gems), `rules/bottom.filter` (hide gear,
blue safety net), `[overquality]`, `hide_forbidden_tome`, `show_contracts`, `show_gold` / `gold_min_stack`,
`always_top_classes`, `[exchange.show_stacks]`, `[overrides]`.

## 11. Parity with the FilterBlade filter (`tests/test_parity.py`)
Every item `reference/league.filter` shows (cache items + one item per Show block / BaseType /
rarity) is shown by ours, or hidden for a reason in `EXPLAINED` / `price_reason` / `reason_for`:
confident poe.ninja price in a hidden tier, or a listed decision (config toggles, NeverSink fallback
groups ranked cheap, card 3-stacks and level 18-20 gems left to price). New gap = fix or add a reason.

## Known gaps vs user's intended logic (fix = ask user first)
- EV path step 2: hidden EV tier hides even a pool jackpot (Headhunter on Leather Belt).
  User rule: jackpot -> blue first.
- Foulborn base price always cheapest, ignores `base_price`.
- Faded content rescue (normal uniques only) uses priciest module unique, ignores `base_price`.
