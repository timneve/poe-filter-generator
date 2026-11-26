# Tiering: how every item gets its tier (READ BEFORE touching pricing / visibility)

Simple steps per item kind. Code names in `backticks`. Block order (which rule wins in game):
`ARCHITECTURE.md` emit table. Keep this file current with the code (AGENTS.md hard rule).

## 0. Tiers (everything points here)

- Tier = price as fraction of 1 divine (live poe.ninja rate): top 1, high 1/4, mid 1/16,
  minor 1/64, low 1/256, brown 1/1024, dust 0. `Tiers.of(chaos)`.
- Blue = `variable` / `unknown`: probably valuable, exact price unknown. Never hidden.
- `hide_tiers` -> hidden. `quiet_tiers` -> brown look (`quiet_icon = false`: no minimap icon). `variable_after` = blue's rank.
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
- `[gems] hide_level1`: plain lvl 1 / 0% / uncorrupted non-exceptional gems hidden (`emit_level1_gem_hide`, wins over show_all).
- `[leveling] unused_whites_min_tier` (with `build`): white bases the build module hides stay hidden in
  maps unless priced at that tier (`unused_white_hides`, in `emit_crafting_bases`).

## 1. Normal uniques (`price_unique_bases`)

What counts on a base: uniques that can drop in maps.
- Out: boss / encounter / recipe / removed (`non_map_drops`, wiki), every `Replica` (Heist),
  disabled `[content.*]` module uniques. `[uniques.map_drop]` fixes the wiki per name.
- In: enabled `[content.*]` module uniques (priced like any unique).
- Price per unique = its CHEAPEST confident variant (`min_listings`). Vendor value floor
  (`[vendor_recipes.*]` with `uniques`) raises it.

- Two floors (`never_hidden`): a confident price tier >= `[uniques] never_hide_tier` (unique
  bases, Foulborn, Viscera) is never hidden by show.* / min_tier / small_loot. A variable group
  (cheap base, pricey roll) is rescued to blue only at `jackpot_divine`.

### 1a. EV path (`[uniques.ev]` on AND base has drop-anywhere uniques)
1. EV = sum(drop chance x avg price) of drop-anywhere uniques. Chance = `tier_weights` of its
   `unique_tiers.toml` tier / uniques in that tier. Content / boss uniques NOT in EV.
2. EV tier off (`[uniques.show]`, small_loot) -> **hidden**.
3. EV tier on, but cheapest unique's tier off -> **blue**.
4. Still hidden, but any unique on the base (pool or content, any listing) >= `jackpot_divine`
   -> **blue** (variable group). Imperial Staff: EV ~2c (Agnerods), Jiquani's 2 div < jackpot -> hidden.
5. `unknown_as_variable` + unpriced chase unique (tier <= `unknown_chase_tier`) -> **blue**.

### 1b. Fallback path (EV off, or no drop-anywhere uniques on the base)
1. `base_price`: "lowest" = cheapest unique, "highest" = priciest unique -> tier.
2. Best variant (any listing) >= jackpot -> `jackpot_tier`: top, or a shown tier ranked above
   blue (high / mid), keeps its tier; anything else -> **blue** (never downgraded or hidden).
3. Tier off -> **hidden**.
4. Hidden but best >= `jackpot_divine` -> **blue**.
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
   drops) -> `jackpot_tier` (as 1b.2: top / shown high / mid kept, else **blue**). Never-hide floor in 5 uses this jackpot too.
4. Below `[foulborn] min_tier` / small_loot -> **hidden**.
5. Hidden but best >= `jackpot_divine` -> **blue**. `unknown_as_variable` + thin unique -> **blue**.
6. Boss-only (wiki restricted) Foulborn uniques count for cheapest, never best; base with only those -> hidden.
   Exception: any content-module unique (Severed in Sleep, Breach boss) is priced normally, module
   on OR off (filter sees `Foulborn True`; Wombgift-only), so its jackpot variant -> blue. No price -> `[foulborn] unpriced`.
