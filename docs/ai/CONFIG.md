# config.toml map (PoE1)

Key -> effect -> code reader. Full comments live in `config.toml`; grep the key there before editing.
Tier-name values accept: `top high mid minor low brown dust` + often `variable`, `unknown`, `hide`.
`league_start = true` overrides many keys at load (`apply_league_start`), noted as LS.

## Top level

| Key | Effect | Reader |
|---|---|---|
| `tiers.<name> = {div, chaos}` | thresholds; `div` = fraction of divine | `split_tiers`, `apply_divine_tiers`, `Tiers` |
| `tiers_follow_divine` | use `div` (min 1c) vs fixed `chaos` | `apply_divine_tiers` |
| `hide_tiers` | priced but hidden (LS: none) | `hidden` |
| `quiet_tiers` | `[style.quiet]` look, keep font size | `style_for` |
| `jackpot_divine` | never hide items >= this; groups -> variable | `jackpot_chaos` |
| `league`, `output_name`, `output_dirs`, `cache_minutes` | IO | `detect_league`, `main`, `fetch_all` |
| `hide_forbidden_tome` | hide it regardless | `emit_forbidden_tome` |
| `show_5_links`, `show_6_links`, `show_mirrored` | toggle `# BEGIN/END` sections in `rules/top.filter` | `hand_rules` |
| `league_start` | show almost everything | `apply_league_start`, `hand_rules`, `league_start_unused_whites` |
| `gear_text_color`, `campaign_white_text_color` | gear text colour | `emit_defaults` |
| `unknown_as_variable` | base with any unpriced wiki unique -> blue | `price_unique_bases` |

## Sections

| Section | Keys | Reader |
|---|---|---|
| `[exchange]` | `min_volume`, `card_fallback_min_volume`, `max_stack`, `unpriced_currency` ("reference"/tier/"hide"/"unknown") | `price_stackables`, `emit_stackables` |
| `[exchange.splinters]` | `"Shard" = ["Finished item", count]` price = finished/count | `price_stackables` |
| `[exchange.card_rewards]` | `"Card" = ["Reward", reward_count, set_size]` exact deterministic rewards only | `price_stackables` |
| `[exchange.reference_currency_tiers]` | NeverSink tier number -> our tier | `reference_currency_tiers` |
| `[exchange.reference_card_tiers]` | NeverSink card group (t1, t2, ...) -> our tier | `reference_card_tiers` |
| `[uniques]` | `never_hide_tier`, `variable_jackpot_only` (LS false), `min_listings`, `include_replicas`, `min_tier` (LS lowest), `unpriced`, `hide_maps` (LS false), `always_show_bases`, `skip_non_map_drops`, `wiki_cache_days`, `map_sources` | `price_unique_bases`, `emit_uniques`, `non_map_drops` |
| `[uniques.ev]` | `enabled`, `tier_weights {"0".."5"}`, `default_tier`, `unknown_chase_tier` | `unique_drop_weights`, `price_unique_bases` |
| `[uniques.map_drop]` | `"Unique" = true/false` force map-drop status | `non_map_drops` |
| `[content.<mod>]` | `enabled` (LS true), `sources` (wiki drop-source substrings) | `content_bases`, `content_policy` |
| `[content.<mod>.drops]` | `"Unique" = "price" / true (show) / false (hide)`; base-wide; unknown name -> ValueError | `content_policy`, `emit_content_overrides` |
| `[foulborn]` | `min_listings`, `min_tier` (LS lowest), `unpriced` | `price_foulborn_bases` |
| `[small_loot]` | wrist saver: `enabled` (LS false), `min_tier`, `types` | `small_loot`, `emit_stackables`, unique emit |
| `[overquality]` | `quality_30/27/21` | `emit_overquality` |
| `[leveling]` | `enabled`, `strictness` 0-4, `area_level_max`, `build`, `hide_normal_after`, `hide_magic_after`, `keep_build_weapons_magic`, `show_jewellery`, `show_gems`, `show_magic_vendor`, `show_rare_vendor`, `show_magic_rare_cells`, `league_start_hide_unused`, `show_all_stackables`, `icon_sound` | `emit_leveling`, `campaign_unhide`, `emit_defaults` |
| `[report]` | `review_tier` | `report.write` |
| `[bases]` | `enabled`, `min_tier` (LS lowest), `min_listings`, `min_samples`, `include_dual_influence` | `price_crafting_bases`, `emit_crafting_bases` |
| `[overrides]` | `"BaseType" = tier/"hide"/"variable"/"unknown"`; wins over prices, not over pinned | `emit_overrides`, `emit_stackables` |
| `[corrupted_implicits]` | `style`, `classes`, `bases`: rescue hidden uniques with corrupted implicit | `emit_corrupted_uniques` |
| `[unique_overrides]` | `"Base" = tier`, applied last | `price_unique_bases` |
| `[style.<tier>]` | `lines = [raw filter lines]`; tiers + `quiet`, `content`, `variable`, `unknown` | `style_for` |

## Other data files

- `unique_tiers.toml`: top-level keys `0 = [names]` .. `5 = [names]` (0 = rarest). Hand-copied from poewiki. Loaded into `cfg["unique_tiers"]`.
- `config_poe2.toml`: `league`, `output_*`, `cache_minutes`, `tiers_follow_divine`, `hide_tiers`, `quiet_tiers`, `[tiers]`, `[exchange] types/min_volume/max_stack`, `[gear] hide_normal_magic_after_area/classes`.