7. No faded content rescue (Wombgift-only, never content drops).
Foulborn only ever takes its own price: normal unique tier blocks carry `Foulborn False` (else a hidden
5c Foulborn Cutlass fell into the shown normal Cutlass tier, 780c United in Dream -> red), and the
Foulborn catch-all (`[foulborn] unpriced`) sits before the hidden normal tiers.

## 2b. Viscera (`price_viscera_bases`, `[viscera]`, 3.28 league class)

Filter sees only `Class "Viscera"` + BaseType: not the implicit (one poe.ninja line each) nor the
Greater / Lesser name prefix (`viscera_base` strips it: same BaseType). Like Foulborn:
1. Base price = cheapest line with listings >= `[viscera] min_listings`.
2. Best line (any listing) >= top-level `jackpot_divine` -> `jackpot_tier` (top / shown high / mid kept, else **blue**).
3. Below `min_tier` (or `[small_loot]` with "Viscera" in `types`) -> **hidden**; hidden but best >= `jackpot_divine` -> **blue**.
4. `unknown_as_variable` + a thin-listed line on the base -> **blue** instead of a quieter / hidden tier;
   base with only thin lines -> **blue**.
5. Base poe.ninja doesn't list -> `[league_mechanic] classes` blue + Moon. Moon icon for all.

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
6. `[overrides]` beat price (not pinned three). `[content.breach.wombgifts]` non-"price" entries join `[overrides]` (`apply_wombgift_choices`; "hide" beats Ancient's minor floor).
7. Campaign (`[leveling] show_all_stackables`): nothing hidden.

## 4. Divination cards
1. `[exchange.card_rewards]`: price = reward price x qty / set size (beats the card quote).
2. Else exchange volume >= `card_fallback_min_volume` -> poe.ninja card quote is the price
   (user decision 2026-11-16: active ~1c cards showed blue before).
3. Else NeverSink group (`fallback_tiers.toml [cards]`) via `[exchange.reference_card_tiers]`.
   Not on poe.ninja and no group -> **blue** (silent).
4. Fallback group hidden: stack >= `card_fallback_stack` (3) shown in `fallback_stack_tier`.
   Priced cards (quote or card_rewards): price x stack decides (user decision: a confident cheap 3-stack stays
   hidden although league.filter's exstack shows any 3 cards).
5. Unpriced low-volume cards in NeverSink groups t4 / t4c / t5 / t5c -> hidden (`reference_card_tiers`):
   NeverSink ranks them cheap, so not "maybe valuable" (the user's league.filter shows t4 / t4c).

## 5. Gems (`price_gems`)
1. Every poe.ninja variant (level / quality / corrupted) priced; capped by a confident better variant.
2. >= `[gems] min_tier` -> its tier. Below -> hidden (bottom.filter), except top.filter Awakened / 20%.
3. Thin listings -> **blue**, except plain, uncorrupted level 1-19 / 0-quality vendor gems, which
   are hidden as worthless when thin-listed or at poe.ninja's 1c floor (`NINJA_FLOOR_CHAOS`;
   ~600 plain level 1 gems sit there, vendor sells them; even with min_tier dust). Level 21+ / quality 21+ without confident price -> **blue**.
4. Transfigured gems -> **blue**.
5. Gem poe.ninja doesn't list at all (new exceptional supports: Item Quantity / Transfusion) -> **blue**
   (`emit_unknown_gems`, last gem rule); listed gems no rule showed -> hidden there.
6. Cheap level 18-20 gems: price decides (user decision; league.filter lt2 / lt3 show every one).
7. `[gems] hide_level1`: `plain_level1_gem` (not `exceptional_gem`: ninja gemKind, `EXCEPTIONAL_GEMS`, Awakened)
   never priced; `emit_level1_gem_hide` (before `emit_unknown_gems`, after campaign) hides the known names.
   Except `never_hide_gem` (plain lvl 1 line confidently >= `[uniques] never_hide_tier`, e.g. Elemental Penetration 250c): priced, never hidden.
8. Imbued gems (poe.ninja ImbuedGem, Standard only): can't drop, never fetched (`SKIPPED_TYPES`).

## 6. Crafting bases (`price_crafting_bases`)
1. Per exact base + influence + ilvl range. Needs `min_listings` AND `min_samples`.
   Price <= `dump_floor` chaos (ninja 1-2c bulk-dump floor) = unpriced: gear modules decide.
2. Each price covers only its own ilvl range.
3. Below `[bases] min_tier` -> not shown by price. Jackpot inside group -> **blue**.
4. Shown-tier / blue entries also copied before the gear modules (`emit_priced_bases_first`): price
   style beats gear_special / crafting Shows, not id_mods / flasks / perfection / exotics (section 9).

## 7. Cluster jewels (`price_clusters`)
Per base + passives + ilvl bucket + enchant node; unknown enchant -> **blue**. Emitted before leveling;
the rest by module `jewels` [2805] eco tiers / [2806] random (`[jewels]`, after rares).

## 8. Vendor recipes (`[vendor_recipes.*]`)
Ingredient shown at recipe `tier` = FLOOR: worth more keeps its own tier, cheaper / hidden gets recipe tier.
`tier = "price"` (`recipe_levels`): recipe tier = reward stackable price x `reward_count` per
ingredient; quality recipes: x quality / `per_quality` (one item >= `full_quality` = full reward),
one `Quality >= N` block per reached tier. Value in a hidden tier -> lowest shown tier:
an enabled recipe shows everything its `conds` accept (gems / flasks `Quality >= 1`); two rules disagree -> lower threshold wins.
`min_tier` (default config: `"low"`): price tier never quieter than that (a 1% gem = low); min_tier in a config-hidden tier (Standard) -> still Show, quiet look (grey beam + icon).
No confident reward price -> reward's NeverSink fallback tier threshold; none -> blue variable.
`uniques` recipes: vendor value floors unique prices (section 1).

## 9. Copied NeverSink rules (no poe.ninja price)
Flasks `[flasks]` (module `flasks`), identified good mods `[id_mods]`, exotic gear `[exotics]`
(module `exotics`: strands, exotic mods, exotic classes, relics, corruptions, abyss sockets,
fractured, enchanted, crucible) - all before recipes / bases / stackables / uniques / rares:
never hidden by them. Exotics vs uniques: only normal / magic / rare decided by the module,
uniques keep their price (`EXOTIC_NOT_UNIQUE` adds `Rarity <= Rare` to imbued / fishing rods;
relics are Normal-Rare in league.filter). Exception: unique Harbinger pieces (`Rarity Unique`,
no poe.ninja price) shown as league.filter. Rare relics / trinkets shown (FilterBlade default).
Anointed amulets (ours, not NeverSink): every `Amulets` base, no BaseType list, talismans too
(so module `rares` `talisman.t1`-`t3` never decide: exotics first);
corrupted / mirrored ones via own block `anointedamuletscorrupted` (default on).
Talismans (`[content.bestiary] talismans`, `price_talismans` / `emit_talismans`): every talisman drops
anointed, so before the anointed-amulet blocks (inside `emit_exotics`) a confident poe.ninja base
price (min_listings + min_samples; NO min_tier, NO dump_floor: 1c with hundreds of listings = 1c)
decides: its tier, hidden tier or below `[content.bestiary] talisman_min_tier` -> Hide. Ilvl ranges like crafting bases; a price ranked below
`variable` also covers lower ilvls down to the next confident one, thin / unlisted ones too (ceiling:
blue would claim more). Thin higher ilvl / lower ilvl under a price above blue -> anointed blue. Off: every talisman anointed blue.
Gear special `[gear_special]` (module `gear_special`: [0302] influenced rares (what shows = config.toml
`[influenced]`: rank A/B/C bases any influence, per-influence bases ilvl 82+ / classes ilvl 80+,
remaining ilvl 86+ / any; `influenced_driven`; first `hide_cheap` Hides: influenced base + ilvl confidently priced
(`[bases]` min_listings + min_samples) <= `[bases] dump_floor` = known junk, hidden, not blue
(`cheap_influenced_bases` / `cheap_influenced_hides`; guards keep enabled `[links]` / chromatic / jeweller items out)), [[0400]] eldritch,
[[0500]] exotic bases after exotics; [0901] perfection (bases = `[gear_special] perfection_armour` NeverSink rare base tiers, default t1) + `[overquality]` (own option, also with
the module off; 30% = top tink style, first in [0901]: beats the ilvl 83+ perfection blocks) after id_mods, before exotics / recipes) and links /
chancing `[links]` / `[chancing]` (module `crafting`: [1401] 5-links after exotics; [2301] 4-link armour,
[[2400]] chancing after the rare gear tiers, before the hide layer; FilterBlade's crafting base lists = price only): Shows only. Price vs
module: `emit_priced_bases_first` puts the crafting-base Shows (confident price at a shown
`[bases]` tier, jackpot -> blue) after id_mods / flasks / perfection / exotics (an identified
good-mod / fractured / strand / perfect item keeps that look: more info than base price) but
before gear_special / crafting, so a priced base keeps its price tier over those. Flasks: only the mods / fractured / overquality flask blocks come before it; the plain flask
Shows (ilvl 82-85, low quality, any utility in maps) come right after, so a priced flask base
(Silver Flask ilvl 85) shows its price tier, cheaper ones the grey module look. `[flasks] show_plain`
false (default): no plain flask Shows, so a flask base is a crafting base: shown only at a
confident price at a shown tier, cheap (<= `dump_floor`) / unpriced fall to the later Hides
(campaign: leveling rules). Flask bases whose
Class no `[leveling]` unused-white Hide names skip the `unused_whites_min_tier` hold-back. Bases priced below `min_tier` are not decided by price (no base Hide
exists, league.filter's [1500] economy bases only Show too), so the module Show applies. Uniques
never match (blocks Normal-Rare; [0901] + `Rarity <= Rare`). Recipes stay `[vendor_recipes.*]`:
[1401] / [2601] RGB = `chromatic` (every area incl. campaign), 6 sockets = `jeweller`, [[0500]] breach-ring entries =
`grasping_mail` (no module block); Stacked Deck = stackable price.
Maps `[maps]` (module `maps`: special maps always, `progression` from `min_tier` up + `extra_tiers` (`quiet` -> quiet look), `corrupted_min_tier`, `blighted_hide_tiers` = blighted (not ravaged) tiers hidden before the blighted Shows).
Campaign `[leveling]` (module `leveling`, `AreaLevel <= area_level_max` only, gear `Rarity <= Rare`; gear-section blocks without Class / BaseType get `Class == GEAR_CLASSES` (NeverSink has them after currency; [5402] firstareas caught currency):
never a unique; after recipes / cluster prices, before stackables / uniques / bases, so campaign
Shows beat price Hides): build module (`rules/leveling/<build>.filter`: rf, minion = minion
wand / Bone Ring / minion spirit shield bases any rarity; the module's leading Shows (before its first Hide) go before the `[leveling]` extras so their sound / icon / beam win over e.g. `show_jewellery`, armour/ES hybrid (pure armour only below that slot's first armour/ES drop level), wands only) + `[leveling]` hides first (`show_3_links_until` / `show_4_links_until`: any 3L / 4L, any base / rarity, `link_classes` only (also build / module link Shows), before the magic hide and build module; `show_jewels`), then [2802] jewels, [[3800]]
currency styles (visibility stays `campaign_unhide` + price), [[5000]] outdated
flask Hides, [[5100]]-[[5405]] flasks / rares / normal + magic gear. Most keys follow `strictness`
(NeverSink tag: `%D<n>` Show while < n, `%H<n>` Hide from n, magic blockers Hide from 3, untagged
Hides Show); [[3800]] too, but price first (`leveling_price_shown` / `leveling_price_first`: names a
price rule shows dropped, `StackSize < n` below the stack reaching a shown tier; pinned / overrides
count); build-module Shows price first too (`campaign_price_first`: currency names as [[3800]],
`Rarity Unique` Shows drop `leveling_unique_bases`). "Shown tier" = `price_beats_campaign`: shown, not
quiet, rank <= `[leveling] price_over_tier` ("" = any shown): price wins only when higher. Every later price rule too (`campaign_price_over`: crafting bases, overrides, stackables incl. unpriced reference tiers, viscera, ...): its exact-BaseType Shows at such a tier get a campaign copy before leveling, so a higher tier beats leveling's Show / Hide (uniques: `leveling_unique_bases`; module blocks have no price tier); options: quicksilver / utility alerts true (as before), decorators / spirit shields false;
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
`show_small_gold` (LS on): no small-gold Hide, smaller stacks keep the small look. Module gold.* keys are config-driven (one source of truth). Every gold Show font `GOLD_FONT_SIZE` (18, smallest; `maximize_item_sizes` skips gold, PoE2 sets it) + `GOLD_BACKGROUND` (`SetBackgroundColor 0 0 0 0`). Misc `[misc]`
(module `misc`): heist targets, enshrouded gear, magic / rare / normal
idols: Shows after special maps, before uniques (league.filter "override uniques": a unique-rarity
heist target / enshrouded item keeps this look; none is a poe.ninja category, Shows hide no
jackpot). Maven's invitations, lab / incursion items ([4900]): after uniques; stackable prices
(Maven's chisels / writ) and the unpriced Map Fragments / Misc Map Items blue fallback decide
first, so `questlike.invitations` only acts on unpriced non-fragment "Maven's" items. [0100]
6L overrides (`6l.*`): `show_6_links` (top.filter, superset; normal / magic / rare like [0100], high style red, not tink) instead. 6L / 5L uniques skip it: unique rules (price, `uniques.extabula` red for Tabula Rasa, `uniques.ex6link`, `uniques.5link`).

## 9b. New league content / unidentified tier (3.28)
- Threads (core game since 3.28, `Map Fragments`): poe.ninja exchange `Thread` feed, priced as stackables (Hexagon);
  not in `[league_mechanic] fragments` (default []): price alone decides, dust / hidden ones hide.
- `[league_mechanic]`: new names / classes without confident price or NeverSink fallback tier ->
  `tier` (blue) + Moon (`fragments`: Hexagon), never hidden (`emit_league_mechanic`, before the stackable class fallbacks).
Itemised beasts (menagerie: `Stackable Currency`, magic / rare, BaseType = beast species; poe.ninja `Beast` skipped):
unpriced, `[content.bestiary] quiet_beasts` -> `[style.quiet]` look, no sound (explicit user choice over blue);
unique spirit beasts -> blue currency fallback.
  `icon_floor`: priced / reference-tier `names` in a tier without beam + icon (brown = beam only, dust, hidden,
  small_loot) -> Show in the quiet look (grey beam + icon) instead (`floored` in `emit_stackables`).
  `Fated True` -> same look (rare gear only in `fated_tiers.<group>` rr base tiers, rest = normal rare) before every Hide except top.filter / gems / recipes / id mods / exotics
  (`emit_fated`): a Fated unique shows blue, not its price tier.
- `rare_base_blocks` (Fated / `[unid_tier]` / `[memory_strands]`): one block per rr tier, groups wanting the same tier share it (NeverSink's generic `rr.tN` lists mix weapon + armour bases; `rr.t1` has no weapons), "all" = one any-base block per group.
- `[unid_tier]` (like `[rares]` base tiers / Fated, `rare_base_blocks` shared with Fated): rare / magic unID
  gear + jewellery on the `weapons` / `armour` / `jewellery` rr base tiers ("t1".."t5", "all") with
  `UnidentifiedItemTier >= min_tier.<rarity>` (0-5, 0 = not tiered), maps only, price tier `tier` style.
  Shows only, after id_mods and priced-base copies, before recipes / rares. LS: groups ["all"], min_tier 2.

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
- `[memory_strands]` (NeverSink [0902] as config, `rare_base_blocks` like `[unid_tier]`): MemoryStrands >= `min_strands` on the listed rr base tiers, >= `any_base_min_strands` on any base, 1+ when fractured / veiled; right after `emit_unid_tiers`.
- EV path step 2: hidden EV tier hides even a pool jackpot (Headhunter on Leather Belt).
  User rule: jackpot -> blue first.
- Foulborn base price always cheapest, ignores `base_price`.
- Faded content rescue (normal uniques only) uses priciest module unique, ignores `base_price`.
