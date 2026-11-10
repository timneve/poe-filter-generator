"""Safety tests: the filter must never hide something valuable or maybe-valuable after ID.

Run:  python -m unittest discover tests        (from the poe-filter-generator folder)

Two kinds of tests:
  Synthetic   - small fake poe.ninja data, checks the pricing rules themselves.
  Live cache  - builds the real filter from cache/<league>/ and replays every priced
                item through it with filtersim.py. Skipped when there is no cache.
"""
import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter as bf  # noqa: E402
import filtersim as fs  # noqa: E402
from report import NINJA_CLASS, STACK_CLASS, browser_rules, unique_class, unique_ev, vendor_recipes  # noqa: E402

# Safety line: no unique worth this many divines may sit on a hidden base. Fixed here on
# purpose, so raising config never_hide_tier fails the tests instead of shrinking them.
SAFETY_DIVINE = 1
# EnchantmentPassiveNode names verified outside NeverSink's reference (which skips them), each
# with source. Only add after checking the real in-game name: a wrong name never matches.
# Source: RePoE https://repoe-fork.github.io/cluster_jewels.json "name" field (checked 2026-11-04);
# it matches every name NeverSink does use (e.g. Burning -> "Fire Damage over Time").
VERIFIED_CLUSTER_NODES = {
    # Large
    "Attack Damage",
    # Medium
    "Cold Damage over Time", "Damage over Time", "Effect of Non-Damaging Ailments",
    "Life and Mana recovery from Flasks", "Physical Damage over Time", "Totem Damage",
    # Small (Curse Effect also Medium)
    "Chance to Block Attack Damage", "Chance to Block Spell Damage", "Chance to Suppress Spell Damage",
    "Cold Resistance", "Curse Effect", "Energy Shield", "Evasion", "Fire Resistance", "Life",
    "Lightning Resistance",
}


# ------------------------------------------------------------------ synthetic data

# Chaos thresholds most Synthetic tests assume (config tiers are divine fractions).
FIXED_TIERS = {"top": 125, "high": 25, "mid": 5, "minor": 2, "low": 1, "brown": 0.25, "dust": 0}


def empty_data(divine=400):
    ex = {t: {"core": {"primary": "chaos", "rates": {"divine": 1 / divine}}, "items": [], "lines": []}
          for t in bf.EXCHANGE_TYPES}
    st = {t: {"lines": []} for t in bf.STASH_TYPES}
    return {"exchange": ex, "stash": st}


def add_exchange(data, t, name, chaos, volume=1000):
    i = name.lower().replace(" ", "-")
    data["exchange"][t]["items"].append({"id": i, "name": name})
    data["exchange"][t]["lines"].append({"id": i, "primaryValue": chaos, "volumePrimaryValue": volume})


def add_unique(data, base, name, chaos, listings=100, item_type="Belt", t="UniqueAccessory"):
    data["stash"][t]["lines"].append({"name": name, "baseType": base, "chaosValue": chaos,
                                      "listingCount": listings, "itemType": item_type})


def unid_unique(base, cls, foulborn=False):
    return {"rarity": "Unique", "basetype": base, "class": cls, "ilvl": 84, "foulborn": foulborn}


def add_foulborn(data, base, name, variant, chaos, listings=20, item_type="Belt", t="UniqueAccessory"):
    data["stash"][t]["lines"].append({"name": "Foulborn " + name, "baseType": base, "variant": variant,
                                      "chaosValue": chaos, "listingCount": listings, "itemType": item_type})


def tink_lines(cfg):
    """Lines that make a block tink: top tier's background + alert sound (palette applied)."""
    top = max(cfg["tiers"], key=cfg["tiers"].get)
    style = fs.parse(bf.apply_palette(cfg, bf.block("Show", [], bf.style_for(cfg, top))))[0].style
    return [l for l in style if l.startswith(("SetBackgroundColor", "PlayAlertSound"))]


def not_tink(blocks, cfg, items):
    """[(label, block)] of the items whose deciding block is not tink."""
    need = tink_lines(cfg)
    out = []
    for label, it in items:
        b, style = fs.evaluate(blocks, it)
        if b is None or b.action != "Show" or any(l not in style for l in need):
            out.append((label, b))
    return out


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(bf.load_cfg())
        self.cfg["tiers_follow_divine"] = False  # fixed chaos tiers: the numbers below assume them
        self.cfg["tiers"] = dict(FIXED_TIERS)
        self.cfg["uniques"]["ev"]["enabled"] = False  # cheapest-unique rules; EV has its own tests
        self.cfg["uniques"]["variable_jackpot_only"] = False
        self.cfg["uniques"]["always_show_bases"] = []
        self.cfg["content"]["ultimatum"]["drops"] = {}
        self.cfg["content"]["ultimatum"]["enabled"] = True  # content tests use ultimatum (config may turn it off)
        self.cfg["content"]["blight"]["drops"] = {}
        self.cfg["content"]["breach"]["drops"] = {}
        self.data = empty_data()

    def build(self):
        text, r = bf.build_text(self.cfg, self.data, "Test")
        return fs.parse(text), r

    def test_report_serializes_filter_conditions(self):
        blocks = fs.parse('Show # first\n\tRarity Unique\n\tContinue\nHide # base tier\n\tBaseType == "Shagreen Boots"\n')
        rules = browser_rules(blocks)
        self.assertEqual(rules[0]["action"], "Show")
        self.assertTrue(rules[0]["continue"])
        self.assertEqual(rules[0]["conditions"][0]["values"], ["Unique"])
        self.assertEqual(rules[1]["conditions"][0]["values"], ["Shagreen Boots"])

    def test_unique_maps_square_icon(self):
        # unique map = map icon (Square), also module blocks (corrupted, restex)
        blocks, _ = self.build()
        for corrupted in (False, True):
            item = {"rarity": "Unique", "class": "Maps", "basetype": "Map (Tier 16)",
                    "corrupted": corrupted, "map_tier": 16, "ilvl": 83}
            b, style = fs.evaluate(blocks, item)
            if b is None or b.action == "Hide":
                continue
            icons = [l for l in style if l.startswith("MinimapIcon")]
            self.assertTrue(icons and icons[-1].endswith("Square"), (corrupted, icons))

    def test_transfigured_gem_name_not_emitted(self):
        # "Cyclone of Tumult" is no BaseType: the game rejects the whole filter
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Cyclone of Tumult", "gemLevel": 1, "chaosValue": 5000, "listingCount": 50,
             "metadata": {"gemKind": "transfigured"},
             "tradeFilter": {"query": {"type": {"option": "Cyclone", "discriminator": "alt_x"}}}},
            {"name": "Heavy Strike of Trarthus", "gemLevel": 1, "chaosValue": 5000, "listingCount": 50,
             "metadata": {"gemKind": "trarthus"},
             "tradeFilter": {"query": {"type": {"option": "Heavy Strike", "discriminator": "alt_y"}}}},
            {"name": "Faster Casting Support", "gemLevel": 1, "chaosValue": 5000, "listingCount": 50}]}
        text, _ = bf.build_text(self.cfg, self.data, "Test")
        self.assertNotIn('"Cyclone of Tumult"', text)
        self.assertNotIn('"Heavy Strike of Trarthus"', text)
        self.assertIn('"Faster Casting Support"', text)
        cyclone = {"class": "Skill Gems", "basetype": "Cyclone", "transfigured": True}
        self.assertTrue(fs.visible(fs.parse(text), cyclone))

    def test_gem_variants_priced_like_neversink(self):
        # level / quality / corrupted variants each priced (NeverSink: GemLevel / Quality rules);
        # a priced 20/20 gem keeps its tier over the cyan 20% rule and the gemcutter recipe floor
        self.cfg["vendor_recipes"]["gemcutter"]["enabled"] = True
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Holy Flame Totem", "gemLevel": 1, "chaosValue": 1.5, "listingCount": 50},
            {"name": "Holy Flame Totem", "gemLevel": 20, "gemQuality": 20, "chaosValue": 200, "listingCount": 50},
            {"name": "Holy Flame Totem", "gemLevel": 21, "gemQuality": 23, "corrupted": True,
             "chaosValue": 6, "listingCount": 50},
            {"name": "Holy Flame Totem", "gemLevel": 20, "chaosValue": 900, "listingCount": 2}]}
        blocks, _ = self.build()
        gem = {"class": "Skill Gems", "basetype": "Holy Flame Totem"}
        # thin 20/0 price: shown blue, not trusted for its tier
        self.assertIn("gem variable 20 ", fs.evaluate(blocks, dict(gem, gem_level=20))[0].comment)
        self.assertIn("gem top 20/20", fs.evaluate(blocks, dict(gem, gem_level=20, quality=20))[0].comment)
        self.assertIn("gem mid 21/23c", fs.evaluate(blocks, dict(gem, gem_level=21, quality=23, corrupted=True))[0].comment)
        self.assertFalse(fs.visible(blocks, dict(gem, gem_level=1)))  # 1.5c: wrist saver
        # 20/20 price never reaches a corrupted 20/20
        self.assertNotIn("gem top", fs.evaluate(blocks, dict(gem, gem_level=20, quality=20, corrupted=True))[0].comment)

    def test_gem_price_capped_by_better_variant(self):
        # poe.ninja "20" Spectral Helix at 1 div (price-fix listings) vs 9c for 20/20: a worse
        # variant is never worth more than a confident better one
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Spectral Helix", "gemLevel": 20, "chaosValue": 424.7, "listingCount": 14},
            {"name": "Spectral Helix", "gemLevel": 20, "gemQuality": 20, "chaosValue": 1, "listingCount": 11},
            {"name": "Spectral Helix", "gemLevel": 21, "corrupted": True, "chaosValue": 424.7, "listingCount": 3},
            {"name": "Spectral Helix", "gemLevel": 21, "gemQuality": 20, "corrupted": True,
             "chaosValue": 1, "listingCount": 50}]}
        blocks, _ = self.build()
        gem = {"class": "Skill Gems", "basetype": "Spectral Helix"}
        self.assertFalse(fs.visible(blocks, dict(gem, gem_level=20)))
        # thin 21c capped by confident cheap 21/20c: hidden, not blue
        self.assertFalse(fs.visible(blocks, dict(gem, gem_level=21, corrupted=True)))

    def test_cheap_gem_hidden_by_small_loot(self):
        # 1.5c Manaforged Arrows (low tier): gems don't stack -> wrist saver (minor 2c) hides it
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Manaforged Arrows Support", "gemLevel": 1, "chaosValue": 1.5, "listingCount": 50}]}
        gem = {"class": "Support Gems", "basetype": "Manaforged Arrows Support"}
        self.cfg["gems"]["min_tier"] = "low"
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gem))
        self.cfg["small_loot"]["enabled"] = False
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, gem))

    def test_gems_below_min_tier_hidden(self):
        # 3c level 1 Pulverise (minor) below [gems] min_tier mid: no price block, hidden
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Pulverise Support", "gemLevel": 1, "chaosValue": 3, "listingCount": 50}]}
        gem = {"class": "Support Gems", "basetype": "Pulverise Support", "gem_level": 1}
        self.cfg["gems"]["min_tier"] = "mid"
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gem))
        self.cfg["gems"]["min_tier"] = "minor"
        blocks, _ = self.build()
        self.assertIn("gem minor 1", fs.evaluate(blocks, gem)[0].comment)

    def test_gem_blue_fallback(self):
        # probably valuable, no exact price -> blue: thin listings (any price), unlisted 21 /
        # 23% variants. A confident price in a hidden tier still hides its exact variant.
        self.cfg["gems"]["min_tier"] = "mid"
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Pulverise Support", "gemLevel": 21, "corrupted": True, "chaosValue": 3, "listingCount": 4},
            {"name": "Arc", "gemLevel": 21, "corrupted": True, "chaosValue": 3, "listingCount": 50}]}
        blocks, _ = self.build()
        gem = {"class": "Support Gems", "basetype": "Pulverise Support", "corrupted": True}
        variable = lambda item: "variable" in fs.evaluate(blocks, item)[0].comment
        self.assertTrue(variable(dict(gem, gem_level=21)))  # thin 3c: blue, not hidden
        self.assertTrue(fs.visible(blocks, dict(gem, gem_level=20, quality=23)))  # unlisted 20/23c: top's 20% Show
        self.assertTrue(variable(dict(gem, basetype="Fireball", gem_level=21)))  # no price at all
        arc = {"class": "Skill Gems", "basetype": "Arc", "corrupted": True, "gem_level": 21}
        self.assertFalse(fs.visible(blocks, arc))  # confident 3c < mid: explicit hide
        self.assertTrue(variable(dict(arc, gem_level=22)))  # other variant: no price -> blue
        self.cfg["hide_tiers"].append("variable")
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, dict(gem, gem_level=21)))

    def test_report_vendor_recipes(self):
        for rec in self.cfg["vendor_recipes"].values():
            rec["enabled"] = True
        for name, chaos in [("Chromatic Orb", 1), ("Jeweller's Orb", 0.5), ("Gemcutter's Prism", 8),
                            ("Glassblower's Bauble", 2)]:  # tier = "price" recipes: all shown
            add_exchange(self.data, "Currency", name, chaos)
        blocks, _ = self.build()
        recipe = next(v for v in vendor_recipes(self.cfg, blocks) if v["key"] == "grasping_mail")
        self.assertTrue(recipe["on"])
        self.assertEqual(recipe["name"], "Grasping Mail")
        self.assertEqual(len(recipe["items"]), 20)  # 5 breach rings x normal / magic / rare / unique
        self.assertEqual({i["how"] for i in recipe["items"]}, {"normal", "magic", "rare", "unique"})
        self.assertTrue(all(i["shown"] and "vendor recipe" in i["rule"] for i in recipe["items"]))
        # conds recipes (no bases): one example item per listed rarity, built from the conditions
        for key, n in [("chromatic", 3), ("jeweller", 3), ("gemcutter", 4), ("glassblower", 1)]:
            recipe = next(v for v in vendor_recipes(self.cfg, blocks) if v["key"] == key)
            self.assertEqual(len(recipe["items"]), n, key)
            self.assertTrue(all(i["shown"] and f"vendor recipe: {key}" in i["rule"] for i in recipe["items"]), key)

        self.cfg["vendor_recipes"]["grasping_mail"]["enabled"] = False
        blocks, _ = self.build()
        recipe = next(v for v in vendor_recipes(self.cfg, blocks) if v["key"] == "grasping_mail")
        self.assertFalse(recipe["on"])
        self.assertFalse(any("vendor recipe" in i["rule"] for i in recipe["items"]))

    def test_forbidden_tome_visibility_toggle(self):
        tome = {"class": "Misc Map Items", "basetype": "Forbidden Tome"}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, tome))

        self.cfg["hide_forbidden_tome"] = False
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, tome))
        # real class: false beats module maps' Sanctum Research Hides (on by default)
        real = {"class": "Sanctum Research", "basetype": "Forbidden Tome", "ilvl": 83}
        self.assertTrue(self.cfg["modules"]["maps"]["blocks"]["exoticmap->sanctum.ilvl83"])
        self.assertTrue(fs.visible(blocks, real))
        self.assertTrue(fs.visible(blocks, dict(real, ilvl=70)))
        self.cfg["hide_forbidden_tome"] = True
        self.assertFalse(fs.visible(self.build()[0], real))

    def test_contracts_visibility_toggle(self):
        contract = {"class": "Contracts", "basetype": "Contract: Bunker", "rarity": "Magic"}
        self.cfg["show_contracts"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, contract))
        self.assertFalse(fs.visible(blocks, dict(contract, rarity="Unique")))
        self.assertTrue(fs.visible(blocks, {"class": "Quest Items", "basetype": "Contract: Bunker"}))

        # true: every contract shown; the toggle beats module maps' "heist->contract.handpicked" Hide
        self.cfg["show_contracts"] = True
        self.assertTrue(self.cfg["modules"]["maps"]["blocks"]["heist->contract.handpicked"])
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, contract))
        self.assertTrue(fs.visible(blocks, dict(contract, enchanted=True)))
        self.assertTrue(fs.visible(blocks, dict(contract, rarity="Unique")))

    def test_tiers_follow_divine(self):
        self.cfg["tiers_follow_divine"] = True
        self.cfg["tiers_divine"] = {"top": 1, "high": 0.25, "mid": 0.0625}
        add_exchange(self.data, "Currency", "Half Div", 200)
        add_exchange(self.data, "Currency", "Thirty", 30)
        _, r = self.build()
        self.assertEqual([(n, v) for n, v in r["tiers"].list][:4],
                         [("top", 400), ("high", 100), ("mid", 25), ("minor", 2)])
        self.assertEqual(r["tiers"].of(r["prices"]["Divine Orb"][0]), "top")
        self.assertEqual(r["tiers"].of(r["prices"]["Half Div"][0]), "high")
        self.assertEqual(r["tiers"].of(r["prices"]["Thirty"][0]), "mid")

    def test_divine_is_pinned_to_tink_below_top_threshold(self):
        self.cfg["tiers_follow_divine"] = True
        self.cfg["tiers_divine"]["top"] = 2  # divine itself prices below top
        self.cfg["overrides"]["Divine Orb"] = "hide"
        for exchange in self.data["exchange"].values():
            exchange["core"]["rates"]["divine"] = 1 / 409.668

        blocks, r = self.build()
        divine = {"class": "Stackable Currency", "basetype": "Divine Orb"}
        self.assertEqual(r["tiers"].of(r["prices"]["Divine Orb"][0]), "high")
        block, style = fs.evaluate(blocks, divine)
        self.assertEqual(block.comment, "pinned Divine Orb (always tink)")
        self.assertIn("SetBackgroundColor 255 255 255 255", style)

    def test_divine_is_pinned_even_without_market_rate(self):
        for exchange in self.data["exchange"].values():
            exchange["core"]["rates"].pop("divine")

        blocks, _ = self.build()
        block, _ = fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": "Divine Orb"})
        self.assertEqual(block.comment, "pinned Divine Orb (always tink)")

    def test_mirror_and_hinekora_lock_are_pinned_to_tink(self):
        names = ("Mirror of Kalandra", "Hinekora's Lock")
        for name in names:
            add_exchange(self.data, "Currency", name, 1)
            self.cfg["overrides"][name] = "hide"

        blocks, _ = self.build()
        for name in names:
            block, style = fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": name})
            self.assertEqual(block.comment, f"pinned {name} (always tink)")
            self.assertIn("SetBackgroundColor 255 255 255 255", style)

    def test_all_tiers_are_divine_fractions_without_chaos_floor(self):
        self.cfg["tiers_follow_divine"] = True
        for exchange in self.data["exchange"].values():
            exchange["core"]["rates"]["divine"] = 1 / 8
        _, r = self.build()
        self.assertEqual(r["divine"], 8)
        for name, frac in self.cfg["tiers_divine"].items():
            self.assertAlmostEqual(dict(r["tiers"].list)[name], frac * 8, places=2)
        self.assertEqual(r["tiers"].list[-1], ("dust", 0))  # dust = everything below brown

    def test_gold_hidden_unless_show_gold(self):
        gold = {"class": "Stackable Currency", "basetype": "Gold", "stack": 5000, "area_level": 20}
        self.cfg["show_gold"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gold))
        self.cfg["show_gold"] = True
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, gold))

    def test_chase_unique_on_cheap_base_not_hidden(self):
        # Leather Belt: cheapest unique 1c, Headhunter 12 div
        add_unique(self.data, "Leather Belt", "Cheap Belt", 1)
        add_unique(self.data, "Leather Belt", "Headhunter", 4800)
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))

    def test_base_price_lowest_or_highest(self):
        # Studded Belt: 1c junk + 40c unique (high tier), no jackpot
        add_unique(self.data, "Studded Belt", "Junk Belt", 1)
        add_unique(self.data, "Studded Belt", "Good Belt", 40)
        belt = unid_unique("Studded Belt", "Belts")
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Studded Belt"][0], "hide")
        self.assertFalse(fs.visible(blocks, belt))
        self.cfg["uniques"]["base_price"] = "highest"
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Studded Belt"][0], "high")
        self.assertTrue(fs.visible(blocks, belt))

    def test_base_price_highest_keeps_jackpot(self):
        # priciest confident 1c, thin-listed Headhunter still makes it variable
        self.cfg["uniques"]["base_price"] = "highest"
        add_unique(self.data, "Leather Belt", "Cheap Belt", 1)
        add_unique(self.data, "Leather Belt", "Headhunter", 4800, listings=2)
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))

    def test_chase_unique_with_few_listings_counts(self):
        add_unique(self.data, "Paua Amulet", "Cheap Amulet", 1)
        add_unique(self.data, "Paua Amulet", "Rare Chase", 1600, listings=2, item_type="Amulet")
        blocks, r = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Paua Amulet", "Amulets")))

    def test_jackpot_variant_counts(self):
        # Voices: 7 passives 1c (common), 1 passive 1500 div. Unidentified you can't tell.
        for variant, chaos in [("7 passives", 1), ("5 passives", 12), (None, 1500 * 400)]:
            self.data["stash"]["UniqueJewel"]["lines"].append(
                {"name": "Voices", "baseType": "Large Cluster Jewel", "variant": variant,
                 "chaosValue": chaos, "listingCount": 100, "itemType": "Cluster Jewel"})
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Large Cluster Jewel"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Large Cluster Jewel", "Jewels")))

    def test_linked_jackpot_on_junk_base_shown(self):
        add_unique(self.data, "Vile Staff", "Junk Staff", 1, item_type="Staff", t="UniqueWeapon")
        self.data["stash"]["UniqueWeapon"]["lines"].append(
            {"name": "Junk Staff", "baseType": "Vile Staff", "links": 5, "chaosValue": 50 * 400,
             "listingCount": 7, "itemType": "Staff"})
        blocks, _ = self.build()
        staff = unid_unique("Vile Staff", "Staves")
        self.assertFalse(fs.visible(blocks, staff))
        self.assertTrue(fs.visible(blocks, dict(staff, links=5)))
        self.assertTrue(fs.visible(blocks, dict(staff, links=6)))

    def test_generic_link_pickup_booleans_are_independent(self):
        rare_armour = {"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Rare"}
        self.cfg["show_5_links"] = False
        self.cfg["show_6_links"] = True
        blocks = fs.parse(bf.hand_rules(self.cfg, "top"))
        self.assertEqual(fs.evaluate(blocks, dict(rare_armour, links=6))[0].action, "Show")
        self.assertIsNone(fs.evaluate(blocks, dict(rare_armour, links=5))[0])

        self.cfg["show_5_links"] = True
        blocks = fs.parse(bf.hand_rules(self.cfg, "top"))
        self.assertEqual(fs.evaluate(blocks, dict(rare_armour, links=5))[0].action, "Show")

        self.cfg["show_6_links"] = False
        blocks = fs.parse(bf.hand_rules(self.cfg, "top"))
        self.assertIsNone(fs.evaluate(blocks, dict(rare_armour, links=6))[0])
        self.assertEqual(fs.evaluate(blocks, dict(rare_armour, links=5))[0].action, "Show")

    def test_currency_recipes_toggle(self):
        rgb = {"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Magic", "socket_group": "RGB",
               "sockets": 3, "width": 2, "height": 2}
        six = {"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Normal", "sockets": 6, "links": 2}
        gem = {"class": "Skill Gems", "basetype": "Fireball", "quality": 7}
        gem20 = dict(gem, quality=20)
        awakened = {"class": "Support Gems", "basetype": "Awakened Spell Echo Support", "quality": 3}
        flask = {"class": "Life Flasks", "basetype": "Divine Life Flask", "rarity": "Normal", "quality": 20}
        flask_low = dict(flask, quality=15)
        recipes = {"chromatic": rgb, "jeweller": six, "gemcutter": gem, "glassblower": flask}
        for key in recipes:
            self.cfg["vendor_recipes"][key]["enabled"] = True
        # tier = "price": 1c chrom, 7 x 0.5c jewellers, 7/40 x 8c prism, 20/40 x 2c bauble -> low
        for name, chaos in [("Chromatic Orb", 1), ("Jeweller's Orb", 0.5), ("Gemcutter's Prism", 8),
                            ("Glassblower's Bauble", 2)]:
            add_exchange(self.data, "Currency", name, chaos)
        blocks, _ = self.build()
        for key, item in recipes.items():
            block, style = fs.evaluate(blocks, item)
            self.assertEqual(block.comment, f"vendor recipe: {key}")
            self.assertTrue(any(l.startswith("MinimapIcon") and l.endswith("Diamond") for l in style), key)
        self.assertNotIn("recipe", fs.evaluate(blocks, gem20)[0].comment)  # own cyan 20% rule
        self.assertIn("MinimapIcon 1 Red Diamond", fs.evaluate(blocks, awakened)[1])
        self.assertEqual(fs.evaluate(blocks, flask_low)[0].comment, "vendor recipe: glassblower")  # brown share: lowest shown
        self.assertFalse(fs.visible(blocks, dict(flask, quality=0)))
        self.assertFalse(fs.visible(blocks, dict(rgb, socket_group="RGG")))
        for key in recipes:
            self.cfg["vendor_recipes"][key]["enabled"] = False
        blocks, _ = self.build()
        for key, item in recipes.items():
            self.assertFalse(fs.visible(blocks, item), key)

    def test_vendor_recipe_price_tiers(self):
        """tier = "price": recipe tier = reward value per ingredient (quality share for gems)."""
        gem = {"class": "Skill Gems", "basetype": "Fireball", "rarity": "Normal"}
        tier = lambda blocks, item: (lambda b: b.comment if b else None)(fs.evaluate(blocks, item)[0])
        add_exchange(self.data, "Currency", "Gemcutter's Prism", 40)  # 1% quality = 1c
        blocks, _ = self.build()
        text = bf.emit_vendor_recipes(self.cfg, bf.Tiers(self.cfg), {}, {}, [],
                                      {"Gemcutter's Prism": (40, "Currency")})
        self.assertIn("Quality >= 1", text)   # 1c low
        self.assertIn("Quality >= 2", text)   # 2c minor
        self.assertIn("Quality >= 5", text)   # 5c mid
        self.assertIn("Quality >= 20", text)  # one 20% gem = whole prism, 40c high
        for qual in (1, 4, 19):
            self.assertEqual(tier(blocks, dict(gem, quality=qual)), "vendor recipe: gemcutter", qual)
        style = lambda qual: fs.evaluate(blocks, dict(gem, quality=qual))[1]
        self.assertNotEqual(style(1), style(5))
        self.assertFalse(fs.visible(blocks, dict(gem, quality=0)))
        # cheap prism: shares in a hidden tier still show (lowest shown tier): the recipe accepts
        # Quality >= 1, lower threshold wins; Quality 0 not
        self.data = empty_data()
        add_exchange(self.data, "Currency", "Gemcutter's Prism", 0.4)
        blocks, _ = self.build()
        for qual in (1, 19):
            self.assertEqual(tier(blocks, dict(gem, quality=qual)), "vendor recipe: gemcutter", qual)
        self.assertEqual(style(1), style(19))  # one level: all in the lowest shown tier (low)
        self.assertEqual(sum("vendor recipe: gemcutter" == b.comment for b in blocks), 1)
        self.assertFalse(fs.visible(blocks, dict(gem, quality=0)))
        # chromatic: worthless orb -> no block; no price and no fallback tier -> blue
        rec = self.cfg["vendor_recipes"]["chromatic"]
        rec["enabled"] = True
        rgb = {"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Magic", "socket_group": "RGB",
               "sockets": 3, "width": 2, "height": 2, "area_level": 80}
        add_exchange(self.data, "Currency", "Chromatic Orb", 0.1)
        blocks, _ = self.build()
        self.assertEqual(tier(blocks, rgb), "vendor recipe: chromatic")  # cheap orb: still shown
        self.data = empty_data()
        self.cfg["fallback_tiers"]["currency"].pop("Chromatic Orb", None)
        blocks, _ = self.build()
        b, style = fs.evaluate(blocks, rgb)
        self.assertEqual(b.comment, "vendor recipe: chromatic")
        self.assertIn("PlayEffect Blue", style)
        rec["tier"] = "nope"
        self.assertRaises(ValueError, self.build)

    def test_vendor_recipe_floor_keeps_crafting_base_tier(self):
        # 6-socket Plate Vest: pricey ilvl 86 base keeps its top tier, cheap ilvl 84 one (hidden by
        # price) gets the jeweller recipe tier.
        for ilvl, chaos in [(84, 1), (86, 600)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": "Plate Vest", "levelRequired": ilvl, "chaosValue": chaos,
                 "listingCount": 69, "count": 10, "itemType": "Body Armour"})
        self.cfg["vendor_recipes"]["jeweller"]["enabled"] = True
        add_exchange(self.data, "Currency", "Jeweller's Orb", 0.5)  # 7 x 0.5c = low
        blocks, r = self.build()
        vest = {"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Normal", "sockets": 6}
        block, style = fs.evaluate(blocks, dict(vest, ilvl=86))
        # top tier first (emit_priced_bases_first copy, else the recipe floor block)
        self.assertIn("base top ilvl86+ plain", block.comment)
        self.assertIn("SetBackgroundColor 255 255 255 255", style)
        self.assertEqual(fs.evaluate(blocks, dict(vest, ilvl=84))[0].comment, "vendor recipe: jeweller")
        self.assertFalse(fs.visible(blocks, dict(vest, ilvl=84, sockets=4)))

    def test_crafting_base_jackpot_stays_variable(self):
        # A confident jackpot stays variable even when a higher ilvl is cheaper.
        for ilvl, chaos in [(86, 20 * 400), (87, 2)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": "Some Base", "variant": "Shaper", "levelRequired": ilvl, "chaosValue": chaos,
                 "listingCount": 50, "count": 10, "itemType": "Ring"})
        blocks, r = self.build()
        ring = {"class": "Rings", "basetype": "Some Base", "rarity": "Rare", "ilvl": 86, "influence": ["Shaper"]}
        self.assertTrue(fs.visible(blocks, ring))
        self.assertIn("variable", {e[0] for e in r["cbases"] if e[4] == "Some Base"})

    def test_confident_crafting_base_price_is_not_floored_by_higher_ilvl(self):
        for ilvl, chaos in [(84, 600), (85, 20)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": "Some Base", "variant": "Elder", "levelRequired": ilvl, "chaosValue": chaos,
                 "listingCount": 69, "count": 10, "itemType": "Ring"})
        blocks, r = self.build()
        ring = {"class": "Rings", "basetype": "Some Base", "rarity": "Rare", "ilvl": 84,
                "influence": ["Elder"]}
        self.assertEqual(fs.evaluate(blocks, ring)[0].action, "Show")
        self.assertIn(("top", 84, 84, "Elder", "Some Base", 600),
                      [e for e in r["cbases"] if e[4] == "Some Base"])

    def test_crafting_base_requires_minimum_sample_count(self):
        self.data["stash"]["BaseType"]["lines"].append(
            {"name": "Timber Axe", "variant": None, "levelRequired": 85, "chaosValue": 400,
             "listingCount": 38, "count": 3, "itemType": "Two Handed Axe"})
        blocks, r = self.build()
        self.assertFalse(any(e[4] == "Timber Axe" for e in r["cbases"]))
        axe = {"class": "Two Hand Axes", "basetype": "Timber Axe", "rarity": "Rare", "ilvl": 85}
        self.assertFalse(fs.visible(blocks, axe))

    def test_endgame_rares_by_neversink_base_tier(self):
        self.cfg["rares"] = {"enabled": True, "weapons": ["t1", "t2"], "armour": ["t1", "t2"],
                             "jewellery": ["t1", "t2"], "text_color": "test"}
        self.cfg["colors"]["test"] = "200 200 150 255"
        blocks, _ = self.build()
        _, style = fs.evaluate(blocks, {"class": "Helmets", "basetype": "Lich's Circlet", "rarity": "Rare", "ilvl": 84})
        self.assertIn("SetTextColor 200 200 150 255", style)
        for item, shown in [
            ({"class": "Helmets", "basetype": "Lich's Circlet", "rarity": "Rare"}, True),        # t1
            ({"class": "Boots", "basetype": "Fugitive Boots", "rarity": "Rare"}, True),          # t2
            ({"class": "Two Hand Axes", "basetype": "Vaal Axe", "rarity": "Rare"}, True),        # weapon t2
            ({"class": "Belts", "basetype": "Stygian Vise", "rarity": "Rare"}, True),            # belts t1
            ({"class": "Rings", "basetype": "Amethyst Ring", "rarity": "Rare"}, True),           # jewellery t1
            ({"class": "Boots", "basetype": "Ambush Boots", "rarity": "Rare"}, False),           # t3
            ({"class": "Helmets", "basetype": "Lich's Circlet", "rarity": "Magic"}, False),
            ({"class": "Helmets", "basetype": "Lich's Circlet", "rarity": "Rare", "ilvl": 60}, False),
        ]:
            self.assertEqual(fs.visible(blocks, {"ilvl": 84, **item}), shown, item)

    def test_endgame_rare_groups_and_class_toggles(self):
        helmet = {"class": "Helmets", "basetype": "Lich's Circlet", "rarity": "Rare", "ilvl": 84}
        boots = {"class": "Boots", "basetype": "Ambush Boots", "rarity": "Rare", "ilvl": 84}   # armour t3
        axe = {"class": "Two Hand Axes", "basetype": "Vaal Axe", "rarity": "Rare", "ilvl": 84}  # weapon t2
        ring = {"class": "Rings", "basetype": "Amethyst Ring", "rarity": "Rare", "ilvl": 84}
        jewel = {"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Rare", "ilvl": 84}
        self.cfg["rares"] = {"enabled": True, "weapons": [], "armour": ["all"], "jewellery": ["t1"],
                             "show": {"Helmets": False, "Boots": True}}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, helmet))   # class toggled off beats "all"
        self.assertTrue(fs.visible(blocks, boots))     # armour all
        self.assertFalse(fs.visible(blocks, axe))      # weapons []
        self.assertTrue(fs.visible(blocks, ring))
        self.assertFalse(fs.visible(blocks, jewel))
        self.cfg["rares"]["min_ilvl"] = {"armour": 80, "jewellery": 70}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, dict(boots, ilvl=79)))
        self.assertTrue(fs.visible(blocks, dict(boots, ilvl=80)))
        self.assertTrue(fs.visible(blocks, dict(ring, ilvl=70)))
        self.assertFalse(fs.visible(blocks, dict(ring, ilvl=69)))
        self.cfg["rares"]["show"] = {"Helmet": False}
        with self.assertRaises(ValueError):
            self.build()

    def test_rares_module_blocks(self):
        """Module rares ([[1700]]-[[2700]]): each block family on real-looking items, per-block
        toggles, league start (Shows only), base_tiers / enabled off."""
        self.cfg["rares"] = {"enabled": True, "base_tiers": False, "weapons": ["t1"], "armour": ["t1"],
                             "jewellery": ["t1"], "text_color": "rare"}
        self.cfg["vendor_recipes"]["grasping_mail"]["enabled"] = False   # recipe floor runs first
        rare = {"rarity": "Rare", "ilvl": 84, "width": 2, "height": 2}
        veiled = {**rare, "class": "Helmets", "basetype": "Lich's Circlet", "identified": True,
                  "mods": ["of the Veil"]}
        cases = [  # item, deciding module key (None = not this module), visible
            (veiled, "rare->exotic->veiled.t1", True),                                         # [[1800]]
            ({**veiled, "basetype": "Iron Hat"}, "rare->exotic->veiled.any", True),
            ({**rare, "class": "Rings", "basetype": "Cryonic Ring", "width": 1, "height": 1},
             "rare->exotic->breachrings.high", True),                                          # [[1900]]
            ({**rare, "class": "Amulets", "basetype": "Wolf Alpha Talisman", "enchanted": True},
             "rare->exotic->talisman.t1", True),                                               # [[1700]]
            ({**rare, "class": "Amulets", "basetype": "Ape Talisman", "enchanted": True},
             "rare->exotic->talisman.t2", False),
            ({**rare, "class": "Boots", "basetype": "Iron Greaves", "corrupted": True},
             "hidelayer.corruptedrares", False),                                               # [[2000]]
            ({**rare, "class": "Body Armours", "basetype": "Astral Plate", "ilvl": 82, "height": 3},
             "s2000_1", False),                                                                # FilterBlade entry
            ({**rare, "class": "Helmets", "basetype": "Iron Hat"}, "hidelayer.raresendgame", False),  # [[2700]]
            ({**rare, "class": "Helmets", "basetype": "Iron Hat", "rarity": "Magic"},
             "hidelayer.normalmagicendgame", False),
        ]
        blocks, _ = self.build()
        for item, key, shown in cases:
            b, style = fs.evaluate(blocks, item)
            self.assertIn(f"rare {key} ", b.comment + " ", item)
            self.assertEqual(fs.visible(blocks, item), shown, item)
        _, style = fs.evaluate(blocks, veiled)
        self.assertTrue(any("decorators->rareeg" in b.comment and b.cont for b in blocks))   # [[1700]] Continue
        self.assertIn("SetFontSize 45", style)
        deco = [b for b in blocks if "decorators->rareeg" in b.comment]
        self.assertTrue(deco and all("SetTextColor 235 220 105 255" in b.style for b in deco))  # rares.text_color
        self.assertFalse(any("255 255 155" in s for b in deco for s in b.style))           # not NeverSink yellow
        self.assertFalse(any("base tier" in b.comment for b in blocks))                      # base_tiers off
        sword = {"class": "One Hand Swords", "basetype": "Rusted Sword", "rarity": "Normal", "ilvl": 84}
        self.assertNotIn("animatedweapons", fs.evaluate(blocks, sword)[0].comment)          # [[2600]] off
        # per-block toggles: veiled t1 off -> falls to veiled.any; droplevel hide (off) turned on
        mods = self.cfg["modules"]["rares"]["blocks"]
        mods["rare->exotic->veiled.t1"] = False
        mods["hidelayer.rrihide4"] = True
        mods["animatedweapons.normalmelee"] = True
        blocks, _ = self.build()
        self.assertIn("animatedweapons.normalmelee", fs.evaluate(blocks, sword)[0].comment)
        self.assertTrue(fs.visible(blocks, sword))
        mods["animatedweapons.normalmelee"] = False
        self.assertIn("veiled.any", fs.evaluate(blocks, veiled)[0].comment)
        old = {**rare, "class": "Helmets", "basetype": "Iron Hat", "drop_level": 1, "area_level": 80}
        self.assertIn("hidelayer.rrihide4", fs.evaluate(blocks, old)[0].comment)
        # league start: off Shows on, on Hides off (off ones stay off), rr base tiers "all" from 68
        mods["hidelayer.rrihide4"] = False
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        self.assertTrue(any("rare->utility->droppeditems.any" in b.comment for b in blocks))
        self.assertFalse(any("rrihide" in b.comment or "idhider" in b.comment for b in blocks))
        self.assertFalse(any("animatedweapons" in b.comment for b in blocks))  # LS: every weapon otherwise
        self.assertFalse(any(k in b.comment for b in blocks for k in ("hidelayer.raresendgame", "s2000_1")))
        self.assertTrue(any(".t5" in b.comment and "rr" in b.comment for b in blocks))
        self.cfg["league_start"] = False
        # base tiers on: rr Shows come after the [[2000]] hides (FilterBlade order)
        self.cfg["rares"]["base_tiers"] = True
        blocks, _ = self.build()
        t1 = {**rare, "class": "Body Armours", "basetype": "Royal Plate", "height": 3}
        self.assertIn("rr.t1", fs.evaluate(blocks, t1)[0].comment)
        self.assertFalse(fs.visible(blocks, {**t1, "ilvl": 82}))                             # s2000_1 first
        self.cfg["rares"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(any("module rares" in b.comment for b in blocks))
        self.assertFalse(fs.visible(blocks, veiled))

    def test_rares_hides_never_hide_priced_bases(self):
        """A priced crafting base (and a jackpot one, variable) is decided before the rare Hides."""
        for name, chaos in [("Astral Plate", 600), ("Iron Hat", 1_000_000)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": name, "variant": None, "levelRequired": 82, "chaosValue": chaos,
                 "listingCount": 38, "count": 38, "itemType": "Body Armour"})
        blocks, _ = self.build()
        plate = {"class": "Body Armours", "basetype": "Astral Plate", "rarity": "Rare", "ilvl": 82}
        hat = {"class": "Helmets", "basetype": "Iron Hat", "rarity": "Rare", "ilvl": 84}
        for item in (plate, hat):                                  # s2000_1 / hide layer would hide them
            b, _ = fs.evaluate(blocks, item)
            self.assertTrue(fs.visible(blocks, item), item)
            self.assertNotIn("module rares", b.comment)

    def test_boss_only_unique_ignored(self):
        # Serpentine Staff: Cane of Kulemak drops from Catarina only, Sire of Shards is 1c
        self.data["nomap"] = bf.non_map_drops(
            [{"name": "Cane of Kulemak", "restricted": True, "enabled": True,
              "source": "Metadata/Monsters/LeagueBetrayal/BetrayalCatarina2 |  | "},
             {"name": "Voices", "restricted": True, "enabled": True,
              "source": " | AfflictionTown6 | "}], self.cfg)
        add_unique(self.data, "Serpentine Staff", "Sire of Shards", 1, item_type="Staff", t="UniqueWeapon")
        add_unique(self.data, "Serpentine Staff", "Cane of Kulemak", 6000, item_type="Staff", t="UniqueWeapon")
        add_unique(self.data, "Large Cluster Jewel", "Voices", 6000, item_type="Jewel", t="UniqueJewel")
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Serpentine Staff"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Serpentine Staff", "Staves")))
        self.assertIn("Large Cluster Jewel", r["ubases"])  # delirium drops in maps: counted
        self.assertNotEqual(r["ubases"]["Large Cluster Jewel"][0], "hide")

    def test_base_with_only_boss_uniques_shown(self):
        # Vermillion Ring: only Enmity's Embrace (memory boss) -> visible for boss farming
        self.data["nomap"] = {"Enmity's Embrace": "boss"}
        self.data["wiki_bases"] = {"Vermillion Ring": {"Enmity's Embrace"}}
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Vermillion Ring"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Vermillion Ring", "Rings")))

    def test_boss_unique_does_not_rescue_base_with_map_unique(self):
        self.data["nomap"] = {"Boss Unique": "boss"}
        self.data["wiki_bases"] = {
            "Vermillion Ring": {"Boss Unique", "Map Unique"},
        }
        add_unique(self.data, "Vermillion Ring", "Boss Unique", 5000, item_type="Ring")
        add_unique(self.data, "Vermillion Ring", "Map Unique", 1, item_type="Ring")
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Vermillion Ring"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Vermillion Ring", "Rings")))

    def test_replica_is_heist_only_even_without_wiki_flag(self):
        rows = [{"name": "Replica Dragonfang's Flight", "base": "Onyx Amulet", "restricted": False,
                 "enabled": True, "source": " |  | "}]
        self.assertIn("Replica Dragonfang's Flight", bf.non_map_drops(rows, self.cfg))
        self.cfg["uniques"]["map_drop"] = {"Replica Dragonfang's Flight": True}
        self.assertNotIn("Replica Dragonfang's Flight", bf.non_map_drops(rows, self.cfg))

    def test_content_unique_uses_ninja_price(self):
        # Module on: restricted drop uses its poe.ninja price; 1c junk -> hidden (not worth a faded show).
        rows = [{"name": "Ixchel's Temptation", "base": "Gold Ring", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Gold Ring", "Ixchel's Temptation", 1, item_type="Ring")
        ring = unid_unique("Gold Ring", "Rings")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {"Ixchel's Temptation": "content"}
        self.data["wiki_bases"] = {"Gold Ring": {"Ixchel's Temptation"}}

        self.assertFalse(fs.visible(self.build()[0], ring))
        self.data["stash"]["UniqueAccessory"]["lines"][0]["chaosValue"] = 100
        blocks, r = self.build()
        self.assertNotEqual(r["ubases"]["Gold Ring"][0], "hide")
        self.assertNotIn("SetFontSize 32", fs.evaluate(blocks, ring)[1])

    def test_blight_ravaged_unique_does_not_price_normal_map_base(self):
        name = "Stranglegasp"
        rows = [
            {"name": "Astramentis", "base": "Onyx Amulet", "restricted": False, "enabled": True, "source": ""},
            {"name": name, "base": "Onyx Amulet", "restricted": True, "enabled": True,
             "source": "Can drop after completing a Blight encounter in a Blight-ravaged map."},
        ]
        add_unique(self.data, "Onyx Amulet", "Astramentis", 1, item_type="Amulet")
        add_unique(self.data, "Onyx Amulet", name, 6000, item_type="Amulet")
        self.data["nomap"] = bf.non_map_drops(rows, self.cfg)
        self.data["wiki_bases"] = bf.wiki_unique_bases(rows)
        self.data["content"] = bf.content_bases(rows, self.cfg)
        amulet = unid_unique("Onyx Amulet", "Amulets")

        self.assertIn(name, self.data["nomap"])
        self.assertFalse(fs.visible(self.build()[0], amulet))

        self.cfg["content"]["blight"]["drops"] = {name: "price"}
        self.cfg["content"]["blight"]["enabled"] = True
        self.assertTrue(fs.visible(self.build()[0], amulet))

    def test_content_module_on_off(self):
        # Titan Greaves: 30c Kaom's Roots + 1c Breach-boss unique. Breach off -> Kaom's tier, on -> blue
        rows = [
            {"name": "Kaom's Roots", "base": "Titan Greaves", "restricted": False, "enabled": True, "source": ""},
            {"name": "The Infinite Pursuit", "base": "Titan Greaves", "restricted": True, "enabled": True,
             "source": "Metadata/Monsters/BreachBossHandMage/HandMage |  | "},
        ]
        add_unique(self.data, "Titan Greaves", "Kaom's Roots", 30, item_type="Boots", t="UniqueArmour")
        add_unique(self.data, "Titan Greaves", "The Infinite Pursuit", 1, item_type="Boots", t="UniqueArmour")
        self.data["nomap"] = bf.non_map_drops(rows, self.cfg)
        self.data["wiki_bases"] = bf.wiki_unique_bases(rows)
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.cfg["uniques"]["ev"]["enabled"] = True
        self.cfg["unique_tiers"] = {"Kaom's Roots": 3}
        self.data["drop_anywhere"] = {"Kaom's Roots"}
        self.cfg["uniques"]["show"] = dict.fromkeys(self.cfg["tiers"], False) | {"top": True, "high": True, "mid": True}
        self.cfg["tiers"]["mid"] = 25
        boots = unid_unique("Titan Greaves", "Boots")
        self.cfg["content"]["breach"]["enabled"] = False
        blocks, r = self.build()
        self.assertIn(r["ubases"]["Titan Greaves"][0], self.cfg["tiers"])
        self.assertTrue(fs.visible(blocks, boots))
        # on: priced normally, 1c Breach unique -> blue variable (price beats the faded style)
        self.cfg["content"]["breach"]["enabled"] = True
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Titan Greaves"][0], "variable")
        self.assertTrue(fs.visible(blocks, boots))
        self.assertNotIn("SetFontSize 32", fs.evaluate(blocks, boots)[1])
        # Kaom's junk -> base hidden by price; 1c Breach unique isn't worth a faded show
        self.data["stash"]["UniqueArmour"]["lines"][0]["chaosValue"] = 1
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Titan Greaves"][0], "hide")
        self.assertFalse(fs.visible(blocks, boots))
        # Breach unique in a shown tier (mid 50c): on -> faded, off -> hidden
        self.data["stash"]["UniqueArmour"]["lines"][1]["chaosValue"] = 50
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Titan Greaves"][0], "hide")
        self.assertIn("SetFontSize 32", fs.evaluate(blocks, boots)[1])
        self.cfg["content"]["breach"]["enabled"] = False
        self.assertFalse(fs.visible(self.build()[0], boots))

    def test_content_drop_can_be_forced_visible(self):
        name = "Ixchel's Temptation"
        rows = [{"name": name, "base": "Gold Ring", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Gold Ring", name, 1, item_type="Ring")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {name: "content"}
        self.data["wiki_bases"] = {"Gold Ring": {name}}
        self.cfg["content"]["ultimatum"]["drops"] = {name: True}
        self.cfg["overrides"]["Gold Ring"] = "hide"

        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Gold Ring", "Rings")))
        override = next(b for b in blocks if b.comment.startswith("content override show"))
        self.assertIn("SetFontSize 32", override.style)
        self.assertIn("SetBackgroundColor 0 0 0 193", override.style)

    def test_variable_classes(self):
        # unique jewels: junk / mid priced -> blue variable; a known tink base stays tink
        self.cfg["uniques"]["variable_classes"] = ["Jewels", "Abyss Jewels"]
        add_unique(self.data, "Cobalt Jewel", "Junk", 1, item_type="Jewel", t="UniqueJewel")
        add_unique(self.data, "Viridian Jewel", "Mid", 30, item_type="Jewel", t="UniqueJewel")
        add_unique(self.data, "Prismatic Jewel", "Tink", 100000, item_type="Jewel", t="UniqueJewel")
        blocks, _ = self.build()
        for base in ("Cobalt Jewel", "Viridian Jewel"):
            self.assertEqual(fs.evaluate(blocks, unid_unique(base, "Jewels"))[0].comment,
                             "uniques variable_classes", base)
        self.assertEqual(fs.evaluate(blocks, unid_unique("Murderous Eye Jewel", "Abyss Jewels"))[0].comment,
                         "uniques variable_classes")
        self.assertEqual(fs.evaluate(blocks, unid_unique("Prismatic Jewel", "Jewels"))[0].comment, "uniques top")
        self.cfg["uniques"]["variable_classes"] = []
        self.assertFalse(fs.visible(self.build()[0], unid_unique("Cobalt Jewel", "Jewels")))

    def test_no_map_unique_does_not_set_cheapest(self):
        # Ancient Gauntlets: Lab-only 10c Winds of Change must not drag 3000c Hateforge's base down
        rows = [
            {"name": "Hateforge", "base": "Ancient Gauntlets", "restricted": True, "enabled": True,
             "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "},
            {"name": "Winds of Change", "base": "Ancient Gauntlets", "restricted": True, "enabled": True,
             "source": " |  | This item can only drop in [[the Lord's Labyrinth]]."},
        ]
        add_unique(self.data, "Ancient Gauntlets", "Hateforge", 3000, item_type="Gloves", t="UniqueArmour")
        add_unique(self.data, "Ancient Gauntlets", "Winds of Change", 10, item_type="Gloves", t="UniqueArmour")
        self.data["nomap"] = bf.non_map_drops(rows, self.cfg)
        self.data["wiki_bases"] = bf.wiki_unique_bases(rows)
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.assertIn("Winds of Change", self.data["nomap"])
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Ancient Gauntlets"][1], 3000)
        self.assertEqual(r["ubases"]["Ancient Gauntlets"][0], "top")

    def test_content_force_show_keeps_price_tier(self):
        # Hateforge-like: true override, but its price already shows the base -> price style, not faded
        name = "Ixchel's Temptation"
        rows = [{"name": name, "base": "Gold Ring", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Gold Ring", name, 100000, item_type="Ring")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {name: "content"}
        self.data["wiki_bases"] = {"Gold Ring": {name}}
        self.cfg["content"]["ultimatum"]["drops"] = {name: True}
        blocks, r = self.build()
        self.assertFalse([b for b in blocks if b.comment.startswith("content override show")])
        self.assertNotIn("SetFontSize 32", fs.evaluate(blocks, unid_unique("Gold Ring", "Rings"))[1])

    def test_visible_items_use_maximum_font_size_outside_content_overrides(self):
        self.cfg["hide_tiers"] = []
        add_exchange(self.data, "Currency", "Dust Orb", 0.1)
        add_exchange(self.data, "Currency", "Brown Orb", 0.5)

        blocks, _ = self.build()
        for name in ("Dust Orb", "Brown Orb"):
            _, style = fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": name})
            self.assertIn("SetFontSize 45", style)
        for rule in blocks:
            sizes = [line for line in rule.style if line.startswith("SetFontSize")]
            if sizes and rule.action in ("Show", "Minimal"):
                expected = "SetFontSize 32" if rule.comment.startswith("content override show") else "SetFontSize 45"
                self.assertEqual(sizes, [expected], rule.comment)

    def test_content_drop_can_be_forced_hidden(self):
        name = "Ixchel's Temptation"
        rows = [{"name": name, "base": "Gold Ring", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Gold Ring", name, 1000, item_type="Ring")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {name: "content"}
        self.data["wiki_bases"] = {"Gold Ring": {name}}
        self.cfg["content"]["ultimatum"]["drops"] = {name: False}

        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, unid_unique("Gold Ring", "Rings")))

    def test_enabled_content_unique_shows_faded(self):
        # Shagreen Boots: 1c map unique + encounter-only Temptation Step. Module on: 50c (shown tier)
        # -> faded, though the 1c sibling hides the base by price; 1c -> hidden. Alone + pricey -> its tier.
        rows = [{"name": "Temptation Step", "base": "Shagreen Boots", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Shagreen Boots", "Temptation Step", 50, item_type="Boots", t="UniqueArmour")
        add_unique(self.data, "Shagreen Boots", "Junk", 1, item_type="Boots", t="UniqueArmour")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {"Temptation Step": "content"}
        self.data["wiki_bases"] = {"Shagreen Boots": {"Temptation Step", "Junk"}}
        item = unid_unique("Shagreen Boots", "Boots")

        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Shagreen Boots"][0], "hide")
        self.assertIn("SetFontSize 32", fs.evaluate(blocks, item)[1])
        self.cfg["content"]["ultimatum"]["enabled"] = False
        self.assertFalse(fs.visible(self.build()[0], item))
        self.cfg["content"]["ultimatum"]["enabled"] = True
        self.data["stash"]["UniqueArmour"]["lines"][0]["chaosValue"] = 1
        self.assertFalse(fs.visible(self.build()[0], item))
        self.data["stash"]["UniqueArmour"]["lines"].pop()
        self.data["wiki_bases"] = {"Shagreen Boots": {"Temptation Step"}}
        self.data["stash"]["UniqueArmour"]["lines"][0]["chaosValue"] = 100000
        _, r = self.build()
        self.assertEqual(r["ubases"]["Shagreen Boots"][0], "top")

    def test_enabled_content_foulborn_not_faded(self):
        # Foulborn uniques only come from Wombgifts, never from the content: a 30c Foulborn
        # Xoph's Blood does not rescue a Foulborn Amber Amulet its cheapest variant hides.
        rows = [{"name": n, "base": "Amber Amulet", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/Breach/BreachBoss |  | "} for n in ("Xoph's Heart", "Xoph's Blood")]
        self.cfg["small_loot"]["enabled"] = True
        add_foulborn(self.data, "Amber Amulet", "Xoph's Heart", "Debilitate", 0.5, item_type="Amulet")
        add_foulborn(self.data, "Amber Amulet", "Xoph's Blood", "Fire", 30, item_type="Amulet")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {"Xoph's Heart": "content", "Xoph's Blood": "content"}
        self.data["wiki_bases"] = {"Amber Amulet": {"Xoph's Heart", "Xoph's Blood"}}
        item = unid_unique("Amber Amulet", "Amulets", foulborn=True)

        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Amber Amulet"][0], "hide")
        self.assertFalse(fs.visible(blocks, item))
        self.assertNotIn("Foulborn uniques on otherwise hidden", blocks)

    def test_content_unique_is_not_unknown(self):
        # A disabled content module stays out of normal unknown-value handling.
        rows = [{"name": "Glimpse of Chaos", "base": "Vaal Mask", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Vaal Mask", "Junk A", 1, item_type="Helmet", t="UniqueArmour")
        add_unique(self.data, "Vaal Mask", "Glimpse of Chaos", 50, listings=2, item_type="Helmet", t="UniqueArmour")
        self.cfg["unknown_as_variable"] = True
        self.cfg["content"] = {"ultimatum": {"enabled": False, "sources": ["Ultimatum"]}}
        self.data["content"] = bf.content_bases(rows, self.cfg)
        _, r = self.build()
        self.assertEqual(r["ubases"]["Vaal Mask"][0], "hide")

    def test_all_cheap_base_hidden(self):
        # the point of the filter: a base with only junk uniques is hidden
        add_unique(self.data, "Heavy Belt", "Junk A", 1)
        add_unique(self.data, "Heavy Belt", "Junk B", self.cfg["tiers"][self.cfg["uniques"]["never_hide_tier"]] - 1)
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, unid_unique("Heavy Belt", "Belts")))

    def test_variable_jackpot_only(self):
        # Moonstone Ring: 1c junk + 200c unique. Default: variable. Late league toggle: hidden,
        # unless a jackpot is on the base. league_start turns the toggle back off.
        add_unique(self.data, "Moonstone Ring", "Junk A", 1, item_type="Ring")
        add_unique(self.data, "Moonstone Ring", "Mid Ring", 200, item_type="Ring")
        add_unique(self.data, "Leather Belt", "Cheap Belt", 1)
        add_unique(self.data, "Leather Belt", "Headhunter", 13 * 400)
        self.cfg["unknown_as_variable"] = False
        self.cfg["uniques"]["variable_jackpot_only"] = False
        _, r = self.build()
        self.assertEqual(r["ubases"]["Moonstone Ring"][0], "variable")
        self.cfg["uniques"]["variable_jackpot_only"] = True
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Moonstone Ring"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Moonstone Ring", "Rings")))
        self.assertEqual(r["ubases"]["Leather Belt"][0], "variable")
        self.cfg["league_start"] = True
        self.cfg = bf.apply_league_start(self.cfg)
        _, r = self.build()
        self.assertNotEqual(r["ubases"]["Moonstone Ring"][0], "hide")

    def test_unpriced_unique_base_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Brand New Base", "Rings")))

    def test_top_base_stays_tink(self):
        add_unique(self.data, "Gold Ring", "Pricey", 300, item_type="Ring")
        add_unique(self.data, "Gold Ring", "Pricier", 900000, item_type="Ring")
        _, r = self.build()
        self.assertEqual(r["ubases"]["Gold Ring"][0], "top")

    def test_overquality_tier_toggles(self):
        body_armour = {"class": "Body Armours", "basetype": "Simple Robe", "rarity": "Normal"}

        def decided_at(quality, **attrs):
            blocks, _ = self.build()
            b = fs.evaluate(blocks, dict(body_armour, quality=quality, **attrs))[0]
            b.comment = b.comment.split(" (module gear_special")[0]  # module gear_special [0901] block
            return b

        oq = self.cfg["overquality"]
        self.assertEqual((oq["quality_30"], oq["quality_27"], oq["quality_21"]), (True, False, False))
        self.assertEqual(decided_at(30).comment, "overquality 30%+")
        self.assertNotEqual(decided_at(30, rarity="Unique").comment, "overquality 30%+")  # unique: price
        # 30% = our top-tier tink style (style_for), incl. the border / background only tink has
        blocks, _ = self.build()
        _, style = fs.evaluate(blocks, dict(body_armour, quality=30))
        top_style = [l for l in fs.parse(bf.apply_palette(self.cfg, bf.block(
            "Show", [], bf.style_for(self.cfg, max(self.cfg["tiers"], key=self.cfg["tiers"].get)))))[0].style]
        self.assertEqual(style[-len(top_style):], top_style)
        self.assertTrue(any(l.startswith("SetBackgroundColor") for l in top_style))
        # 30% beats the [0901] perfection blocks (Quality >= 28, ilvl 83+ T1 bases like Spine Bow)
        bow = {"class": "Bows", "basetype": "Spine Bow", "rarity": "Normal", "ilvl": 84}
        self.assertEqual(decided_at(30, **bow).comment, "overquality 30%+")
        self.assertIn("perfection", decided_at(28, **bow).comment)
        # [overquality] is its own option: still on with module gear_special off
        self.cfg["gear_special"]["enabled"] = False
        self.assertEqual(decided_at(30).comment, "overquality 30%+")
        self.cfg["overquality"]["quality_30"] = False
        self.assertNotEqual(decided_at(30).comment, "overquality 30%+")
        self.cfg["overquality"]["quality_30"] = True
        self.cfg["gear_special"]["enabled"] = True
        self.assertEqual(decided_at(29).action, "Hide")
        self.assertNotEqual(decided_at(30, mirrored=True).comment, "overquality 30%+")
        self.assertNotEqual(decided_at(30, corrupted=True).comment, "overquality 30%+")

        self.cfg["overquality"]["quality_27"] = True
        self.assertEqual(decided_at(27).comment, "overquality 27%+")
        self.cfg["overquality"]["quality_30"] = False
        self.assertEqual(decided_at(30).comment, "overquality 27%+")

        self.cfg["overquality"]["quality_27"] = False
        self.cfg["overquality"]["quality_21"] = True
        self.assertEqual(decided_at(21).comment, "overquality 21%+")
        self.cfg["overquality"]["quality_21"] = False
        self.assertEqual(decided_at(30).action, "Hide")

    def test_crafting_and_overquality_have_icon_and_beam(self):
        # user pref: every crafting / quality Show has a minimap icon and a permanent beam
        for name in ("crafting", "gear_special", "flasks", "unique_exceptions"):
            for b in bf.load_module(name):
                if b["action"] != "Show" or (name == "gear_special" and b["section"] != "0901") or (
                        name in ("flasks", "unique_exceptions") and b["key"] not in bf.OVERQUALITY_TOGGLES):
                    continue
                self.assertTrue(any(s.startswith("MinimapIcon") for s in b["style"]), b["key"])
                self.assertTrue(any(s.startswith("PlayEffect") for s in b["style"]), b["key"])
        # user pref: no temporary beams anywhere (league start = every module block on)
        self.cfg["league_start"] = True
        self.assertNotRegex(bf.build_text(self.cfg, self.data, "x")[0], r"PlayEffect \w+ Temp")

    def test_overquality_groups_all_quality_rules(self):
        # every quality-threshold module block is a config.toml [overquality] key (one place)
        for name, table in self.cfg["modules"].items():
            for key, v in table["blocks"].items():
                if v == "config.toml [overquality]":
                    self.assertIn(key, set(bf.OVERQUALITY_KEYS) | set(bf.OVERQUALITY_TOGGLES), key)
        self.assertEqual({k: v for k, v in bf.OVERQUALITY_TOGGLES.items() if v not in self.cfg["overquality"]}, {})
        # t1 armour 21%: off -> the endgame hide layer hides it, on -> perfection Show
        regalia = {"class": "Body Armours", "basetype": "Twilight Regalia", "rarity": "Normal",
                   "ilvl": 84, "quality": 21, "area_level": 83}
        self.cfg["overquality"]["armour_t1_21"] = False
        self.assertFalse(fs.visible(self.build()[0], regalia))
        self.cfg["overquality"]["armour_t1_21"] = True
        self.assertIn("armors1q2", fs.evaluate(self.build()[0], regalia)[0].comment)
        # flask key: tinctures 21% ilvl 82+ in maps
        tincture = {"class": "Tinctures", "basetype": "Prismatic Tincture", "rarity": "Normal",
                    "ilvl": 82, "quality": 21, "area_level": 83}
        self.cfg["overquality"].update(tinctures_21=True)
        self.assertIn("overqual2", fs.evaluate(self.build()[0], tincture)[0].comment)
        self.cfg["overquality"].update(tinctures_21=False)
        self.assertNotIn("overqual2", fs.evaluate(self.build()[0], tincture)[0].comment)
        # league_start: every [overquality] key on
        ls = bf.apply_league_start(dict(copy.deepcopy(self.cfg), league_start=True))
        self.assertTrue(all(ls["overquality"].values()))

    def test_small_loot_toggle(self):
        # 4c Foulborn (Goldwyrm-like) and a 3c invitation: hidden with the wrist saver on,
        # shown (Foulborn quiet at its own tier) with it off
        self.cfg["small_loot"]["min_tier"] = "mid"
        add_foulborn(self.data, "Nubuck Boots", "Goldwyrm", "Gold", 4, listings=300, item_type="Boots", t="UniqueArmour")
        self.data["stash"]["Invitation"]["lines"].append(
            {"name": "Cheap Invitation", "chaosValue": 3, "listingCount": 100})
        boots = unid_unique("Nubuck Boots", "Boots", foulborn=True)
        inv = {"class": "Misc Map Items", "basetype": "Cheap Invitation"}
        self.cfg["small_loot"]["enabled"] = True
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Nubuck Boots"][0], "hide")
        self.assertFalse(fs.visible(blocks, boots))
        self.assertFalse(fs.visible(blocks, inv))
        self.cfg["small_loot"]["enabled"] = False
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Nubuck Boots"][0], "minor")
        self.assertTrue(fs.visible(blocks, boots))
        self.assertTrue(fs.visible(blocks, inv))

    def test_small_loot_default_shows_minor_tier_items(self):
        self.assertEqual(self.cfg["small_loot"]["min_tier"], "minor")
        self.data["stash"]["Invitation"]["lines"].append(
            {"name": "Cheap Invitation", "chaosValue": 3, "listingCount": 100})

        blocks, _ = self.build()
        self.assertTrue(fs.visible(
            blocks, {"class": "Misc Map Items", "basetype": "Cheap Invitation"}))

    def test_ancient_wombgift_has_minor_price_floor_and_keeps_higher_tier(self):
        item = {"class": "Wombgifts", "basetype": "Ancient Wombgift"}

        for price, expected_tier, expected_effect in [
                (None, "minor", "PlayEffect White"),
                (1, "minor", "PlayEffect White"),
                (3, "minor", "PlayEffect White"),
                (10, "mid", "PlayEffect Yellow"),
                (30, "high", "PlayEffect Red"),
                (100, "high", "PlayEffect Red")]:
            with self.subTest(price=price):
                self.data["stash"]["Wombgift"]["lines"] = []
                if price is not None:
                    self.data["stash"]["Wombgift"]["lines"].append(
                        {"name": "Ancient Wombgift", "baseType": "Ancient Wombgift",
                         "chaosValue": price, "listingCount": 100})

                blocks, result = self.build()
                self.assertEqual(result["prices"]["Ancient Wombgift"][0],
                                 max(price or 0, self.cfg["tiers"]["minor"]))
                self.assertEqual(result["tiers"].of(result["prices"]["Ancient Wombgift"][0]),
                                 expected_tier)
                block, style = fs.evaluate(blocks, item)
                self.assertEqual(block.action, "Show")
                self.assertIn(expected_effect, style)
                self.assertTrue(any(line.startswith("PlayAlertSound") for line in style))

    def test_boss_only_cheap_unique_keeps_tier_honest(self):
        # Titan Greaves: Kaom's Roots 26c drops in maps, Infinite Pursuit 1c is Breach-boss only.
        # Breach module on: the 1c one can drop, so the base must not claim "high" (normal or Foulborn).
        # (Off: it's ignored, see test_content_module_on_off.)
        rows = [{"name": "The Infinite Pursuit", "base": "Titan Greaves", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/BreachBossHandMage/HandMage |  | "}]
        add_unique(self.data, "Titan Greaves", "Kaom's Roots", 26, item_type="Boots", t="UniqueArmour")
        add_unique(self.data, "Titan Greaves", "The Infinite Pursuit", 1, item_type="Boots", t="UniqueArmour")
        add_foulborn(self.data, "Titan Greaves", "Kaom's Roots", "Strength", 54, item_type="Boots", t="UniqueArmour")
        add_foulborn(self.data, "Titan Greaves", "The Infinite Pursuit", "Bleed Armour", 0.98, item_type="Boots", t="UniqueArmour")
        self.data["nomap"] = {"The Infinite Pursuit": "Breach"}
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.cfg["content"]["breach"]["enabled"] = True
        _, r = self.build()
        self.assertEqual(r["ubases"]["Titan Greaves"][1], 1)
        self.assertEqual(r["fbases"]["Titan Greaves"][1], 0.98)
        self.assertEqual(r["ubases"]["Titan Greaves"][0], "hide")
        self.assertEqual(r["fbases"]["Titan Greaves"][0], "hide")

    def test_unknown_value_unique_makes_base_blue(self):
        # Archon Kite Shield: one priced 10c unique, The Unshattered Will drops but has no price
        add_unique(self.data, "Archon Kite Shield", "Priced Shield", 10, item_type="Shield", t="UniqueArmour")
        self.data["wiki_bases"] = {"Archon Kite Shield": {"Priced Shield", "The Unshattered Will"}}
        self.cfg["unknown_as_variable"] = True
        _, r = self.build()
        self.assertEqual(r["ubases"]["Archon Kite Shield"][0], "variable")
        self.cfg["unknown_as_variable"] = False
        _, r = self.build()
        self.assertEqual(r["ubases"]["Archon Kite Shield"][0], "mid")

    def test_linked_only_unique_is_not_unknown(self):
        # Tabula Rasa is only ever listed linked: priced, so Simple Robe keeps its tier
        add_unique(self.data, "Simple Robe", "Priced Robe", 10, item_type="Body Armour", t="UniqueArmour")
        self.data["stash"]["UniqueArmour"]["lines"].append(
            {"name": "Tabula Rasa", "baseType": "Simple Robe", "links": 6, "chaosValue": 10,
             "listingCount": 500, "itemType": "Body Armour"})
        self.data["wiki_bases"] = {"Simple Robe": {"Priced Robe", "Tabula Rasa"}}
        self.cfg["unknown_as_variable"] = True
        _, r = self.build()
        self.assertEqual(r["ubases"]["Simple Robe"][0], "mid")

    def test_small_loot_keeps_valuable_variant(self):
        # cheapest variant 2c, another 300c: never_hide_chaos keeps it visible (variable)
        self.cfg["small_loot"]["min_tier"] = "mid"
        self.cfg["uniques"]["variable_jackpot_only"] = False
        add_foulborn(self.data, "Titan Greaves", "Red Trail", "Junk", 2, item_type="Boots", t="UniqueArmour")
        add_foulborn(self.data, "Titan Greaves", "Red Trail", "Bleed Power", 300, listings=3, item_type="Boots", t="UniqueArmour")
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Titan Greaves"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Titan Greaves", "Boots", foulborn=True)))

    def test_foulborn_variants_cheapest_tiers_best_flags(self):
        # same unique, mutated-mod variants 1c .. 30 div: tier by cheapest (low), flagged variable
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Red Immortal", 30 * 400, listings=3, item_type="Two Handed Sword", t="UniqueWeapon")
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Other", 1, listings=3, item_type="Two Handed Sword", t="UniqueWeapon")
        _, r = self.build()
        tier, cheapest, best, *_ = r["fbases"]["Lion Sword"]
        self.assertEqual(cheapest, 1)  # 3+3 listings summed >= min_listings
        self.assertEqual(best, 30 * 400)
        self.assertEqual(tier, "variable")
        # cheapest already mid (ranks above variable): keeps its louder mid tier
        self.data["stash"]["UniqueWeapon"]["lines"][-1]["chaosValue"] = self.cfg["tiers"]["mid"] * 1.5
        _, r = self.build()
        self.assertEqual(r["fbases"]["Lion Sword"][0], "mid")

    def test_foulborn_does_not_raise_normal_tier(self):
        add_unique(self.data, "Leather Belt", "Junk", 1)
        add_foulborn(self.data, "Leather Belt", "Headhunter", "Culling Strike", 200000)
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts", foulborn=True)))

    def test_hidden_foulborn_not_shown_at_normal_tier(self):
        # Foulborn Cutlass: cheapest variant 5c (hidden), normal Cutlass 780c (high, red).
        # The Foulborn must stay hidden, the normal one shown.
        sword = dict(item_type="One Handed Sword", t="UniqueWeapon")
        add_unique(self.data, "Cutlass", "United in Dream", 780, **sword)
        add_foulborn(self.data, "Cutlass", "Severed in Sleep", "Minion Unholy", 0.5, **sword)
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Cutlass"][0], "hide")
        self.assertTrue(fs.visible(blocks, unid_unique("Cutlass", "One Hand Swords")))
        self.assertFalse(fs.visible(blocks, unid_unique("Cutlass", "One Hand Swords", foulborn=True)))

    def test_foulborn_own_jackpot(self):
        # 2 div best variant on a hidden 0.5c base: below the top-level jackpot, but at
        # [foulborn] jackpot_divine -> variable (Foulborn are Wombgift-only, lower bar)
        self.cfg["small_loot"]["enabled"] = False
        add_foulborn(self.data, "Cutlass", "Severed in Sleep", "Minion Unholy", 0.5, item_type="One Handed Sword", t="UniqueWeapon")
        add_foulborn(self.data, "Cutlass", "Severed in Sleep", "Minion Crit", 2 * 400, listings=1, item_type="One Handed Sword", t="UniqueWeapon")
        self.cfg["jackpot_divine"] = 100
        self.cfg["uniques"]["variable_jackpot_only"] = True  # never-hide floor = jackpot only
        self.cfg["foulborn"]["jackpot_divine"] = 100
        _, r = self.build()
        self.assertEqual(r["fbases"]["Cutlass"][0], "hide")
        self.cfg["foulborn"]["jackpot_divine"] = 1
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Cutlass"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Cutlass", "One Hand Swords", foulborn=True)))

    def test_jackpot_keeps_better_tier_than_variable(self):
        # cheapest unique on the base just under top (high), best a jackpot: the jackpot must
        # not drop it to blue variable (ranks below high); stays high. Normal + Foulborn.
        high = self.cfg["tiers"]["high"]
        sword = dict(item_type="Two Handed Sword", t="UniqueWeapon")
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Junk", high * 1.5, **sword)
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Chase", 76000, **sword)
        add_unique(self.data, "Lion Sword", "Mid One", high * 1.5, **sword)
        add_unique(self.data, "Lion Sword", "Chase One", 76000, **sword)
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Lion Sword"][0], "high")
        self.assertEqual(r["ubases"]["Lion Sword"][0], "high")
        b, _ = fs.evaluate(blocks, unid_unique("Lion Sword", "Two Hand Swords", foulborn=True))
        self.assertEqual(b.comment, "foulborn high")
        b, _ = fs.evaluate(blocks, unid_unique("Lion Sword", "Two Hand Swords"))
        self.assertEqual(b.comment, "uniques high")
        # tier hidden by config -> jackpot still blue, never hidden
        self.cfg["hide_tiers"] = self.cfg["hide_tiers"] + ["high"]
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Lion Sword"][0], "variable")
        self.assertEqual(r["ubases"]["Lion Sword"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Lion Sword", "Two Hand Swords", foulborn=True)))
        self.assertTrue(fs.visible(blocks, unid_unique("Lion Sword", "Two Hand Swords")))

    def test_foulborn_content_unique_follows_module(self):
        # Severed in Sleep = Breach-boss restricted. Breach module on: its Foulborn is priced
        # (jackpot -> blue), not skipped as boss-only. Off: boss-only -> hidden.
        rows = [{"name": "Severed in Sleep", "base": "Cutlass", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/BreachBossHandMage/HandMage |  | "}]
        self.data["nomap"] = bf.non_map_drops(rows, self.cfg)
        self.data["wiki_bases"] = bf.wiki_unique_bases(rows)
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.cfg["small_loot"]["enabled"] = False
        sword = dict(item_type="One Handed Sword", t="UniqueWeapon")
        add_foulborn(self.data, "Cutlass", "Severed in Sleep", "Minion Unholy", 0.5, **sword)
        add_foulborn(self.data, "Cutlass", "Severed in Sleep", "Minion Crit", 5 * 400, **sword)
        self.cfg["foulborn"]["jackpot_divine"] = 1
        item = unid_unique("Cutlass", "One Hand Swords", foulborn=True)
        self.cfg["content"]["breach"]["enabled"] = True
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Cutlass"][0], "variable")
        self.assertTrue(fs.visible(blocks, item))
        self.cfg["content"]["breach"]["enabled"] = False
        blocks, r = self.build()
        self.assertEqual(r["fbases"]["Cutlass"][0], "hide")
        self.assertFalse(fs.visible(blocks, item))

    def test_unique_show_toggles(self):
        # 1c base: minor/low tier, hidden by default; turning its tier on shows it
        self.cfg["small_loot"]["enabled"] = False
        add_unique(self.data, "Leather Belt", "Junk", 1)
        blocks, r = self.build()
        tier = r["ubases"]["Leather Belt"][0]
        self.assertEqual(tier, "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))
        self.cfg["uniques"]["show"] = dict.fromkeys(self.cfg["tiers"], True)
        blocks, r = self.build()
        self.assertIn(r["ubases"]["Leather Belt"][0], self.cfg["tiers"])
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))
        # turning off a tier doesn't touch lower ones; jackpots still go variable, never hidden
        add_unique(self.data, "Gold Ring", "Big", 2000, item_type="Ring")
        self.cfg["uniques"]["show"]["top"] = False
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Gold Ring"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Gold Ring", "Rings")))
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))

    def ev_setup(self):
        # 2 T5 junk + 2 T4 junk per tier slot, one T0 chase; tiers counted over drop_anywhere
        self.cfg["uniques"]["ev"]["enabled"] = True
        self.cfg["uniques"]["always_show_bases"] = []
        self.cfg["unknown_as_variable"] = True
        self.cfg["unique_tiers"] = {"Junk5": 5, "Junk4": 4, "Chase": 0, "Big4": 4}
        self.data["drop_anywhere"] = {"Junk5", "Junk4", "Chase", "Big4"}

    def test_ev_hides_rare_jackpot(self):
        # Leather Belt: 1c junk + 4800c T0. T0 ~ 0.005% vs 88% junk -> EV ~1c -> hidden
        self.ev_setup()
        add_unique(self.data, "Leather Belt", "Junk5", 1)
        add_unique(self.data, "Leather Belt", "Junk4", 1)
        add_unique(self.data, "Leather Belt", "Chase", 4800)
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "hide")
        self.assertLess(r["ubases"]["Leather Belt"][4], 2)
        self.assertFalse(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))
        self.cfg["uniques"]["always_show_bases"] = ["Leather Belt"]
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))

    def test_ev_common_valuable_unique_shows(self):
        # 1c T5 + 50c T4 on the same base: EV ~20c -> shown, blue because the cheap one is junk
        self.ev_setup()
        add_unique(self.data, "Gold Ring", "Junk5", 1, item_type="Ring")
        add_unique(self.data, "Gold Ring", "Big4", 50, item_type="Ring")
        blocks, r = self.build()
        self.assertGreater(r["ubases"]["Gold Ring"][4], 5)
        self.assertEqual(r["ubases"]["Gold Ring"][0], "variable")
        self.assertTrue(fs.visible(blocks, unid_unique("Gold Ring", "Rings")))

    def test_report_unique_ev(self):
        # report section: per base EV + each unique's drop share and price, and the real filter look
        self.ev_setup()
        add_unique(self.data, "Gold Ring", "Junk5", 1, item_type="Ring")
        add_unique(self.data, "Gold Ring", "Big4", 50, item_type="Ring")
        blocks, r = self.build()
        row = next(u for u in unique_ev(self.data, blocks, r) if u["base"] == "Gold Ring")
        self.assertAlmostEqual(row["ev"], r["ubases"]["Gold Ring"][4])
        self.assertEqual(row["tier"], "variable")
        self.assertTrue(row["shown"])
        parts = {u["name"]: u for u in row["uniques"]}
        self.assertAlmostEqual(sum(u["p"] for u in row["uniques"]), 1, places=3)
        self.assertAlmostEqual(sum(u["p"] * u["c"] for u in row["uniques"]), row["ev"], places=1)
        self.assertEqual((parts["Big4"]["t"], parts["Big4"]["c"]), (4, 50))

    def test_ev_variants_weighted_by_listings(self):
        # Mageblood-like: 900 listings at 10c, 100 at 1000c -> 109c per drop
        self.ev_setup()
        for chaos, n in [(10, 900), (1000, 100)]:
            self.data["stash"]["UniqueAccessory"]["lines"].append(
                {"name": "Big4", "baseType": "Heavy Belt", "variant": str(chaos), "chaosValue": chaos,
                 "listingCount": n, "itemType": "Belt"})
        _, r = self.build()
        self.assertAlmostEqual(r["ubases"]["Heavy Belt"][4], 109)

    def test_ev_unlisted_chase_is_blue(self):
        # T0 on the base with no price at all: can't rule it out -> variable
        self.ev_setup()
        add_unique(self.data, "Leather Belt", "Junk5", 1)
        self.data["wiki_bases"] = {"Leather Belt": {"Junk5", "Chase"}}
        _, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "variable")

    def harbinger_setup(self):
        # Fracturing Orb 400c -> Fracturing Shard 20c (mid tier); Torrent's Reclamation sells for 3c
        self.ev_setup()
        self.cfg["unique_tiers"]["The Torrent's Reclamation"] = 4
        self.data["drop_anywhere"].add("The Torrent's Reclamation")
        add_exchange(self.data, "Currency", "Fracturing Orb", 400)
        add_unique(self.data, "Cloth Belt", "The Torrent's Reclamation", 3)

    def test_harbinger_vendor_value_in_ev(self):
        # vendors for a 20c shard: EV 20c, not 3c -> shown mid; recipe off -> 3c, hidden
        self.harbinger_setup()
        belt = unid_unique("Cloth Belt", "Belts")
        blocks, r = self.build()
        self.assertAlmostEqual(r["ubases"]["Cloth Belt"][4], 20)
        self.assertEqual(r["ubases"]["Cloth Belt"][0], "mid")
        self.assertTrue(fs.visible(blocks, belt))
        self.assertNotIn("vendor recipe: harbinger", " ".join(b.comment for b in blocks))
        row = next(v for v in vendor_recipes(self.cfg, blocks, self.data) if v["key"] == "harbinger")
        self.assertEqual([(i["base"], i["shown"]) for i in row["items"]], [("Cloth Belt", True)])
        self.cfg["vendor_recipes"]["harbinger"]["enabled"] = False
        blocks, r = self.build()
        self.assertAlmostEqual(r["ubases"]["Cloth Belt"][4], 3)
        self.assertFalse(fs.visible(blocks, belt))

    def test_harbinger_vendor_value_beats_unknown(self):
        # thin / unlisted Harbinger unique: worth its shard, not an unknown chase (no blue)
        self.harbinger_setup()
        self.data["stash"]["UniqueAccessory"]["lines"] = []
        self.data["wiki_bases"] = {"Cloth Belt": {"The Torrent's Reclamation"}}
        self.cfg["unique_tiers"]["The Torrent's Reclamation"] = 0
        _, r = self.build()
        self.assertEqual(r["ubases"]["Cloth Belt"][0], "mid")
        self.assertAlmostEqual(r["ubases"]["Cloth Belt"][1], 20)

    def test_unpriced_foulborn_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Brand New Base", "Rings", foulborn=True)))

    def test_low_volume_card_quotes_are_treated_as_unknown(self):
        add_exchange(self.data, "DivinationCard", "Thin Card", 21, volume=3)
        add_exchange(self.data, "DivinationCard", "Thin Junk", 0.1, volume=1)
        blocks, r = self.build()
        self.assertNotIn("Thin Card", r["prices"])
        self.assertNotIn("Thin Junk", r["prices"])
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Thin Card"}))
        _, style = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Thin Card"})
        self.assertIn("SetTextColor 215 215 215 255", style)
        self.assertIn("PlayEffect Blue", style)
        self.assertIn("DisableDropSound True", style)
        self.assertFalse(any(line.startswith("PlayAlertSound") for line in style))

    def test_unpriced_tiers_config_tier(self):
        oil = {"class": "Stackable Currency", "basetype": "Clear Oil"}
        self.cfg["overrides"].pop("Clear Oil", None)
        self.cfg["exchange"]["unpriced_tiers"] = {"Clear Oil": "dust"}
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, oil)[0].comment, "unpriced currency, config tier dust")
        self.assertFalse(fs.visible(blocks, oil))  # dust hidden by default
        add_exchange(self.data, "Oil", "Clear Oil", 0.01, volume=1)  # thin + cheap: still unpriced
        self.assertFalse(fs.visible(self.build()[0], oil))
        self.data["exchange"]["Oil"]["lines"][-1].update(primaryValue=500, volumePrimaryValue=1000)
        self.assertTrue(fs.visible(self.build()[0], oil))  # confident price wins

    def test_high_volume_card_quote_is_not_used_without_buy_order_direction(self):
        add_exchange(self.data, "DivinationCard", "The Surgeon", 1000, volume=10000)
        blocks, r = self.build()
        self.assertNotIn("The Surgeon", r["prices"])
        self.assertEqual(r["ref_cards"]["The Surgeon"], "hide")
        card = {"class": "Divination Cards", "basetype": "The Surgeon"}
        self.assertTrue(fs.visible(blocks, card))
        _, style = fs.evaluate(blocks, card)
        self.assertIn("PlayEffect Blue", style)
        self.assertIn("DisableDropSound True", style)
        self.assertFalse(any(line.startswith("PlayAlertSound") for line in style))
        self.assertEqual(r["card_volumes"]["The Surgeon"], 10000)

    def test_confirmed_currency_card_falls_back_to_neversink_group_without_reward_price(self):
        blocks, r = self.build()
        self.assertNotIn("Loyalty", r["prices"])
        self.assertEqual(r["ref_cards"]["Loyalty"], "hide")
        self.assertFalse(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Loyalty"}))

    def test_low_volume_card_quote_uses_hidden_neversink_group(self):
        add_exchange(self.data, "DivinationCard", "The Dark Mage", 1000, volume=1)
        blocks, r = self.build()
        self.assertNotIn("The Dark Mage", r["prices"])
        self.assertEqual(r["ref_cards"]["The Dark Mage"], "hide")
        self.assertFalse(fs.visible(blocks, {"class": "Divination Cards", "basetype": "The Dark Mage"}))

    def test_dark_mage_without_market_price_uses_hidden_neversink_group(self):
        blocks, r = self.build()
        self.assertNotIn("The Dark Mage", r["prices"])
        self.assertEqual(r["ref_cards"]["The Dark Mage"], "hide")
        self.assertFalse(fs.visible(blocks, {"class": "Divination Cards", "basetype": "The Dark Mage"}))

    def test_unpriced_cards_use_regular_neversink_groups(self):
        blocks, r = self.build()
        expected = {
            "Abandoned Wealth": "hide",
            "The Endless Darkness": "top",
            "Brother's Stash": "hide",
            "House of Mirrors": "top",
            "The Surgeon": "hide",
        }
        for card, tier in expected.items():
            self.assertNotIn(card, r["prices"])
            self.assertEqual(r["ref_cards"][card], tier)
            self.assertEqual(fs.visible(blocks, {"class": "Divination Cards", "basetype": card}),
                             tier != "hide", card)
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Card From Next League"}))

    def test_card_missing_from_neversink_groups_uses_unknown_style_without_sound(self):
        blocks, _ = self.build()
        block, style = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Card From Next League"})
        self.assertIn("SetTextColor 215 215 215 255", style)
        self.assertIn("PlayEffect Blue", style)
        self.assertIn("MinimapIcon 1 Blue Circle", style)
        self.assertIn("DisableDropSound True", style)
        self.assertFalse(any(line.startswith("PlayAlertSound") for line in style))

    def test_stack_lifts_hidden_item(self):
        add_exchange(self.data, "Currency", "Half Orb", 0.5)
        blocks, _ = self.build()
        orb = {"class": "Stackable Currency", "basetype": "Half Orb"}
        self.assertFalse(fs.visible(blocks, dict(orb, stack=1)))
        self.assertTrue(fs.visible(blocks, dict(orb, stack=10)))

    def test_stackable_icon_shapes_follow_item_category(self):
        categories = [
            ("Essence", "Deafening Essence of Greed", "Circle"),
            ("Oil", "Golden Oil", "Circle"),
            ("Fossil", "Perfect Fossil", "Circle"),
            ("Resonator", "Prime Chaotic Resonator", "Circle"),
            ("Artifact", "Greater Broken Circle Artifact", "Circle"),
            ("DeliriumOrb", "Delirium Orb", "Circle"),
            ("Tattoo", "Honoured Tattoo", "Moon"),
        ]
        for item_type, name, _ in categories:
            add_exchange(self.data, item_type, name, 5)

        blocks, _ = self.build()
        for item_type, name, expected_shape in categories:
            _, style = fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": name})
            icon = next(line for line in style if line.startswith("MinimapIcon"))
            self.assertEqual(icon.split()[-1], expected_shape, item_type)

    def test_splinter_priced_from_finished_item(self):
        add_exchange(self.data, "Fragment", "Timeless Karui Emblem", 7)
        add_exchange(self.data, "Fragment", "Timeless Templar Splinter", 4)  # thin, wrong
        add_exchange(self.data, "Fragment", "Timeless Templar Emblem", 12)
        blocks, r = self.build()
        self.assertAlmostEqual(r["prices"]["Timeless Karui Splinter"][0], 0.07)
        self.assertAlmostEqual(r["prices"]["Timeless Templar Splinter"][0], 0.12)
        karui = {"class": "Map Fragments", "basetype": "Timeless Karui Splinter"}
        self.assertFalse(fs.visible(blocks, dict(karui, stack=1)))
        self.assertTrue(fs.visible(blocks, dict(karui, stack=72)))  # 5.04c, above max_stack 40

    def test_currency_shards_use_orb_conversion_not_exchange_quotes(self):
        shards = {
            "Alchemy Shard": "Orb of Alchemy",
            "Alteration Shard": "Orb of Alteration",
            "Fracturing Shard": "Fracturing Orb",
            "Mirror Shard": "Mirror of Kalandra",
            "Transmutation Shard": "Orb of Transmutation",
        }
        for shard, orb in shards.items():
            add_exchange(self.data, "Currency", orb, 100)
            add_exchange(self.data, "Currency", shard, 1, volume=0.5)

        blocks, result = self.build()

        for shard, orb in shards.items():
            with self.subTest(shard=shard):
                self.assertEqual(result["prices"][shard][0], result["prices"][orb][0] / 20)
                item = {"class": "Stackable Currency", "basetype": shard, "stack": 15}
                block, style = fs.evaluate(blocks, item)
                self.assertEqual(block.action, "Show")
                self.assertIn("PlayEffect Red", style)
                self.assertNotIn("PlayEffect White", style)
                for candidate in blocks:
                    if any(key == "BaseType" and shard in values
                           for key, _, values, _ in candidate.conds):
                        stack_condition = next((int(values[0]) for key, _, values, _
                                                in candidate.conds if key == "StackSize"), None)
                        self.assertTrue(stack_condition is None or stack_condition <= 20)

    def test_splinter_exchange_price_is_ignored_when_finished_item_is_unpriced(self):
        add_exchange(self.data, "Fragment", "Timeless Templar Emblem", 0.01, volume=1)
        add_exchange(self.data, "Fragment", "Timeless Templar Splinter", 20)
        _, r = self.build()
        self.assertNotIn("Timeless Templar Splinter", r["prices"])

    def test_exact_currency_reward_ignores_divination_card_quote(self):
        add_exchange(self.data, "Currency", "Exalted Orb", 100)
        add_exchange(self.data, "DivinationCard", "Abandoned Wealth", 50, volume=100)
        blocks, r = self.build()
        self.assertAlmostEqual(r["prices"]["Abandoned Wealth"][0], 60)
        self.assertEqual(r["prices"]["Abandoned Wealth"][1], "DivinationCard")
        self.assertTrue(r["card_volumes"]["Abandoned Wealth"] >= self.cfg["exchange"]["card_fallback_min_volume"])
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Abandoned Wealth"}))

    def test_confirmed_currency_card_uses_reward_value_per_set(self):
        add_exchange(self.data, "Currency", "Orb of Fusing", 0.5)
        blocks, r = self.build()
        self.assertAlmostEqual(r["prices"]["Loyalty"][0], 0.3)
        self.assertEqual(r["prices"]["Loyalty"][1], "DivinationCard")
        card = {"class": "Divination Cards", "basetype": "Loyalty"}
        self.assertFalse(fs.visible(blocks, card))
        self.assertFalse(fs.visible(blocks, dict(card, stack=3)))
        self.assertTrue(fs.visible(blocks, dict(card, stack=4)))

    def test_exact_item_card_reward_uses_item_price_even_when_card_quote_differs_10x(self):
        add_unique(self.data, "Simple Robe", "Tabula Rasa", 5, listings=100,
                   item_type="Body Armour", t="UniqueArmour")
        add_exchange(self.data, "DivinationCard", "Humility", 100, volume=1000)
        blocks, r = self.build()
        self.assertAlmostEqual(r["prices"]["Humility"][0], 5 / 9)
        self.assertEqual(r["prices"]["Humility"][1], "DivinationCard")
        self.assertGreater(100, r["prices"]["Humility"][0] * 10)
        rule, _ = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Humility"})
        self.assertNotIn("unpriced cards", rule.comment)
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Humility", "stack": 9}))

    def test_exact_item_card_reward_requires_confident_item_listings(self):
        add_unique(self.data, "Simple Robe", "Tabula Rasa", 5, listings=1,
                   item_type="Body Armour", t="UniqueArmour")
        _, r = self.build()
        self.assertNotIn("Humility", r["prices"])

    def test_exact_unique_card_reward_uses_exact_item_price_per_set(self):
        add_unique(self.data, "Ezomyte Dagger", "Cold Iron Point", 4.6, item_type="Dagger", t="UniqueWeapon")
        add_exchange(self.data, "DivinationCard", "Broken Truce", 100, volume=1000)
        _, r = self.build()
        self.assertAlmostEqual(r["prices"]["Broken Truce"][0], 4.6 / 5)
        self.assertEqual(r["prices"]["Broken Truce"][1], "DivinationCard")

    def test_exact_non_currency_exchange_card_reward_uses_reward_market_price(self):
        add_exchange(self.data, "Scarab", "Bestiary Scarab", 12)
        _, r = self.build()
        self.assertAlmostEqual(r["prices"]["Man With Bear"][0], 4)
        self.assertEqual(r["prices"]["Man With Bear"][1], "DivinationCard")

    def test_exact_card_reward_chain_uses_mirror_value_not_card_quotes(self):
        add_exchange(self.data, "Currency", "Mirror of Kalandra", 9000)
        add_exchange(self.data, "DivinationCard", "House of Mirrors", 100000, volume=1000)
        add_exchange(self.data, "DivinationCard", "The Immortal", 100000, volume=1000)
        _, r = self.build()
        self.assertAlmostEqual(r["prices"]["House of Mirrors"][0], 1000)
        self.assertAlmostEqual(r["prices"]["The Immortal"][0], 100)
        self.assertEqual(r["prices"]["House of Mirrors"][1], "DivinationCard")
        self.assertEqual(r["prices"]["The Immortal"][1], "DivinationCard")

    def test_card_reward_chain_stays_unpriced_without_exact_reward_market_data(self):
        add_exchange(self.data, "DivinationCard", "House of Mirrors", 100000, volume=1000)
        add_exchange(self.data, "DivinationCard", "The Immortal", 100000, volume=1000)
        _, r = self.build()
        self.assertNotIn("House of Mirrors", r["prices"])
        self.assertNotIn("The Immortal", r["prices"])

    def test_removed_category_feed_builds(self):
        # Patch removes a category (Scarab, 2026-11-13 patch): poe.ninja feed gone -> {} from fetch_feed.
        # Build must still work, other stackables still priced.
        self.data["exchange"]["Scarab"] = {}
        add_exchange(self.data, "Currency", "Chaos Orb", 1)
        _, r = self.build()
        self.assertIn("Chaos Orb", r["prices"])

    def test_fetch_feed_gone_is_empty_not_fatal(self):
        import io
        import urllib.error
        from contextlib import redirect_stderr
        from unittest import mock

        def gone(*_a, **_k):
            raise urllib.error.HTTPError("u", 404, "Not Found", None, None)

        def down(*_a, **_k):
            raise urllib.error.HTTPError("u", 503, "Unavailable", None, None)

        with mock.patch.object(bf, "fetch_json", gone), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(bf.fetch_feed("u", None, 0, False, "exchange Scarab"), {})
        self.assertIn("exchange Scarab", err.getvalue())
        with mock.patch.object(bf, "fetch_json", down), self.assertRaises(urllib.error.HTTPError):
            bf.fetch_feed("u", None, 0, False, "exchange Scarab")

    def test_generic_scarab_rewards_are_not_treated_as_exact_items(self):
        rewards = self.cfg["exchange"]["card_rewards"]
        for card in ("Rebirth and Renewal", "The Card Sharp", "The Deal"):
            self.assertNotIn(card, rewards)

    def test_card_quote_below_minimum_volume_uses_neversink_reference_tier(self):
        add_exchange(self.data, "DivinationCard", "Broken Truce", 500, volume=4.99)
        blocks, r = self.build()
        self.assertNotIn("Broken Truce", r["prices"])
        self.assertEqual(r["ref_cards"]["Broken Truce"], "mid")
        _, style = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Broken Truce"})
        self.assertIn("PlayEffect Yellow", style)

    def test_nonhidden_neversink_group_is_suppressed_at_minimum_volume(self):
        add_exchange(self.data, "DivinationCard", "Broken Truce", 20, volume=5)
        blocks, r = self.build()
        self.assertNotIn("Broken Truce", r["prices"])
        self.assertEqual(r["ref_cards"]["Broken Truce"], "mid")
        self.assertEqual(r["card_volumes"]["Broken Truce"], 5)
        _, style = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Broken Truce"})
        self.assertIn("PlayEffect Blue", style)
        self.assertIn("DisableDropSound True", style)
        self.assertFalse(any(line.startswith("PlayAlertSound") for line in style))

    def test_card_reward_ignores_linked_unique_lines(self):
        # live: 5-link Whispering Ice listed 21235c x19 tinked The Incantation (unlinked reward)
        add_unique(self.data, "Vile Staff", "The Whispering Ice", 0.32, listings=180, item_type="Staff", t="UniqueWeapon")
        self.data["stash"]["UniqueWeapon"]["lines"].append({"name": "The Whispering Ice", "baseType": "Vile Staff",
            "links": 5, "chaosValue": 21235, "listingCount": 19, "itemType": "Staff"})
        blocks, r = self.build()
        self.assertAlmostEqual(r["prices"]["The Incantation"][0], 0.08)
        _, style = fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "The Incantation", "stack": 1})
        self.assertNotIn("PlayEffect Red", style or [])

    def test_exact_reward_price_overrides_card_exchange_quote(self):
        add_unique(self.data, "Ezomyte Dagger", "Cold Iron Point", 1000, item_type="Dagger", t="UniqueWeapon")
        add_exchange(self.data, "DivinationCard", "Broken Truce", 50, volume=100)
        _, r = self.build()
        self.assertAlmostEqual(r["prices"]["Broken Truce"][0], 200)

    def test_leveling_only_in_campaign(self):
        self.cfg["leveling"] = {"enabled": True, "strictness": 2, "area_level_max": 67}
        blocks, _ = self.build()
        boots = {"class": "Boots", "basetype": "Leather Boots", "rarity": "Rare", "ilvl": 30, "evasion": 10}
        self.assertTrue(fs.visible(blocks, dict(boots, area_level=30)))
        self.assertFalse(fs.visible(blocks, dict(boots, ilvl=83)))  # in a map: hidden gear
        flask = {"class": "Life Flasks", "basetype": "Medium Life Flask", "rarity": "Normal", "area_level": 10}
        self.assertTrue(fs.visible(blocks, flask))
        # leveling never hides a unique
        add_unique(self.data, "Small Life Flask", "Junk Flask", 50, item_type="Flask", t="UniqueFlask")
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {"class": "Life Flasks", "basetype": "Small Life Flask",
                                            "rarity": "Unique", "area_level": 40}))

    def test_leveling_module(self):
        # module leveling: [2802] [[3800]] [[5000]]-[[5405]], no build module / extras in the way
        lv = self.cfg["leveling"]
        lv.update(enabled=True, strictness=2, build="", hide_normal_after=None, hide_magic_after=None,
                  show_magic_rare_cells=0, show_jewellery=False, show_jewels=False)
        toggles = self.cfg["modules"]["leveling"]["blocks"]
        camp = lambda cls, base, rarity="Normal", area=20, **kw: {
            "class": cls, "basetype": base, "rarity": rarity, "ilvl": area, "area_level": area, **kw}
        cur = lambda base, stack=1: {"class": "Stackable Currency", "basetype": base, "stack": stack, "area_level": 20}
        jewel = camp("Jewels", "Cobalt Jewel", "Magic", 30)
        old_flask = camp("Life Flasks", "Small Life Flask", quality=0)
        quicksilver = camp("Utility Flasks", "Quicksilver Flask", "Magic", 10)
        aquamarine = camp("Utility Flasks", "Aquamarine Flask", "Magic", 10)
        rare_boots = camp("Boots", "Leather Boots", "Rare", 30, evasion=10)
        magic_gloves = camp("Gloves", "Iron Gauntlets", "Magic", 40, armour=10)
        hybrid = camp("Hybrid Flasks", "Small Hybrid Flask", area=10)
        spirit = camp("Shields", "Bone Spirit Shield", es=10)
        add_exchange(self.data, "Currency", "Orb of Binding", 30)   # high tier: price beats [[3800]]
        add_exchange(self.data, "Currency", "Orb of Chance", 0.05)  # a big stack reaches a shown tier

        def rule(item):
            b, style = fs.evaluate(blocks, item)
            return (b.action, b.comment.removeprefix("leveling ").removesuffix(" (module leveling)")), style
        blocks, _ = self.build()
        for item, want in [
            (jewel, ("Show", "jewels->leveling.generic")),                      # [2802] %D3
            (cur("Orb of Transmutation", 3), ("Show", "currency->levelingstacked.t3trans")),  # [3800] %D4
            (cur("Scroll of Wisdom", 2), ("Show", "currency->levelingstacked.wisdom")),       # %D3
            (cur("Orb of Chance", 3), ("Show", "currency->levelingstacked.t2chance")),
            (old_flask, ("Hide", "hidelayer.outdatedlevelflaska")),             # [5000]
            (quicksilver, ("Show", "leveling->flasks->utility.quicksilver")),   # option, on as before
            (aquamarine, ("Show", "leveling->flasks->utility.any")),            # %H3: Show below 3
            (camp("Life Flasks", "Medium Life Flask", area=10), ("Show", "leveling->flasks->life.t2")),
            (hybrid, ("Hide", "leveling->flasks->hybrid.t1")),                  # %H2 at strictness 2
            (camp("Tinctures", "Prismatic Tincture", "Magic", 10), ("Show", "leveling->tincture.any")),
            (rare_boots, ("Show", "leveling->rare->armours.bootsfocus")),        # [5304]
            (camp("Wands", "Driftwood Wand", "Rare", 30), ("Show", "leveling->rare->caster.general")),
            (camp("Two Hand Axes", "Stone Axe", area=3), ("Show", "leveling->firstlevels.firstareas")),
            (camp("Body Armours", "Plate Vest", area=5, armour=10), ("Hide", "leveling->firstlevels.earlybodyarmours")),
            (magic_gloves, ("Hide", "leveling->magic->remaining.rest")),         # [5405] %H1
            (camp("Gloves", "Iron Gauntlets", "Magic", 5, armour=10), ("Show", "leveling->magic->remaining.firstlevels")),
        ]:
            self.assertEqual(rule(item)[0], want, item)
        self.assertIn("PlayAlertSound 2 300", rule(quicksilver)[1])             # quicksilver alert kept
        self.assertIn("MinimapIcon 1 Yellow Raindrop", rule(quicksilver)[1])
        # price first: a priced shown tier (or stack reaching one) keeps its tier style
        for item in (cur("Orb of Binding"), cur("Orb of Chance", 40), cur("Divine Orb")):
            self.assertNotIn("leveling", rule(item)[0][1], item)
            self.assertTrue(fs.visible(blocks, item), item)
        self.assertNotIn("leveling", rule(spirit)[0][1])                        # option off
        self.assertNotIn("leveling", rule(dict(rare_boots, area_level=75))[0][1])  # maps: no campaign rule
        self.assertFalse(fs.visible(blocks, dict(rare_boots, area_level=75)))
        self.assertNotIn("leveling", rule(dict(cur("Orb of Transmutation", 3), area_level=75))[0][1])
        # strictness 0: %H blocks Show, more %D Shows (currency too)
        lv["strictness"] = 0
        blocks, _ = self.build()
        self.assertEqual(rule(magic_gloves)[0], ("Show", "leveling->magic->remaining.rest"))
        self.assertTrue(fs.visible(blocks, hybrid))
        self.assertEqual(rule(cur("Scroll of Wisdom", 2))[0], ("Show", "currency->levelingstacked.wisdom"))
        self.assertEqual(rule(cur("Orb of Augmentation"))[0], ("Show", "currency->leveling.t5aug"))
        self.assertNotIn("leveling", rule(cur("Orb of Binding"))[0][1])
        # strictness 3: %D3 jewels / wisdom off, %H3 utility flasks hidden, %D4 currency still on
        lv["strictness"] = 3
        blocks, _ = self.build()
        self.assertNotIn("jewels->leveling", rule(jewel)[0][1])
        self.assertNotIn("leveling", rule(cur("Scroll of Wisdom", 2))[0][1])
        self.assertTrue(fs.visible(blocks, cur("Scroll of Wisdom", 2)))        # campaign_unhide
        self.assertEqual(rule(cur("Orb of Transmutation", 3))[0], ("Show", "currency->levelingstacked.t3trans"))
        self.assertEqual(rule(aquamarine)[0], ("Hide", "leveling->flasks->utility.any"))
        self.assertEqual(rule(quicksilver)[0][1], "leveling->flasks->utility.quicksilver")
        # per-block toggles: an option off, a hide layer / strictness key off
        lv["strictness"] = 2
        toggles.update({"leveling->flasks->utility.quicksilver": False, "hidelayer.outdatedlevelflaska": False,
                        "leveling->magic->remaining.rest": False, "currency->levelingstacked.t3trans": False})
        blocks, _ = self.build()
        self.assertEqual(rule(quicksilver)[0], ("Show", "leveling->flasks->utility.asortedutility"))
        self.assertNotEqual(rule(old_flask)[0][1], "hidelayer.outdatedlevelflaska")
        self.assertNotEqual(rule(magic_gloves)[0][1], "leveling->magic->remaining.rest")
        self.assertNotEqual(rule(cur("Orb of Transmutation", 3))[0][1], "currency->levelingstacked.t3trans")
        # league_start: option Shows on, strictness keys unchanged (still the campaign preset)
        self.cfg["modules"] = copy.deepcopy(bf.load_cfg()["modules"])
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        self.assertEqual(rule(spirit)[0], ("Show", "leveling->normalmagic->minion.minionshields"))
        self.assertEqual(rule(magic_gloves)[0], ("Hide", "leveling->magic->remaining.rest"))
        self.assertEqual(rule(old_flask)[0], ("Hide", "hidelayer.outdatedlevelflaska"))
        self.assertEqual(rule(hybrid)[0], ("Hide", "leveling->flasks->hybrid.t1"))
        # [leveling] enabled = false: no module leveling
        self.cfg["league_start"] = False
        lv["enabled"] = False
        blocks, _ = self.build()
        self.assertNotIn("leveling", rule(rare_boots)[0][1])
        self.assertNotIn("leveling", rule(cur("Orb of Transmutation", 3))[0][1])

    def test_vendor_small_magic_rare(self):
        self.cfg["leveling"].update(enabled=True, build="rf", hide_normal_after=2, hide_magic_after=7,
                                    show_magic_vendor=True, show_rare_vendor=True, show_magic_rare_cells=4)
        blocks, _ = self.build()
        camp = {"area_level": 20, "ilvl": 20}
        for item, shown in [
            ({"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Rare", "es": 10,
              "width": 2, "height": 2}, True),  # beats rf no pure ES
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Magic",
              "width": 1, "height": 3}, True),  # beats hide_magic_after
            ({"class": "One Hand Swords", "basetype": "Copper Sword", "rarity": "Magic",
              "width": 1, "height": 3}, True),
            ({"class": "Thrusting One Hand Swords", "basetype": "Rusted Spike", "rarity": "Rare",
              "width": 1, "height": 4}, True),
            ({"class": "Sceptres", "basetype": "Driftwood Sceptre", "rarity": "Rare",
              "width": 1, "height": 3}, True),
            ({"class": "Shields", "basetype": "Goathide Buckler", "rarity": "Rare", "evasion": 10,
              "width": 2, "height": 2}, True),
            ({"class": "Shields", "basetype": "Splintered Tower Shield", "rarity": "Rare",
              "width": 2, "height": 4}, False),
            ({"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Normal", "es": 10}, False),
        ]:
            self.assertEqual(fs.visible(blocks, {**camp, **item}), shown, item)
        # maps untouched
        self.assertFalse(fs.visible(blocks, {"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Magic"}))

    def test_vendor_rarity_toggles_are_independent(self):
        self.cfg["leveling"].update(enabled=True, build="rf", hide_normal_after=2, hide_magic_after=7,
                                    show_magic_rare_cells=4, show_magic_vendor=False, show_rare_vendor=True)
        camp = {"area_level": 20, "ilvl": 20}
        magic_wand = {"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Magic",
                      "width": 1, "height": 3}
        rare_gloves = {"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Rare", "es": 10,
                       "width": 2, "height": 2}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, {**camp, **magic_wand}))
        self.assertTrue(fs.visible(blocks, {**camp, **rare_gloves}))

        self.cfg["leveling"].update(show_magic_vendor=True, show_rare_vendor=False)
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {**camp, **magic_wand}))
        self.assertFalse(fs.visible(blocks, {**camp, **rare_gloves}))

    def test_rf_leveling(self):
        self.cfg["show_gold"] = True
        self.cfg["leveling"].update(enabled=True, build="rf", hide_normal_after=2, show_all_stackables=True,
                                    show_jewellery=True, show_magic_rare_cells=0)
        add_exchange(self.data, "Currency", "Cheap Shard", 0.001)
        blocks, _ = self.build()
        camp = {"area_level": 20, "ilvl": 20}
        for item, shown in [
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Rare", "armour": 10}, True),
            ({"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Rare", "evasion": 10}, True),
            ({"class": "Gloves", "basetype": "Fishscale Gauntlets", "rarity": "Rare", "armour": 5, "evasion": 5}, True),
            ({"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Rare", "es": 10}, False),
            ({"class": "Shields", "basetype": "Goathide Buckler", "rarity": "Normal", "evasion": 10, "area_level": 2}, False),
            ({"class": "Shields", "basetype": "Splintered Tower Shield", "rarity": "Rare", "armour": 10}, False),
            ({"class": "Shields", "basetype": "Splintered Tower Shield", "rarity": "Rare", "armour": 10, "area_level": 40}, True),
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Normal", "armour": 10}, False),
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Normal", "armour": 10, "area_level": 2}, True),
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Normal", "armour": 10, "area_level": 3}, False),
            ({"class": "Mana Flasks", "basetype": "Hallowed Mana Flask", "rarity": "Normal", "area_level": 40}, False),
            ({"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Magic"}, True),  # show_jewels
            ({"class": "Stackable Currency", "basetype": "Cheap Shard"}, True),
            ({"class": "Stackable Currency", "basetype": "Scroll of Wisdom"}, True),
            ({"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Normal", "armour": 10, "links": 4}, True),
            ({"class": "Rings", "basetype": "Iron Ring", "rarity": "Normal"}, True),
            ({"class": "Life Flasks", "basetype": "Medium Life Flask", "rarity": "Normal", "area_level": 10}, True),
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Rare"}, False),
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Magic"}, True),
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Normal", "area_level": 2}, True),
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Normal", "area_level": 3}, False),
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Normal", "area_level": 1}, True),
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Normal", "area_level": 1}, False),
            ({"class": "Belts", "basetype": "Leather Belt", "rarity": "Normal", "area_level": 1}, True),
            ({"class": "Amulets", "basetype": "Coral Amulet", "rarity": "Normal", "area_level": 40}, True),
            ({"class": "Rings", "basetype": "Sapphire Ring", "rarity": "Magic", "area_level": 60}, True),
            ({"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Normal", "es": 5, "area_level": 1}, False),
            ({"class": "Belts", "basetype": "Rustic Sash", "rarity": "Normal", "area_level": 10}, True),
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Magic", "area_level": 40}, False),
            ({"class": "Boots", "basetype": "Wool Shoes", "rarity": "Unique", "es": 10}, True),  # Wanderlust
            ({"class": "Stackable Currency", "basetype": "Orb of Transmutation"}, True),
            ({"class": "Stackable Currency", "basetype": "Gold", "stack": 50}, True),
        ]:
            self.assertEqual(fs.visible(blocks, {**camp, **item}), shown, item)
        # hide_magic_after = 7: blue gear hidden after, flasks / jewellery / build weapons stay
        for item, shown in [
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Magic", "armour": 10, "area_level": 7}, True),
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Magic", "armour": 10, "area_level": 8}, False),
            ({"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Magic", "armour": 10, "links": 4,
              "area_level": 30}, False),  # after show_3_links_until
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Rare", "armour": 10}, True),
            ({"class": "Amulets", "basetype": "Coral Amulet", "rarity": "Magic"}, True),
            ({"class": "Two Hand Maces", "basetype": "Driftwood Club", "rarity": "Magic"}, True),
        ]:
            self.assertEqual(fs.visible(blocks, {**camp, **item}), shown, item)
        self.cfg["leveling"]["keep_build_weapons_magic"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, {**camp, "class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Magic"}))
        self.assertTrue(fs.visible(blocks, {**camp, "class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Magic",
                                            "area_level": 7}))
        # maps untouched: white gear in a map still hidden, small gold hidden
        self.assertFalse(fs.visible(blocks, {"class": "Rings", "basetype": "Iron Ring", "rarity": "Normal"}))
        self.assertFalse(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Gold", "stack": 50}))
        self.assertFalse(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Cheap Shard"}))

    def test_minion_leveling(self):
        self.cfg["leveling"].update(enabled=True, build="minion", hide_normal_after=2, hide_magic_after=7,
                                    show_jewellery=False, show_magic_rare_cells=0, keep_build_weapons_magic=True)
        blocks, _ = self.build()
        camp = {"area_level": 30, "ilvl": 30}
        for item, shown in [
            # minion bases: any rarity, whole campaign, past hide_normal_after / hide_magic_after
            ({"class": "Wands", "basetype": "Calling Wand", "rarity": "Normal"}, True),
            ({"class": "Wands", "basetype": "Convening Wand", "rarity": "Magic"}, True),
            ({"class": "Wands", "basetype": "Convoking Wand", "rarity": "Rare", "area_level": 67}, True),
            ({"class": "Rings", "basetype": "Bone Ring", "rarity": "Normal"}, True),
            ({"class": "Rings", "basetype": "Bone Ring", "rarity": "Magic"}, True),
            ({"class": "Shields", "basetype": "Bone Spirit Shield", "rarity": "Normal", "es": 10}, True),
            # other wands: magic / rare early only, white until hide_normal_after
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Magic", "area_level": 7}, True),
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Magic"}, False),
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Normal", "area_level": 2}, True),
            ({"class": "Wands", "basetype": "Driftwood Wand", "rarity": "Normal", "area_level": 3}, False),
            # armour/ES hybrid only: never pure armour, evasion or pure ES
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Rare", "armour": 10}, False),
            ({"class": "Gloves", "basetype": "Wool Gloves", "rarity": "Rare", "es": 10}, False),
            ({"class": "Gloves", "basetype": "Riveted Gloves", "rarity": "Rare", "armour": 5, "es": 5}, True),
            ({"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Rare", "evasion": 10}, False),
            ({"class": "Gloves", "basetype": "Fishscale Gauntlets", "rarity": "Rare", "armour": 5, "evasion": 5}, False),
            ({"class": "Shields", "basetype": "Goathide Buckler", "rarity": "Rare", "evasion": 10}, False),
            ({"class": "Shields", "basetype": "Splintered Tower Shield", "rarity": "Rare", "armour": 10}, False),
            ({"class": "Shields", "basetype": "Splintered Tower Shield", "rarity": "Normal", "armour": 10, "area_level": 2}, True),
            # pure armour only before that slot's first armour/ES base can drop (gloves / shields 7, helmets / boots 5)
            ({"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Rare", "armour": 10, "area_level": 6}, True),
            ({"class": "Helmets", "basetype": "Iron Hat", "rarity": "Rare", "armour": 10, "area_level": 4}, True),
            ({"class": "Helmets", "basetype": "Iron Hat", "rarity": "Rare", "armour": 10, "area_level": 5}, False),
            ({"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Rare", "armour": 10, "area_level": 2}, False),
            ({"class": "Shields", "basetype": "Plank Kite Shield", "rarity": "Rare", "armour": 5, "es": 5}, True),
            ({"class": "Shields", "basetype": "Plank Kite Shield", "rarity": "Normal", "armour": 5, "es": 5, "area_level": 2}, True),
            # wands only
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Rare"}, False),
            ({"class": "Sceptres", "basetype": "Driftwood Sceptre", "rarity": "Rare"}, False),
            ({"class": "Body Armours", "basetype": "Chainmail Vest", "rarity": "Normal", "armour": 5, "es": 5, "links": 4,
              "socket_group": "BBBB"}, True),
            ({"class": "Body Armours", "basetype": "Simple Robe", "rarity": "Normal", "es": 10, "links": 4,
              "socket_group": "BBBB"}, False),
            ({"class": "Boots", "basetype": "Wool Shoes", "rarity": "Unique", "evasion": 10}, True),  # Wanderlust
            # early 3-links: any base, any rarity incl. white, until area 24
            ({"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Normal", "evasion": 10, "links": 3,
              "socket_group": "RRG", "area_level": 24}, True),
            ({"class": "Body Armours", "basetype": "Simple Robe", "rarity": "Magic", "es": 10, "links": 3,
              "socket_group": "GGG", "area_level": 10}, True),
            # link_classes (default: no weapons, no boots): links don't show them
            ({"class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Rare", "links": 3,
              "socket_group": "RRR", "area_level": 10}, False),
            ({"class": "Boots", "basetype": "Iron Greaves", "rarity": "Magic", "armour": 10, "links": 3,
              "socket_group": "BBB", "area_level": 10}, False),
            ({"class": "Boots", "basetype": "Iron Greaves", "rarity": "Magic", "armour": 10, "links": 4,
              "socket_group": "BBBB", "area_level": 40}, False),
            ({"class": "Gloves", "basetype": "Chain Gloves", "rarity": "Normal", "armour": 5, "es": 5, "links": 4,
              "socket_group": "BBBB", "area_level": 40}, True),
            ({"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Normal", "evasion": 10, "links": 3,
              "socket_group": "RRG", "area_level": 25}, False),
        ]:
            self.assertEqual(fs.visible(blocks, {**camp, **item}), shown, item)
        # link_classes = []: every class again
        self.cfg["leveling"]["link_classes"] = []
        axe3 = {**camp, "class": "Two Hand Axes", "basetype": "Stone Axe", "rarity": "Rare", "links": 3,
                "socket_group": "RRR", "area_level": 10}
        self.assertTrue(fs.visible(self.build()[0], axe3))
        self.cfg["leveling"]["link_classes"] = ["Body Armours", "Gloves", "Helmets", "Shields"]
        blocks, _ = self.build()
        # jewels always shown in the campaign (show_jewels); campaign chromatic recipe on
        rgb = {"class": "Gloves", "basetype": "Rawhide Gloves", "rarity": "Normal", "evasion": 10,
               "socket_group": "RGB", "sockets": 3, "links": 3}
        for item, shown in [
            ({"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Magic"}, True),
            ({"class": "Abyss Jewels", "basetype": "Murderous Eye Jewel", "rarity": "Rare"}, True),
            (rgb, True),
        ]:
            self.assertEqual(fs.visible(blocks, {**camp, **item}), shown, item)
        self.assertEqual(fs.evaluate(blocks, {**camp, **rgb})[0].comment, "vendor recipe: chromatic_campaign")
        self.assertFalse(fs.visible(blocks, rgb))  # maps: endgame chromatic (off)
        self.cfg["leveling"]["show_jewels"] = False
        self.cfg["vendor_recipes"]["chromatic_campaign"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, {**camp, "class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Magic"}))
        self.assertFalse(fs.visible(blocks, {**camp, **rgb}))
        # maps untouched
        self.assertFalse(fs.visible(blocks, {"class": "Rings", "basetype": "Bone Ring", "rarity": "Normal"}))

    def test_league_start_shows_almost_everything(self):
        add_exchange(self.data, "Currency", "Cheap Shard", 0.01)
        add_unique(self.data, "Gold Ring", "Junk Ring", 0.1)
        self.cfg["show_gold"] = True
        self.cfg["league_start"] = True
        self.cfg = bf.apply_league_start(self.cfg)
        blocks, _ = self.build()
        for item in [
            {"class": "Stackable Currency", "basetype": "Cheap Shard"},
            {"class": "Stackable Currency", "basetype": "Scroll of Wisdom"},
            {"class": "Rings", "basetype": "Gold Ring", "rarity": "Unique"},
            {"class": "Maps", "basetype": "Map (Tier 1)", "rarity": "Normal"},
            {"class": "Skill Gems", "basetype": "Fireball"},
            {"class": "Stackable Currency", "basetype": "Gold", "stack": 10},
        ]:
            self.assertTrue(fs.visible(blocks, item), item)

    def test_unpriced_currency_uses_reference_tier(self):
        # league start: poe.ninja empty -> NeverSink tier, not blue unknown
        self.cfg["exchange"]["unpriced_currency"] = "reference"
        blocks, _ = self.build()
        b, _ = fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": "Exalted Orb"})
        self.assertIn("reference tier", b.comment)
        self.assertTrue(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Exalted Orb"}))

    @unittest.skipUnless((ROOT / "reference/regular-neversink.filter").exists(), "no reference/ exports")
    def test_fallback_tiers_file_matches_reference_import(self):
        # fallback_tiers.toml (what the build reads) == a fresh import of the NeverSink exports,
        # and fallback_tiers() maps it like the old build-time parse (first mapped group wins)
        sys.path.insert(0, str(ROOT / "tools"))
        import import_fallback_tiers as imp
        cfg = bf.load_cfg()
        currency = imp.parse_currency(cfg, (ROOT / "reference/league.filter").read_text(encoding="utf-8"))
        cards = imp.parse_cards(cfg, (ROOT / "reference/regular-neversink.filter").read_text(encoding="utf-8"))
        self.assertEqual(cfg["fallback_tiers"]["currency"], currency, "rerun tools/import_fallback_tiers.py")
        self.assertEqual(cfg["fallback_tiers"]["cards"], cards, "rerun tools/import_fallback_tiers.py")
        ex = cfg["exchange"]
        self.assertEqual(bf.fallback_tiers(cfg, "currency"),
                         {n: ex["reference_currency_tiers"][g] for n, g in currency.items()})
        self.assertEqual(bf.fallback_tiers(cfg, "cards"), {n: ex["reference_card_tiers"][g] for n, g in cards.items()})
        self.assertGreater(len(currency), 300)
        self.assertGreater(len(cards), 300)

    def test_fallback_tiers_come_from_data_file(self):
        self.cfg["fallback_tiers"] = {"currency": {"Fake Orb": "1"}, "cards": {"Fake Card": "t1"}}
        self.cfg["exchange"]["unpriced_currency"] = "reference"
        blocks, r = self.build()
        self.assertEqual(r["ref_currency"], {"Fake Orb": "top"})
        self.assertEqual(r["ref_cards"], {"Fake Card": "top"})
        self.assertIn("reference tier top", fs.evaluate(blocks, {"class": "Stackable Currency", "basetype": "Fake Orb"})[0].comment)
        self.assertIn("reference tier top", fs.evaluate(blocks, {"class": "Divination Cards", "basetype": "Fake Card"})[0].comment)

    def test_big_stacks_priced_past_max_stack(self):
        # lifeforce drops in hundreds: 0.02c x 1250 = 25c (high), not hidden like one 0.02c piece
        add_exchange(self.data, "Currency", "Wild Crystallised Lifeforce", 0.02)
        life = lambda n: {"class": "Stackable Currency", "basetype": "Wild Crystallised Lifeforce", "stack": n}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, life(40)))
        self.assertTrue(fs.visible(blocks, life(50)))  # 1c = low
        self.assertEqual(fs.evaluate(blocks, life(1250))[0].comment, "high stack x1250")
        self.cfg["exchange"]["big_stacks"] = {}
        self.assertFalse(fs.visible(self.build()[0], life(1250)))  # max_stack 40 only

    def test_show_stacks_forced(self):
        # [exchange.show_stacks]: Rogue's Marker >= 2500 shown even when price x stack is hidden
        add_exchange(self.data, "Currency", "Rogue's Marker", 0.0001)
        rm = lambda n: {"class": "Stackable Currency", "basetype": "Rogue's Marker", "stack": n}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, rm(2499)))
        b, _ = fs.evaluate(blocks, rm(2500))
        self.assertEqual((b.action, b.comment), ("Show", "low stack x2500"))
        self.data = empty_data()                                    # unpriced: still forced
        blocks, _ = self.build()
        self.assertIn("show_stacks", fs.evaluate(blocks, rm(2500))[0].comment)
        add_exchange(self.data, "Currency", "Rogue's Marker", 0.02)  # 2500 x 0.02 = 50c: price tier wins
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, rm(2500))[0].comment, "high stack x1250")
        self.cfg["exchange"]["show_stacks"] = {}
        self.data = empty_data()
        add_exchange(self.data, "Currency", "Rogue's Marker", 0.0001)
        self.assertFalse(fs.visible(self.build()[0], rm(2500)))

    def test_unknown_gems_blue(self):
        # gem poe.ninja doesn't list (new exceptional support): blue; listed + cheap: hidden
        self.data["stash"]["SkillGem"] = {"lines": [
            {"name": "Fireball", "gemLevel": 1, "chaosValue": 0.1, "listingCount": 500}]}
        new = {"class": "Support Gems", "basetype": "Transfusion Support"}
        cheap = {"class": "Skill Gems", "basetype": "Fireball"}
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, new)[0].comment, "gem not on poe.ninja (variable)")
        self.assertFalse(fs.visible(blocks, cheap))
        self.cfg["league_start"] = True
        self.cfg = bf.apply_league_start(self.cfg)
        self.assertTrue(fs.visible(self.build()[0], cheap))

    def test_unpriced_tiers_variable_omens(self):
        # thin omens league.filter shows: blue, never hidden by their NeverSink fallback group
        omen = {"class": "Stackable Currency", "basetype": "Omen of Refreshment"}
        blocks, _ = self.build()
        b, _ = fs.evaluate(blocks, omen)
        self.assertEqual(b.comment, "unpriced currency, config tier variable")
        add_exchange(self.data, "Omen", "Omen of Refreshment", 0.01)  # confident cheap price: hidden
        self.assertFalse(fs.visible(self.build()[0], omen))

    def test_card_fallback_stack(self):
        # unpriced card in a hidden NeverSink group: x3 stack shown (league.filter exstack)
        card = lambda n: {"class": "Divination Cards", "basetype": "Loyalty", "stack": n}
        blocks, r = self.build()
        self.assertEqual(r["ref_cards"]["Loyalty"], "hide")
        self.assertFalse(fs.visible(blocks, card(2)))
        self.assertTrue(fs.visible(blocks, card(3)))
        self.assertIn("stack x3", fs.evaluate(blocks, card(3))[0].comment)
        self.cfg["exchange"]["card_fallback_stack"] = 0
        self.assertFalse(fs.visible(self.build()[0], card(3)))

    def test_reference_currency_stacks(self):
        # unpriced, NeverSink t5 / t6 (brown / dust = hidden): x5 / x14 stacks shown ([3901])
        self.cfg["exchange"]["unpriced_currency"] = "reference"
        cur = lambda name, n: {"class": "Stackable Currency", "basetype": name, "stack": n}
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, cur("Orb of Binding", 4)))
        self.assertTrue(fs.visible(blocks, cur("Orb of Binding", 5)))
        self.assertFalse(fs.visible(blocks, cur("Astragali", 13)))
        self.assertTrue(fs.visible(blocks, cur("Astragali", 14)))
        self.assertFalse(fs.visible(blocks, cur("Scroll of Wisdom", 40)))  # t9: never
        add_exchange(self.data, "Currency", "Orb of Binding", 0.01)  # confident cheap price decides
        self.assertFalse(fs.visible(self.build()[0], cur("Orb of Binding", 5)))

    def test_unpriced_cheap_currency_hidden(self):
        # league.filter hides these (no poe.ninja price): [exchange.unpriced_tiers] "hide"
        blocks, _ = self.build()
        for name in ("Scroll Fragment", "Amber Oil", "Verdant Oil"):
            self.assertFalse(fs.visible(blocks, {"class": "Stackable Currency", "basetype": name}), name)

    def test_unique_exceptions(self):
        # variants a per-base price can't see: shown although the base is priced hidden
        add_unique(self.data, "Glorious Plate", "Kaom's Heart", 0.1, item_type="BodyArmour", t="UniqueArmour")
        add_unique(self.data, "Bone Circlet", "Some Circlet", 0.1, item_type="Helmet", t="UniqueArmour")
        kaom = dict(unid_unique("Glorious Plate", "Body Armours"), sockets=0)
        circlet = dict(unid_unique("Bone Circlet", "Helmets"), sockets=4, socket_colours="AAAA")
        vestigial = dict(unid_unique("Bone Circlet", "Helmets"), vestigial=True)
        blocks, r = self.build()
        self.assertTrue(bf.hidden(self.cfg, r["ubases"]["Glorious Plate"][0]))
        self.assertTrue(fs.visible(blocks, kaom))
        self.assertFalse(fs.visible(blocks, dict(kaom, sockets=6)))
        self.assertTrue(fs.visible(blocks, circlet))
        self.assertFalse(fs.visible(blocks, dict(circlet, socket_colours="AAA")))
        self.assertTrue(fs.visible(blocks, vestigial))
        self.assertIn("module unique_exceptions", fs.evaluate(blocks, kaom)[0].comment)
        # [4804] overqual (ours 21%): 21%+ quality unique on a hidden base shown (blue), 20% stays hidden
        oq = dict(unid_unique("Glorious Plate", "Body Armours"), sockets=6)  # sockets: not exkaom
        self.assertIn("uniques.overqual", fs.evaluate(blocks, dict(oq, quality=21))[0].comment)
        self.assertFalse(fs.visible(blocks, dict(oq, quality=20)))
        self.cfg["overquality"]["uniques_21"] = False  # config.toml [overquality] toggle
        self.assertFalse(fs.visible(self.build()[0], dict(oq, quality=21)))
        self.cfg["overquality"]["uniques_21"] = True
        # a base priced in a shown tier keeps its price style
        self.data = empty_data()
        add_unique(self.data, "Glorious Plate", "Kaom's Heart", 500, item_type="BodyArmour", t="UniqueArmour")
        self.assertIn("uniques top", fs.evaluate(self.build()[0], kaom)[0].comment)
        # toggle, enabled = false, league_start (off blocks on: 5L unique)
        self.data = empty_data()
        add_unique(self.data, "Glorious Plate", "Kaom's Heart", 0.1, item_type="BodyArmour", t="UniqueArmour")
        self.cfg["modules"]["unique_exceptions"]["blocks"]["uniques.exkaom"] = False
        self.assertFalse(fs.visible(self.build()[0], kaom))
        self.cfg["modules"]["unique_exceptions"]["blocks"]["uniques.exkaom"] = True
        self.cfg["unique_exceptions"]["enabled"] = False
        self.assertFalse(fs.visible(self.build()[0], kaom))
        self.cfg["unique_exceptions"]["enabled"] = True
        five = dict(unid_unique("Glorious Plate", "Body Armours"), sockets=5, links=5)
        self.assertFalse(fs.visible(self.build()[0], five))
        self.assertNotIn("uniques.5link", bf.emit_unique_exceptions(self.cfg))
        self.cfg["league_start"] = True
        ls = bf.apply_league_start(copy.deepcopy(self.cfg))
        self.assertIn("uniques.5link", bf.emit_unique_exceptions(ls))  # off blocks on at league start

    def test_maps_follow_league_filter(self):
        # special maps always shown; normal tiers per [maps] progression; league_start -> all
        valdo = {"class": "Maps", "basetype": "Valdo Map", "rarity": "Rare", "map_tier": 17}
        blighted = {"class": "Maps", "basetype": "Map (Tier 3)", "map_tier": 3, "blighted": True}
        unique = {"class": "Maps", "basetype": "Map (Tier 16)", "map_tier": 16, "rarity": "Unique"}
        t1 = lambda area: {"class": "Maps", "basetype": "Map (Tier 1)", "map_tier": 1, "area_level": area}
        for mode, shown in [("none", (False, False)), ("auto", (True, False)), ("all", (True, True))]:
            self.cfg["maps"] = {"progression": mode}
            blocks, _ = self.build()
            self.assertTrue(fs.visible(blocks, valdo))
            self.assertTrue(fs.visible(blocks, blighted))
            self.assertFalse(fs.visible(blocks, unique))  # uniques.hide_maps: uncorrupted hidden
            self.assertTrue(fs.visible(blocks, dict(unique, corrupted=True)))
            self.assertEqual((fs.visible(blocks, t1(68)), fs.visible(blocks, t1(72))), shown, mode)
        self.cfg["maps"] = {"progression": "all", "corrupted_min_tier": 16}
        blocks, _ = self.build()
        mod8 = {"class": "Maps", "rarity": "Rare", "corrupted": True, "identified": True, "mods": ["a"] * 8}
        self.assertFalse(fs.visible(blocks, dict(mod8, basetype="Map (Tier 15)", map_tier=15)))
        self.assertTrue(fs.visible(blocks, dict(mod8, basetype="Map (Tier 16)", map_tier=16)))
        self.assertFalse(fs.visible(blocks, dict(t1(68), corrupted=True)))   # progression tier too
        self.assertTrue(fs.visible(blocks, t1(68)))
        self.assertTrue(fs.visible(blocks, dict(valdo, corrupted=True, map_tier=1)))
        self.assertTrue(fs.visible(blocks, dict(unique, corrupted=True, map_tier=1)))
        self.cfg["maps"] = {"progression": "none"}
        self.cfg["league_start"] = True
        self.cfg = bf.apply_league_start(self.cfg)
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, t1(83)))

    def test_league_start_hides_whites_build_never_uses(self):
        for name, chaos, item_type in [("Imbued Wand", 2, "Wand"), ("Glorious Plate", 2, "Body Armour"),
                                       ("Profane Wand", 500, "Wand")]:
            self.data["stash"]["BaseType"]["lines"].append({"name": name, "levelRequired": 82, "chaosValue": chaos,
                                                            "listingCount": 50, "count": 10, "itemType": item_type})
        self.cfg["league_start"] = True
        self.cfg["leveling"]["build"] = "rf"
        self.cfg = bf.apply_league_start(self.cfg)
        blocks, _ = self.build()
        wand = {"class": "Wands", "basetype": "Imbued Wand", "rarity": "Normal", "ilvl": 84}
        for item, shown in [
            (wand, False),                                      # rf never uses wands
            (dict(wand, rarity="Rare"), True),                  # only whites
            (dict(wand, basetype="Profane Wand"), True),        # worth bases.min_tier: still shown
            ({"class": "Body Armours", "basetype": "Glorious Plate", "rarity": "Normal", "ilvl": 84,
              "armour": 500}, True),
        ]:
            self.assertEqual(fs.visible(blocks, item), shown, item)

    def test_unknown_currency_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Orb Of Next League"}))

    def test_special_items_shown(self):
        self.cfg["show_6_links"] = True
        add_exchange(self.data, "Currency", "Mirror of Kalandra", 100000)
        blocks, _ = self.build()
        for item in [
            {"class": "Stackable Currency", "basetype": "Mirror of Kalandra"},
            {"class": "Stackable Currency", "basetype": "Divine Orb"},
            {"class": "Body Armours", "basetype": "Astral Plate", "rarity": "Rare", "links": 6},
            {"class": "Quest Items", "basetype": "Some Quest Thing"},
            {"class": "Some Future Class", "basetype": "Thing"},
        ]:
            self.assertTrue(fs.visible(blocks, item), item)

    def test_vendor_grasping_mail_toggle(self):
        # wiki: any rarity incl. unique, unidentified / corrupted / split all fine
        ring = {"class": "Rings", "basetype": "Organic Ring", "rarity": "Normal", "ilvl": 75}
        recipe = [ring, dict(ring, corrupted=True), dict(ring, rarity="Rare", corrupted=True),
                  dict(ring, rarity="Magic", mirrored=True), dict(ring, rarity="Unique")]
        rec = self.cfg["vendor_recipes"]["grasping_mail"]
        rec["enabled"] = True
        blocks, _ = self.build()
        for item in recipe:
            block, style = fs.evaluate(blocks, item)
            self.assertTrue(block.comment.startswith("vendor recipe: grasping_mail"), item)
            self.assertTrue(any(l.startswith("MinimapIcon") and l.endswith("Diamond") for l in style), item)
        block, _ = fs.evaluate(blocks, dict(ring, basetype="Formless Ring"))
        self.assertFalse(block and block.comment.startswith("vendor recipe"))  # not an ingredient

        rec["enabled"] = False
        blocks, _ = self.build()
        for item in recipe:
            block, _ = fs.evaluate(blocks, item)
            self.assertFalse(block and block.comment.startswith("vendor recipe"), item)

    def test_tier_order_variable_after_minor(self):
        tiers = bf.Tiers(self.cfg)
        self.assertEqual(tiers.order, ["top", "high", "mid", "minor", "variable", "low", "brown", "dust",
                                       "unknown", "hide"])
        self.cfg["variable_after"] = "top"
        self.assertEqual(bf.Tiers(self.cfg).order[:3], ["top", "variable", "high"])

    def test_vendor_recipe_tier_is_floor(self):
        # Fugitive Ring unique = tink, Enthalpic Ring unique = junk: corrupted, both are recipe ingredients.
        # Tink keeps its tink; junk (hidden by price) gets the recipe tier instead of hiding.
        add_unique(self.data, "Fugitive Ring", "Sundered", 100000, item_type="Ring")
        add_unique(self.data, "Enthalpic Ring", "Xoph", 1, item_type="Ring")
        rec = self.cfg["vendor_recipes"]["grasping_mail"]
        rec.update(enabled=True, tier="minor")
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Fugitive Ring"][0], "top")
        self.assertEqual(r["ubases"]["Enthalpic Ring"][0], "hide")
        fug = dict(unid_unique("Fugitive Ring", "Rings"), corrupted=True)
        enth = dict(unid_unique("Enthalpic Ring", "Rings"), corrupted=True)
        self.assertEqual(fs.evaluate(blocks, fug)[0].comment, "uniques top")
        b, style = fs.evaluate(blocks, enth)
        self.assertEqual(b.comment, "vendor recipe: grasping_mail (uniques not worth more)")
        self.assertTrue(any(l.endswith("Diamond") for l in style))
        # rare ring: recipe tier; uncorrupted unique junk is an ingredient too (any state)
        self.assertTrue(fs.evaluate(blocks, dict(fug, rarity="Rare"))[0].comment.startswith("vendor recipe"))
        self.assertTrue(fs.evaluate(blocks, unid_unique("Enthalpic Ring", "Rings"))[0].comment.startswith("vendor recipe"))
        rec["enabled"] = False
        self.assertFalse(fs.visible(self.build()[0], unid_unique("Enthalpic Ring", "Rings")))
        rec["enabled"] = True
        # variable recipe (ranks after minor): junk goes blue, mid + tink keep their tier
        add_unique(self.data, "Synaptic Ring", "Esh", 50, item_type="Ring")
        rec["tier"] = "variable"
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, fug)[0].comment, "uniques top")
        syn = bf.Tiers(self.cfg).of(50)
        self.assertIn(syn, ("high", "mid", "minor"))
        self.assertEqual(fs.evaluate(blocks, unid_unique("Synaptic Ring", "Rings"))[0].comment, f"uniques {syn}")
        b, style = fs.evaluate(blocks, unid_unique("Enthalpic Ring", "Rings"))
        self.assertTrue(b.comment.startswith("vendor recipe"))
        self.assertIn("PlayEffect Blue", style)
        with self.assertRaises(ValueError):
            rec["tier"] = "hide"
            self.build()

    def test_ninja_type_lists_disjoint(self):
        # each poe.ninja category handled in exactly one way
        self.assertEqual(len(bf.NINJA_TYPES), len(set(bf.NINJA_TYPES)))

    def test_cluster_jewels_neversink_eco_tiers(self):
        blocks, _ = self.build()
        large = lambda ilvl, n, node: {"class": "Jewels", "basetype": "Large Cluster Jewel", "rarity": "Normal",
                                       "ilvl": ilvl, "cluster_passives": n, "cluster_node": node}
        self.assertTrue(fs.visible(blocks, large(84, 12, "Minion Damage")))    # [2805] eco tier
        self.assertTrue(fs.visible(blocks, large(84, 8, "Fire Damage")))       # [2806] optimal ilvl 84
        self.assertFalse(fs.visible(blocks, large(70, 9, "Attack Damage")))    # [2806] junk Hide
        b, _ = fs.evaluate(blocks, large(70, 9, "Attack Damage"))
        self.assertIn("cluster", b.comment)
        small = {"class": "Jewels", "basetype": "Small Cluster Jewel", "rarity": "Magic", "ilvl": 84,
                 "cluster_passives": 2, "cluster_node": "No Such Node"}
        self.assertFalse(fs.visible(blocks, small))                            # highsmall off in FilterBlade
        self.cfg["league_start"] = True       # LS: every Show on, except [2805] empty eco tiers
        blocks, _ = self.build()
        self.assertIn("jewels->cluster.highsmall", fs.evaluate(blocks, small)[0].comment)
        self.assertFalse(any("clustereco.n2_i84_t1" in b.comment for b in blocks))

    def test_cluster_price_icon_pentagon(self):
        tiers = bf.Tiers(self.cfg)
        prices = {(t, "Large Cluster Jewel", 8, 84, None, "Fire Damage"): 1 for t in ("high", "top")}
        blocks = fs.parse(bf.emit_cluster_prices(self.cfg, tiers, prices))
        icons = {b.comment.split()[1]: [l for l in b.style if l.startswith("MinimapIcon")] for b in blocks}
        self.assertTrue(icons["high"][0].endswith("Pentagon"))
        self.assertTrue(icons["top"][0].endswith("Star"))   # tink keeps Star

    def test_very_expensive_items_tink(self):
        # every kind of item worth >= top tier (and the always-tink ones) must get the tink look,
        # not just be visible: an earlier block with its own style must not catch it
        big = 600  # > FIXED_TIERS top (125c)
        add_exchange(self.data, "Currency", "Mirror of Kalandra", 9000)  # cards priced via reward chain
        add_exchange(self.data, "DivinationCard", "House of Mirrors", 100000)
        self.cfg["show_6_links"] = True  # off in our config.toml; on, it must tink
        for t, name in [("Currency", "Fake Orb"), ("Scarab", "Fake Scarab"),
                        ("Fragment", "Fake Fragment"), ("Essence", "Fake Essence"), ("Omen", "Fake Omen")]:
            add_exchange(self.data, t, name, big)
        add_unique(self.data, "Gold Ring", "Pricey", big, item_type="Ring")
        self.data["stash"]["BaseType"]["lines"].append(
            {"name": "Some Base", "levelRequired": 86, "chaosValue": big, "listingCount": 69, "count": 10,
             "itemType": "Ring"})
        enchant, node = next(iter(bf.CLUSTER_NODES.items()))
        self.data["stash"]["ClusterJewel"]["lines"].append(
            {"name": enchant, "baseType": "Large Cluster Jewel", "variant": "8 passives", "levelRequired": 84,
             "chaosValue": big, "listingCount": 100})
        self.data["stash"]["SkillGem"]["lines"].append(
            {"name": "Fake Support", "gemLevel": 21, "gemQuality": 20, "corrupted": True, "chaosValue": big,
             "listingCount": 100})
        blocks, _ = self.build()
        stack = lambda cls, name: {"class": cls, "basetype": name, "stack": 1}
        bow = {"class": "Bows", "basetype": "Spine Bow", "rarity": "Normal", "quality": 30}
        items = [
            ("Fake Orb", stack("Stackable Currency", "Fake Orb")),
            ("House of Mirrors (reward chain)", stack("Divination Cards", "House of Mirrors")),
            ("The Endless Darkness (NeverSink top group, unpriced)", stack("Divination Cards", "The Endless Darkness")),
            ("Fake Scarab", stack("Map Fragments", "Fake Scarab")),
            ("Fake Fragment", stack("Map Fragments", "Fake Fragment")),
            ("Fake Essence", stack("Stackable Currency", "Fake Essence")),
            ("Fake Omen", stack("Stackable Currency", "Fake Omen")),
            ("unique Gold Ring", unid_unique("Gold Ring", "Rings")),
            ("base Some Base ilvl86", {"class": "Rings", "basetype": "Some Base", "rarity": "Rare", "ilvl": 86}),
            ("cluster", {"class": "Jewels", "basetype": "Large Cluster Jewel", "rarity": "Normal", "ilvl": 84,
                         "cluster_passives": 8, "cluster_node": node}),
            ("gem 21/20c", {"class": "Support Gems", "basetype": "Fake Support", "gem_level": 21, "quality": 20,
                            "corrupted": True}),
            # always tink, priced or not
            ("Divine Orb", stack("Stackable Currency", "Divine Orb")),
            ("Mirror of Kalandra", stack("Stackable Currency", "Mirror of Kalandra")),
            ("Hinekora's Lock", stack("Stackable Currency", "Hinekora's Lock")),
            ("6-link", {"class": "Body Armours", "basetype": "Simple Robe", "rarity": "Rare", "ilvl": 84,
                        "links": 6, "sockets": 6}),
            ("30% bow ilvl 70", dict(bow, ilvl=70)),
            ("30% bow ilvl 84 (perfection base)", dict(bow, ilvl=84)),
            ("30% rare body armour", {"class": "Body Armours", "basetype": "Vaal Regalia", "rarity": "Rare",
                                      "ilvl": 86, "quality": 30}),
        ] + [(c, {"class": c, "basetype": "Fake " + c}) for c in self.cfg["always_top_classes"]]
        bad = not_tink(blocks, self.cfg, items)
        self.assertFalse(bad, "not tink:\n" + "\n".join(f"  {lab}  <- {b}" for lab, b in bad))

    def test_jewels_module(self):
        blocks, _ = self.build()
        cobalt = {"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Rare", "ilvl": 84,
                  "corrupted": True, "corrupted_mods": 1}
        abyss = {"class": "Abyss Jewels", "basetype": "Searching Eye Jewel", "rarity": "Rare", "ilvl": 86}
        b, style = fs.evaluate(blocks, cobalt)                                      # [2801] corrupted implicit
        self.assertIn("jewel jewels->special.1modcorrupted", b.comment)
        self.assertIn("PlayEffect Blue", style)                                     # league.filter style
        self.assertTrue(fs.visible(blocks, dict(cobalt, rarity="Magic")))          # [2801] magic
        self.assertTrue(fs.visible(blocks, {**cobalt, "corrupted": False, "corrupted_mods": 0, "identified": True,
                                            "mods": ["Vivid"]}))                    # [2801] top mod
        self.assertTrue(fs.visible(blocks, abyss))                                  # [2803] ilvl 86
        self.assertTrue(fs.visible(blocks, dict(abyss, ilvl=70, corrupted=True)))  # [2803] corrupted rare
        b, _ = fs.evaluate(blocks, dict(abyss, ilvl=70))
        self.assertEqual((b.action, b.comment), ("Hide", "jewel jewels->abyss.anyrare (module jewels)"))
        b, _ = fs.evaluate(blocks, {**cobalt, "corrupted": False, "corrupted_mods": 0})
        self.assertEqual((b.action, b.comment), ("Hide", "jewel jewels->generic.anyrare (module jewels)"))
        self.cfg["modules"]["jewels"]["blocks"]["jewels->special.1modcorrupted"] = False  # per-block toggle
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, cobalt))
        self.cfg["league_start"] = True                                             # LS: every Show on
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, cobalt))
        self.cfg["league_start"] = False
        self.cfg["jewels"]["enabled"] = False
        blocks, _ = self.build()
        self.assertNotIn("jewel", fs.evaluate(blocks, abyss)[0].comment)
        self.assertFalse(fs.visible(blocks, abyss))                                 # bottom: hide gear

    def test_heist_module(self):
        blocks, _ = self.build()
        cloak = lambda base, **kw: {"class": "Heist Cloaks", "basetype": base, "rarity": "Normal", "ilvl": 84, **kw}
        b, style = fs.evaluate(blocks, cloak("Whisper-woven Cloak"))                # [2901] t1 ilvl 83+
        self.assertIn("heist heist->cloak.t1highlevel", b.comment)
        self.assertIn("PlayEffect Yellow", style)
        self.assertTrue(fs.visible(blocks, cloak("Hooded Cloak", rarity="Rare")))  # t2
        self.assertTrue(fs.visible(blocks, {"class": "Heist Tools", "basetype": "Master Lockpick",
                                            "rarity": "Magic", "ilvl": 70}))        # [2904] t1
        b, _ = fs.evaluate(blocks, cloak("Torn Cloak"))
        self.assertEqual((b.action, b.comment), ("Hide", "heist heist->cloak.t3any (module heist)"))
        self.cfg["modules"]["heist"]["blocks"]["heist->cloak.t2"] = False           # per-block toggle
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, cloak("Hooded Cloak")))
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, cloak("Hooded Cloak")))
        self.cfg["league_start"] = False
        self.cfg["heist"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, cloak("Whisper-woven Cloak")))         # bottom: hide gear

    def test_misc_module(self):
        # [4500] heist targets, [4600] enshrouded, [4700] idols, [4900] questlike: shown, own look
        blocks, _ = self.build()
        idol = lambda base, rarity: {"class": "Idols", "basetype": base, "rarity": rarity}
        for item, key in [
            ({"class": "Heist Targets", "basetype": "Golden Grail", "rarity": "Unique"}, "heisttarget.any"),
            ({"class": "Helmets", "basetype": "Enshrouded Helmet", "rarity": "Normal"}, "enshrouded.enshroudedgear"),
            (idol("Minor Idol", "Rare"), "event->idols.minorrare"),
            (idol("Conqueror Idol", "Magic"), "event->idols.conquerormagic"),
            (idol("Noble Idol", "Normal"), "event->idols.normalidols"),
            ({"class": "Labyrinth Items", "basetype": "Golden Key"}, "questlike.labyrinthconsumable"),
            ({"class": "Incursion Items", "basetype": "Stone of Passage"}, "questlike.incursionconsumable"),
            ({"class": "Misc Map Items", "basetype": "Maven's Invitation: The Feared"}, None),  # unpriced fallback
        ]:
            b, _ = fs.evaluate(blocks, item)
            self.assertTrue(fs.visible(blocks, item), item)
            if key:
                self.assertEqual(b.comment, f"misc {key} (module misc)")
        # price decides first: a cheap-priced Maven's item stays hidden
        add_exchange(self.data, "Currency", "Maven's Chisel of Junk", 0.001)
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Maven's Chisel of Junk"}))
        # per-block toggle off -> gear hide layer / bottom hides it; league_start turns it back on
        self.cfg["modules"]["misc"]["blocks"]["event->idols.minorrare"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, idol("Minor Idol", "Rare")))
        self.assertTrue(fs.visible(blocks, idol("Minor Idol", "Magic")))
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, idol("Minor Idol", "Rare")))
        self.cfg["league_start"] = False
        self.cfg["misc"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, idol("Minor Idol", "Magic")))
        self.assertTrue(fs.visible(blocks, {"class": "Heist Targets", "basetype": "Golden Grail"}))  # blue net

    def test_misc_gold_tiers(self):
        gold = lambda stack, area=83: {"class": "Stackable Currency", "basetype": "Gold", "stack": stack,
                                       "area_level": area}
        self.cfg["gold_min_stack"] = 10000
        self.cfg["show_gold"] = False  # explicit config hides every stack
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gold(50000)))
        self.cfg["show_gold"] = True
        blocks, _ = self.build()
        b, _ = fs.evaluate(blocks, gold(10000))
        self.assertEqual(b.comment, "gold >= 10000 (config.toml gold_min_stack)")
        self.assertFalse(fs.visible(blocks, gold(9999)))                # below gold_min_stack in maps
        self.assertFalse(fs.visible(blocks, gold(5000)))                # FilterBlade's 3001+ tier: not ours
        self.assertTrue(fs.visible(blocks, gold(10, area=20)))          # campaign: every stack
        self.cfg["gold_min_stack"] = 3000                                # one key moves the line
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, gold(5000)))
        self.assertFalse(fs.visible(blocks, gold(2999)))
        self.cfg["misc"]["enabled"] = False                              # module toggle doesn't touch gold
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gold(2999)))
        self.cfg["league_start"] = True                                  # no gold Hide
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, gold(10)))

    def test_map_items_module(self):
        # [[3400]] / [[3500]]: league.filter's look where no price exists; a price decides first
        self.cfg["hide_forbidden_tome"] = False
        add_exchange(self.data, "Fragment", "Voidborn Reliquary Key", 0.01)
        blocks, _ = self.build()
        key = {"class": "Vault Keys", "basetype": "Lonely Reliquary Key"}
        b, style = fs.evaluate(blocks, key)                        # always_top_classes: first, top style
        self.assertEqual(b.comment, "always top Vault Keys (config.toml always_top_classes)")
        self.assertEqual([l for l in style if l.startswith("PlayAlertSound")],
                         [l for l in bf.style_for(self.cfg, "top") if l.startswith("PlayAlertSound")])
        for item in [{"class": "Expedition Logbooks", "basetype": "Expedition Logbook", "rarity": "Magic"},
                     {"class": "Chart", "basetype": "Some Chart", "rarity": "Rare"},
                     {"class": "Blueprints", "basetype": "Blueprint: Bunker", "rarity": "Rare"},
                     {"class": "Blueprints", "basetype": "Blueprint: Bunker", "rarity": "Unique"}]:
            self.assertIn("map ", fs.evaluate(blocks, item)[0].comment, item)
            self.assertTrue(fs.visible(blocks, item), item)
        voidborn = {"class": "Vault Keys", "basetype": "Voidborn Reliquary Key"}
        self.assertIn("always top", fs.evaluate(blocks, voidborn)[0].comment)        # priced junk: still top
        self.assertFalse(any("relickeys" in b.comment for b in blocks))             # module keys follow config
        tome = {"class": "Sanctum Research", "basetype": "Forbidden Tome", "ilvl": 83}
        self.assertTrue(fs.visible(blocks, tome))             # hide_forbidden_tome false beats sanctum Hide
        self.assertFalse(any("exoticmap->sanctum" in b.comment for b in blocks))
        chronicle = {"class": "Misc Map Items", "basetype": "Chronicle of Atzoatl"}
        b, _ = fs.evaluate(blocks, chronicle)                                       # unpriced fallback first
        self.assertTrue(fs.visible(blocks, chronicle))
        self.assertIn("unpriced", b.comment)
        self.cfg["overrides"] = {"Voidborn Reliquary Key": "hide"}                 # beats [overrides]
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, voidborn))
        self.cfg["always_top_classes"] = []                                         # off: price decides
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, voidborn))

    def test_maps_module_toggles(self):
        valdo = {"class": "Maps", "basetype": "Valdo Map", "rarity": "Rare", "map_tier": 17}
        implicit = {"class": "Maps", "basetype": "Map (Tier 16)", "map_tier": 16, "corrupted": True,
                    "corrupted_mods": 1}
        blocks, _ = self.build()
        self.assertIn("maps->nightmare.valdomaps", fs.evaluate(blocks, valdo)[0].comment)
        self.assertFalse(fs.visible(blocks, implicit))                              # corruptedimplicit off
        self.cfg["modules"]["maps"]["blocks"]["maps->nightmare.valdomaps"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, valdo))                                 # falls to T16 tier Hide
        self.cfg["league_start"] = True
        self.cfg["maps"]["progression"] = "none"
        blocks, _ = self.build()
        self.assertIn("maps->corruptedimplicit.any", fs.evaluate(blocks, implicit)[0].comment)
        self.cfg["league_start"] = False
        self.cfg["maps"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(any(b.comment.startswith("map ") for b in blocks))

    def test_every_colour_from_palette(self):
        text, _ = bf.build_text(self.cfg, self.data, "Test")
        ours = set(self.cfg["colors"].values()) | set(bf.GAME_TEXT_COLOR.values())
        used = set(re.findall(r"Set(?:Text|Border|Background)Color (.+)", text))
        self.assertEqual(used - ours, set())

    def test_palette_names_and_snapping(self):
        cfg = {"colors": {"white": "215 215 215 255", "red": "255 0 0 255", "tink_bg": "255 255 255 255",
                          "clear": "0 0 0 0"}}
        out = bf.apply_palette(cfg, "\tSetTextColor red\n\tSetTextColor 255 255 255 255\n\tSetTextColor 220 220 220\n"
                                    "\tSetBackgroundColor 250 250 250 255\n\tSetBorderColor 220 220 220 0\n")
        self.assertEqual(out, "\tSetTextColor 255 0 0 255\n\tSetTextColor 215 215 215 255\n"
                              "\tSetTextColor 215 215 215 255\n\tSetBackgroundColor 255 255 255 255\n\tSetBorderColor 0 0 0 0\n")
        with self.assertRaises(ValueError):
            bf.apply_palette(cfg, "\tSetTextColor pink\n")

    def test_flasks_neversink_rules(self):
        blocks, _ = self.build()
        flask = lambda **kw: {"class": "Utility Flasks", "basetype": "Quicksilver Flask", "rarity": "Magic",
                              "ilvl": 83, "width": 1, "height": 2, **kw}
        self.assertTrue(fs.visible(blocks, flask(quality=21)))                      # [2502] any 21%
        self.assertTrue(fs.visible(blocks, flask(quality=30, corrupted=True)))      # corrupted 30%
        self.assertTrue(fs.visible(blocks, flask(fractured=True)))                  # [1303] fractured
        self.assertTrue(fs.visible(blocks, flask(identified=True, mods=["of the Cheetah"])))  # [0803]
        self.assertTrue(fs.visible(blocks, {"class": "Tinctures", "basetype": "Oakbranch Tincture",
                                            "rarity": "Magic", "ilvl": 82, "quality": 21}))
        self.assertFalse(fs.visible(blocks, flask(quality=10)))
        b, _ = fs.evaluate(blocks, {"class": "Jewels", "basetype": "Cobalt Jewel",
                                    "rarity": "Magic", "fractured": True})
        self.assertNotIn("flask", b.comment)                                        # flask classes only
        b, _ = fs.evaluate(blocks, flask(quality=21, rarity="Normal"))
        self.assertIn("flask", b.comment)                                           # beats glassblower
        self.cfg["flasks"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, flask(quality=21)))

    def test_exotics_memory_strands_fractured(self):
        blocks, _ = self.build()
        gear = lambda **kw: {"class": "Helmets", "basetype": "Haunted Bascinet", "rarity": "Rare",
                             "ilvl": 84, "width": 2, "height": 2, **kw}
        self.assertTrue(fs.visible(blocks, gear(memory_strands=44)))                # [0902] t1 base 15+
        b, style = fs.evaluate(blocks, gear(memory_strands=44))
        self.assertIn("exotic", b.comment)
        self.assertTrue(any(s.startswith("PlayEffect Blue") for s in style))      # league.filter style
        self.assertTrue(fs.visible(blocks, gear(basetype="Iron Hat", memory_strands=1, fractured=True)))
        self.assertFalse(fs.visible(blocks, gear(basetype="Iron Hat", memory_strands=30)))  # t3: off
        self.assertTrue(fs.visible(blocks, gear(basetype="Iron Hat", fractured=True, identified=True,
                                                mods=["Subterranean"])))          # [1105] delve fractured
        jewel = {"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Magic", "fractured": True}
        self.assertTrue(fs.visible(blocks, jewel))                                  # [1303] fractspecial
        self.assertFalse(fs.visible(blocks, gear(basetype="Iron Hat", fractured=True)))     # fractt*: off
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, gear(basetype="Iron Hat", memory_strands=30)))   # off -> on
        self.assertTrue(fs.visible(blocks, gear(basetype="Iron Hat", fractured=True)))
        self.cfg["league_start"] = False
        self.cfg["exotics"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gear(memory_strands=44)))

    def test_flasks_module_toggles(self):
        flask = {"class": "Utility Flasks", "basetype": "Quicksilver Flask", "rarity": "Magic", "ilvl": 86,
                 "width": 1, "height": 2}
        mana = {**flask, "class": "Mana Flasks", "basetype": "Divine Mana Flask", "quality": 21}
        self.cfg["overquality"]["any_flask_21"] = True
        blocks, _ = self.build()
        self.assertIn("flask endgameflasks.any20qualflask", fs.evaluate(blocks, mana)[0].comment)
        self.assertNotIn("utility85", fs.evaluate(blocks, flask)[0].comment)          # off in FilterBlade
        self.cfg["overquality"]["any_flask_21"] = False  # toggle lives in config.toml [overquality]
        blocks, _ = self.build()
        self.assertNotIn("any20qualflask", fs.evaluate(blocks, mana)[0].comment)
        self.assertTrue(fs.visible(blocks, {**flask, "fractured": True}))            # rest still on
        self.cfg["league_start"] = True                                              # LS: every Show on
        blocks, _ = self.build()
        self.assertIn("flask endgameflasks.utility85", fs.evaluate(blocks, flask)[0].comment)

    def test_exotics_module_families(self):
        """Every [[1100]] / [[1200]] / [[1300]] family shows its real-looking item via module exotics."""
        rare = lambda cls, base, **kw: {"class": cls, "basetype": base, "rarity": "Rare", "ilvl": 84,
                                        "width": 2, "height": 2, **kw}
        items = {
            "exoticmods.duoveil": rare("Rings", "Iron Ring", identified=True, mods=["Chosen's Veiled", "of the Veil"]),
            "exoticmods.incursionlifechest": rare("Body Armours", "Plate Vest", identified=True,
                                                  mods=["Guatelitzi's"]),
            "exoticmods.necropoliscraft": rare("Boots", "Iron Greaves", identified=True, mods=["Haunted"]),
            "exoticmods.bestiaryvaluable": rare("Belts", "Leather Belt", identified=True, mods=["of Farrul"]),
            "exoticmods.warband": rare("Gloves", "Iron Gauntlets", identified=True, mods=["Brinerot"]),
            "artefact->misc.anysynth": rare("Rings", "Iron Ring", synthesised=True),
            "artefact->misc.anytrinket": rare("Trinkets", "Thief's Trinket"),
            "artefact->misc.fishingrods": {"class": "Fishing Rods", "basetype": "Fishing Rod", "rarity": "Normal"},
            "artefact->misc.pieces": {"class": "Pieces", "basetype": "Fragment of the Unique",
                                      "rarity": "Unique"},
            "artefact->sanctifiedrelics.selectedrelics": rare("Relics", "Urn Relic"),
            "exotic->corruptions.doublecorruptedany": rare("Helmets", "Iron Hat", corrupted=True,
                                                           corrupted_mods=2),
            "exotic->sockets.anynonbelt": rare("Boots", "Iron Greaves", socket_group="RRA"),
            "exotic->enchanted.exotic": rare("Helmets", "Iron Hat", enchanted=True),
            "exotic->enchanted.anointedamulets": rare("Amulets", "Onyx Amulet", enchanted=True),
            "exotic->crucible.crucibleany": rare("One Hand Swords", "Rusted Sword", crucible=True),
        }
        blocks, _ = self.build()
        for key, item in items.items():
            b, style = fs.evaluate(blocks, item)
            self.assertIn(f"exotic {key}", b.comment, key)
            self.assertTrue(any(s.startswith("PlayEffect") for s in style), key)      # league.filter style
        # priced uniques stay with emit_uniques: a cheap unique rod / unique relic is no exotic
        add_unique(self.data, "Fishing Rod", "Song of the Sirens", 1, item_type="FishingRod", t="UniqueWeapon")
        blocks, _ = self.build()
        for item in ({"class": "Fishing Rods", "basetype": "Fishing Rod", "rarity": "Unique"},
                     {"class": "Relics", "basetype": "Urn Relic", "rarity": "Unique"}):
            b, _ = fs.evaluate(blocks, item)
            self.assertNotIn("module exotics", b.comment if b else "", item)
        crafted = rare("Helmets", "Iron Hat", identified=True, mods=["of Crafting"])
        self.assertNotIn("module exotics", fs.evaluate(blocks, crafted)[0].comment)          # off in FilterBlade
        self.cfg["modules"]["exotics"]["blocks"]["exotic->crucible.crucibleany"] = False  # per-block toggle
        blocks, _ = self.build()
        self.assertNotIn("module exotics", fs.evaluate(blocks, items["exotic->crucible.crucibleany"])[0].comment)
        self.assertIn("exotic", fs.evaluate(blocks, items["artefact->misc.anysynth"])[0].comment)
        self.cfg["league_start"] = True                                              # LS: every Show on
        blocks, _ = self.build()
        self.assertIn("exotic exoticmods.crafting", fs.evaluate(blocks, crafted)[0].comment)
        self.cfg["league_start"] = False
        self.cfg["exotics"]["enabled"] = False
        blocks, _ = self.build()
        for key, item in items.items():
            b, _ = fs.evaluate(blocks, item)
            self.assertNotIn("module exotics", b.comment if b else "", key)

    def test_id_mods_neversink_rules(self):
        blocks, _ = self.build()
        amu = {"class": "Amulets", "basetype": "Onyx Amulet", "rarity": "Magic", "ilvl": 84,
               "width": 1, "height": 1, "identified": True, "mods": ["Vulcanist's"]}
        b, style = fs.evaluate(blocks, amu)                                         # [0802] t2amu
        self.assertIn("idmod", b.comment)
        self.assertTrue(fs.visible(blocks, amu))
        self.assertTrue(any(s.startswith("PlayEffect Purple") for s in style))    # league.filter style
        b, _ = fs.evaluate(blocks, {**amu, "mods": ["of the Fox"]})
        self.assertNotIn("idmod", b.comment)                                        # no good mod
        b, _ = fs.evaluate(blocks, {**amu, "identified": False})
        self.assertNotIn("idmod", b.comment)
        helm = {"class": "Helmets", "basetype": "Iron Hat", "rarity": "Rare", "ilvl": 84, "width": 2,
                "height": 2, "identified": True, "mods": ["Elreon's Veiled"]}
        self.assertTrue(fs.visible(blocks, helm))                                   # [0617] veil t1
        gloves = {"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Rare", "ilvl": 84,
                  "width": 2, "height": 2, "identified": True, "corrupted": True, "corrupted_mods": 1,
                  "mods": ["Athlete's", "of the Gods", "of the Wind"]}
        b, _ = fs.evaluate(blocks, gloves)                                          # [[1000]] corrupted
        self.assertIn("idmod", b.comment)
        self.cfg["modules"]["id_mods"]["blocks"]["magicid.t2amu"] = False             # per-block toggle
        blocks, _ = self.build()
        self.assertNotIn("t2amu", fs.evaluate(blocks, amu)[0].comment)
        self.assertTrue(fs.visible(blocks, helm))
        self.cfg["league_start"] = True                                             # LS: every Show on
        blocks, _ = self.build()
        self.assertTrue(any("magicid.t2amu" in b.comment for b in blocks))
        self.cfg["league_start"] = False
        self.cfg["id_mods"]["enabled"] = False
        blocks, _ = self.build()
        b, _ = fs.evaluate(blocks, amu)
        self.assertNotIn("idmod", b.comment)

    def test_modules_keys_match_modules_toml(self):
        """Every block key of every rules/modules/*.filter is in modules.toml and vice versa
        (no hidden settings, no stale toggles); keys unique per module."""
        for path in sorted(bf.MODULES_DIR.glob("*.filter")):
            keys = [b["key"] for b in bf.load_module(path.stem)]
            self.assertEqual(len(keys), len(set(keys)), path.stem)
            self.assertEqual(set(keys), set(self.cfg["modules"][path.stem]["blocks"]), path.stem)
        self.assertEqual(set(self.cfg["modules"]), {p.stem for p in bf.MODULES_DIR.glob("*.filter")})

    def test_module_missing_key_raises(self):
        del self.cfg["modules"]["id_mods"]["blocks"]["magicid.t2amu"]
        with self.assertRaises(KeyError):
            self.build()

    def test_gear_special_module_families(self):
        """[0302] influenced / [[0400]] eldritch / [[0500]] exotic bases / [0901] perfection via
        module gear_special; priced bases keep their price tier; toggle, LS, enabled=false."""
        item = lambda cls, base, rarity="Normal", **kw: {"class": cls, "basetype": base, "rarity": rarity,
                                                         "ilvl": 84, "width": 2, "height": 2, **kw}
        items = {
            "gear influenced->all.t1basescrusader": item("Rings", "Bone Ring", "Rare", influence=["Crusader"]),
            "gear influenced->all.t1exotic": item("Helmets", "Divine Crown", "Rare", influence=["Hunter"]),
            "gear exoticbases.exoticheistbases": item("Rings", "Cogwork Ring"),
            "gear exoticbases.exoticritualbases": item("Helmets", "Demon Crown", "Magic"),
            "gear exoticbaseslower.stygian86": item("Belts", "Stygian Vise", ilvl=86),
            "perfection crafting->qualityperfection.armors1q1": item("Helmets", "Bone Helmet", quality=28),
            "perfection crafting->qualityperfection.weapont1q2": item("Wands", "Kinetic Wand", quality=24),
        }
        blocks, _ = self.build()
        for key, it in items.items():
            b, style = fs.evaluate(blocks, it)
            self.assertIn(f"{key} (module gear_special)", b.comment, key)
            self.assertTrue(any(s.startswith("PlayEffect") for s in style), key)        # league.filter style
        mod = lambda it: (fs.evaluate(blocks, it)[0] or fs.Block("Show", "", 0)).comment
        self.assertNotIn("gear_special", mod(item("Rings", "Bone Ring", "Rare")))       # not influenced
        self.assertNotIn("gear_special", mod(item("Belts", "Stygian Vise", ilvl=84)))  # "stygian" off
        self.assertNotIn("gear_special", mod(item("Helmets", "Bone Helmet", "Unique", quality=28)))  # price
        exarch = item("Helmets", "Divine Crown", "Rare", exarch_implicit=1)
        self.assertNotIn("gear_special", mod(exarch))                                   # [[0400]] off
        # FilterBlade conditional entries: decided by price / [vendor_recipes.grasping_mail]
        self.assertNotIn("gear_special", mod({"class": "Stackable Currency", "basetype": "Stacked Deck"}))
        self.assertIn("vendor recipe: grasping_mail", mod(item("Rings", "Organic Ring")))
        # confident shown-tier price wins over the module Show; a cheap price doesn't hide it
        for name, ilvl, chaos in [("Stygian Vise", 86, 600), ("Cogwork Ring", 84, 1), ("Bone Helmet", 84, 600),
                                  ("Onyx Amulet", 84, 600)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": name, "levelRequired": ilvl, "chaosValue": chaos, "listingCount": 69, "count": 10,
                 "itemType": "Belt"})
        blocks, _ = self.build()
        self.assertIn("base top ilvl86+ plain", mod(items["gear exoticbaseslower.stygian86"]))
        self.assertIn("exoticheistbases", mod(items["gear exoticbases.exoticheistbases"]))
        self.assertIn("base top ilvl84+ plain (priced", mod(item("Helmets", "Bone Helmet", "Rare")))
        self.data["stash"]["BaseType"]["lines"].append(
            {"name": "Bone Helmet", "variant": "Hunter", "levelRequired": 84, "chaosValue": 600,
             "listingCount": 69, "count": 10, "itemType": "Helmet"})
        blocks, _ = self.build()
        self.assertIn("base top ilvl84+ Hunter (priced", mod(item("Helmets", "Bone Helmet", "Rare",
                                                                  influence=["Hunter"])))  # beats t1exotic
        # ...but not id_mods / perfection / exotics: those say more than the base price
        self.assertIn("perfection crafting->qualityperfection.armors1q1", mod(items[
            "perfection crafting->qualityperfection.armors1q1"]))
        good_amu = item("Amulets", "Onyx Amulet", "Magic", width=1, height=1, identified=True, mods=["Vulcanist's"])
        self.assertIn("idmod", mod(good_amu))
        self.assertIn("base top", mod(dict(good_amu, mods=["of the Fox"])))
        self.cfg["modules"]["gear_special"]["blocks"]["influenced->all.t1basescrusader"] = False  # toggle
        blocks, _ = self.build()
        self.assertNotIn("gear_special", mod(items["gear influenced->all.t1basescrusader"]))
        self.assertIn("gear_special", mod(items["gear influenced->all.t1exotic"]))
        self.cfg["league_start"] = True                                                 # LS: every Show on
        blocks, _ = self.build()
        self.assertIn("gear rare->exarch.anyhigh (module gear_special)", mod(exarch))
        self.assertIn("module gear_special", mod(items["gear influenced->all.t1basescrusader"]))  # t1top
        self.assertFalse(any("s0500_" in b.comment for b in blocks))                   # never a block
        self.cfg["league_start"] = False
        self.cfg["gear_special"]["enabled"] = False
        blocks, _ = self.build()
        for key, it in items.items():
            self.assertNotIn("module gear_special", mod(it), key)

    def test_chromatic_recipe_sizes(self):
        """[vendor_recipes.chromatic] sizes / area_level = FilterBlade's RGB options; default any."""
        rec = self.cfg["vendor_recipes"]["chromatic"]
        self.assertEqual((rec["sizes"], rec["area_level"]), ([], []))
        rec["enabled"] = True
        rgb = lambda w, h, **kw: {"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Magic", "ilvl": 70,
                                  "width": w, "height": h, "socket_group": "RGB", "area_level": 75, **kw}
        shown = lambda it: "vendor recipe: chromatic" in (fs.evaluate(blocks, it)[0] or fs.Block("Show", "", 0)).comment
        blocks, _ = self.build()
        self.assertTrue(all(shown(rgb(w, h)) for w, h in [(2, 2), (1, 3), (2, 3), (2, 4)]))
        rec["sizes"], rec["area_level"] = ["small", "medium"], [68, 83]
        blocks, _ = self.build()
        self.assertTrue(shown(rgb(2, 2)) and shown(rgb(1, 4)) and shown(rgb(2, 3)))
        self.assertFalse(shown(rgb(2, 4)))                                           # large off
        self.assertFalse(shown(rgb(2, 2, area_level=84)))                            # outside area range
        rec["sizes"] = ["huge"]
        with self.assertRaises(ValueError):
            self.build()

    def test_crafting_module_families(self):
        """[1401] links, [2301] early crafting, [2302] matrix, [[2400]] chancing via module
        crafting; RGB / 6-socket blocks stay vendor recipes; toggle, LS, enabled=false."""
        blocks, _ = self.build()
        mod = lambda it: (fs.evaluate(blocks, it)[0] or fs.Block("Show", "", 0)).comment
        ring = {"class": "Rings", "basetype": "Amethyst Ring", "rarity": "Normal", "ilvl": 75, "area_level": 70,
                "width": 1, "height": 1}
        five = {"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Rare", "ilvl": 84, "links": 5,
                "sockets": 5, "width": 2, "height": 3}
        plate = {"class": "Body Armours", "basetype": "Royal Plate", "rarity": "Normal", "ilvl": 86,
                 "width": 2, "height": 3}
        self.assertIn("crafting normalcraft->extra.earlycraftoptional (module crafting)", mod(ring))
        self.assertNotIn("module crafting", mod(dict(ring, area_level=83)))           # area 68-75 only
        self.assertNotIn("module crafting", mod(five))                               # 5-links off
        self.assertNotIn("module crafting", mod(plate))                              # matrix off
        self.assertFalse(any(k in b.comment for b in blocks
                             for k in ("socketslinks.rgb", "socketslinks.6sockets", "endgamergb")))
        self.cfg["modules"]["crafting"]["blocks"]["socketslinks.5links"] = True      # per-block toggle
        self.cfg["modules"]["crafting"]["blocks"]["crafting->generalgear.t1_86"] = True
        self.cfg["modules"]["crafting"]["blocks"]["chancing.hh"] = True
        blocks, _ = self.build()
        self.assertIn("links socketslinks.5links (module crafting)", mod(five))
        self.assertIn("crafting crafting->generalgear.t1_86 (module crafting)", mod(plate))
        self.assertIn("crafting chancing.hh", mod({"class": "Belts", "basetype": "Heavy Belt", "rarity": "Normal",
                                                  "ilvl": 60, "width": 2, "height": 1}))
        self.cfg["modules"]["crafting"]["blocks"]["normalcraft->extra.earlycraftoptional"] = False
        blocks, _ = self.build()
        self.assertNotIn("module crafting", mod(ring))
        # RGB = [vendor_recipes.chromatic], not a module block (also with every Show on)
        self.cfg["modules"]["crafting"]["blocks"]["crafting->generalgear.t1_86"] = False
        self.cfg["vendor_recipes"]["chromatic"]["enabled"] = True
        self.cfg["league_start"] = True
        blocks, _ = self.build()
        rgb = {"class": "Gloves", "basetype": "Iron Gauntlets", "rarity": "Normal", "ilvl": 70, "width": 2,
               "height": 2, "socket_group": "RGB", "area_level": 75}
        self.assertEqual(fs.evaluate(blocks, rgb)[0].comment, "vendor recipe: chromatic")
        self.assertFalse(any(k in b.comment for b in blocks
                             for k in ("socketslinks.rgb", "socketslinks.6sockets", "endgamergb")))
        self.assertTrue(any("socketslinks.5linksleveling" in b.comment for b in blocks))  # LS: Shows on
        self.assertTrue(fs.visible(blocks, dict(five, area_level=40)))  # LS show_5_links: top.filter tink first
        self.assertNotIn("generalgear", mod(plate))                                 # [2302] not LS
        self.cfg["league_start"] = False
        self.cfg["modules"]["crafting"]["blocks"]["normalcraft->extra.earlycraftoptional"] = True
        self.cfg["crafting"]["enabled"] = False
        blocks, _ = self.build()
        self.assertFalse(any("module crafting" in b.comment for b in blocks))

    def test_mirrored_item_rule_config_toggle(self):
        item = {"class": "Rings", "basetype": "Iron Ring", "rarity": "Rare", "mirrored": True}
        self.cfg["vendor_recipes"]["grasping_mail"]["enabled"] = False
        blocks, _ = self.build()
        mirrored_rules = [  # Shows only: module rares has FilterBlade's mirrored-unID Hide
            block for block in blocks
            if block.action == "Show" and any(key == "Mirrored" and op in ("=", "==") and values == ["True"]
                   for key, op, values, _ in block.conds)
        ]
        self.assertEqual(mirrored_rules, [])

        self.cfg["show_mirrored"] = True
        blocks, _ = self.build()
        block, style = fs.evaluate(blocks, item)
        self.assertEqual(block.comment, "mirrored items (variable value)")
        self.assertIn("PlayAlertSound 2 300", style)
        self.assertIn("PlayEffect Blue", style)
        self.assertFalse(any(line in ("PlayAlertSound 6 300", "PlayEffect Red") for line in style))


# ------------------------------------------------------------------ live cache

def latest_cache():
    dirs = [d for d in (ROOT / "cache").glob("*") if (d / "st_BaseType.json").exists()]
    return max(dirs, key=lambda d: (d / "st_BaseType.json").stat().st_mtime) if dirs else None


def load_cache(d, cfg):
    rd = lambda f: json.loads((d / f).read_text(encoding="utf-8"))
    wiki = ROOT / "cache" / "wiki_uniques.json"
    rows = json.loads(wiki.read_text(encoding="utf-8")) if wiki.exists() else []
    return {"exchange": {t: rd(f"ex_{t}.json") for t in bf.EXCHANGE_TYPES},
            "stash": {t: rd(f"st_{t}.json") for t in bf.STASH_TYPES},
            "nomap": bf.non_map_drops(rows, cfg), "wiki_bases": bf.wiki_unique_bases(rows),
            "content": bf.content_bases(rows, cfg),
            "drop_anywhere": {r["name"] for r in rows if r["enabled"] and not r["restricted"]}}


CACHE = latest_cache()

CONQUERORS = ("Al-Hezmin", "Baran", "Drox", "Veritania")
ELDER_GUARDIANS = ("The Enslaver", "The Eradicator", "The Constrictor", "The Purifier")


def map_drop(name, base=None, **extra):
    """poe.ninja map line -> the map as it drops: tier from "(Tier N)" (Vaal Temple / Valdo /
    special = 16 / 17), influence from the conqueror / Elder guardian name prefix."""
    m = re.search(r"\(Tier (\d+)\)", name)
    tier = int(m.group(1)) if m else 17 if base == "Valdo Map" else 16
    infl = ["Crusader"] if name.startswith(CONQUERORS) else ["Elder"] if name.startswith(ELDER_GUARDIANS) else []
    if base is None or base.startswith("Map (Tier"):
        base = next((b for b in ("Vaal Temple Map", "Nightmare Map", "Shaper Guardian Map") if b in name),
                    f"Map (Tier {tier})")
    return dict({"class": "Maps", "basetype": base, "rarity": "Rare" if infl else "Normal",
                 "map_tier": tier, "influence": infl}, **extra)


@unittest.skipIf(CACHE is None, "no price cache, run build_filter.py once")
class LiveCache(unittest.TestCase):
    longMessage = False  # our message already lists the hidden items

    @classmethod
    def setUpClass(cls):
        cls.cfg = bf.load_cfg()
        cls.data = load_cache(CACHE, cls.cfg)
        text, cls.r = bf.build_text(cls.cfg, cls.data, CACHE.name)
        cls.blocks = fs.parse(text)
        cls.cluster_nodes = bf.module_cluster_nodes()

    def assert_all_visible(self, items, what):
        hidden = [(label, fs.evaluate(self.blocks, it)[0]) for label, it in items
                  if not fs.visible(self.blocks, it)]
        self.assertFalse(hidden, f"{len(hidden)} {what} hidden:\n" +
                         "\n".join(f"  {lab}  <- {b}" for lab, b in hidden[:40]))

    def skip_if_jackpot_only(self):
        # deliberate late-league trade: 125c+ uniques on junk bases hidden, test_no_jackpot_hidden still guards
        if self.cfg["uniques"].get("variable_jackpot_only"):
            self.skipTest("uniques.variable_jackpot_only = true")

    def ev_hidden(self, line):
        # unlinked normal unique on a base the EV hides on purpose (not worth picking up on average)
        v = self.r["ubases"].get(line.get("baseType"))
        return not line.get("links") and not line["name"].startswith("Foulborn ")             and v is not None and v[4] is not None and v[0] == "hide"

    def test_ev_hidden_bases(self):
        # EV-hidden base: EV really below the shown floor, and not on the hand list
        if not self.cfg["uniques"]["ev"].get("enabled"):
            self.skipTest("uniques.ev off")
        tiers = bf.Tiers(self.cfg)
        shown = bf.shown_unique_tiers(self.cfg, tiers)
        always = set(self.cfg["uniques"].get("always_show_bases", []))
        bad = [(b, v) for b, v in self.r["ubases"].items()
               if v[4] is not None and v[0] == "hide" and (tiers.of(v[4]) in shown or b in always)]
        self.assertFalse(bad, bad[:20])
        self.assertFalse([b for b in always if self.r["ubases"].get(b, ("x",))[0] == "hide"])

    def test_valuable_uniques_visible_unidentified(self):
        self.skip_if_jackpot_only()
        if self.cfg["uniques"]["ev"].get("enabled"):
            self.skipTest("uniques.ev on: low-EV bases hide chase uniques, test_ev_hidden_bases guards")
        u = self.cfg["uniques"]
        items = []
        per = {}
        for t in bf.UNIQUE_TYPES:
            for line in self.data["stash"][t]["lines"]:
                name, base = line["name"], line.get("baseType")
                if not base or line.get("links") or line.get("listingCount", 0) < 1:
                    continue
                if name.startswith("Foulborn "):  # own test below
                    continue
                if bf.no_map_drop(self.data, name):  # boss loot: filter toggled off there
                    continue
                if name.startswith("Replica ") and not u["include_replicas"]:
                    continue
                key = (base, name, unique_class(line, t))
                per[key] = max(per.get(key, 0), line["chaosValue"])  # best variant: unID can't tell
        for (base, name, cls), v in per.items():
            if v >= SAFETY_DIVINE * self.r["divine"]:
                items.append((f"{name} ({base}, {v:.0f}c)", unid_unique(base, cls)))
        self.assertGreater(len(items), 30)
        self.assert_all_visible(items, "valuable unique bases")

    def test_unique_price_blocks_match_own_kind(self):
        # Every unique base, as it drops (unID), gets the price block of its own kind and tier:
        # a Foulborn never lands in a normal "uniques <tier>" block and vice versa (5c Foulborn
        # Cutlass was shown red by the 780c normal Cutlass tier). Earlier blocks (exceptions,
        # variable_classes, linked ...) may still decide; only the wrong-kind price block fails.
        classes = {}
        for t in bf.UNIQUE_TYPES:
            for line in self.data["stash"][t]["lines"]:
                cls = unique_class(line, t)
                if line.get("baseType") and cls:
                    classes.setdefault(line["baseType"], cls)
        tier_names = set(self.cfg["tiers"]) | {"variable", "hide", "unknown"}
        bad = []
        for kind, by_base, foul in (("foulborn", self.r["fbases"], True), ("uniques", self.r["ubases"], False)):
            other = "uniques" if foul else "foulborn"
            for base, (tier, *_rest) in by_base.items():
                if base not in classes:
                    continue
                b, _ = fs.evaluate(self.blocks, unid_unique(base, classes[base], foulborn=foul))
                c = (b.comment or "").strip().split() if b else []
                # only price-tier blocks ("<kind> <tier>[ maps]"), not "uniques variable_classes" etc.
                if len(c) < 2 or c[1] not in tier_names:
                    continue
                if c[0] == other or (c[0] == kind and c[1] != tier):
                    bad.append(f"{kind} {base} (tier {tier}) <- {b}")
        self.assertFalse(bad, f"{len(bad)} unique bases styled by the wrong price block:\n" + "\n".join(bad[:40]))

    def test_valuable_foulborn_visible_unidentified(self):
        self.skip_if_jackpot_only()
        items = []
        for t in bf.UNIQUE_TYPES:
            for line in self.data["stash"][t]["lines"]:
                if line["name"].startswith("Foulborn ") and line.get("baseType") and not line.get("links")                         and not bf.no_map_drop(self.data, line["name"]):
                    if line["chaosValue"] < SAFETY_DIVINE * self.r["divine"] or line.get("listingCount", 0) < 1:
                        continue
                    items.append((f"{line['name']} [{line.get('variant')}] ({line['chaosValue']:.0f}c)",
                                  unid_unique(line["baseType"], unique_class(line, t), foulborn=True)))
        self.assertGreater(len(items), 20)
        self.assert_all_visible(items, "valuable Foulborn uniques")

    def test_no_jackpot_hidden(self):
        # ANY priced item >= jackpot_divine, as it drops, must be visible
        jackpot = bf.jackpot_chaos(self.cfg, self.r["divine"])
        b = self.cfg["bases"]
        items = []
        for t in bf.UNIQUE_TYPES:
            for line in self.data["stash"][t]["lines"]:
                if line.get("baseType") and line.get("listingCount", 0) >= 1 and line["chaosValue"] >= jackpot                         and not bf.no_map_drop(self.data, line["name"]) and not self.ev_hidden(line):
                    items.append((f"{line['name']} [{line.get('variant')}] {line.get('links') or ''}L ({line['chaosValue']:.0f}c)",
                                  dict(unid_unique(line["baseType"], unique_class(line, t),
                                                   foulborn=line["name"].startswith("Foulborn ")),
                                       links=line.get("links") or 0)))
        for line in self.data["stash"]["BaseType"]["lines"]:
            if "/" in (line.get("variant") or ""):
                continue  # dual influence: Awakener's Orb crafts only, never drops
            if line["chaosValue"] >= jackpot and line.get("listingCount", 0) >= b["min_listings"]                     and line.get("count", 0) >= b["min_samples"]:
                infl = line.get("variant")
                items.append((f"{line['name']} ilvl{line.get('levelRequired')} {infl or ''} ({line['chaosValue']:.0f}c)",
                              {"class": NINJA_CLASS.get(line.get("itemType")), "basetype": line["name"], "rarity": "Rare",
                               "ilvl": line.get("levelRequired", 0), "influence": infl.split("/") if infl else []}))
        overrides = self.cfg.get("overrides", {})
        items += [(f"{n} ({v:.0f}c)", {"class": STACK_CLASS.get(t, "Stackable Currency"), "basetype": n, "stack": 1})
                  for n, (v, t) in self.r["prices"].items() if v >= jackpot and overrides.get(n) != "hide"]
        self.assertGreater(len(items), 20)
        self.assert_all_visible(items, "jackpot items")

    def test_top_priced_items_tink(self):
        # every confident price in the top tier, as it drops, gets the tink look (not just shown)
        top = max(self.cfg["tiers"], key=self.cfg["tiers"].get)
        tiers, overrides = self.r["tiers"], self.cfg.get("overrides", {})
        items = [(f"{n} ({v:.0f}c)", {"class": STACK_CLASS.get(t, "Stackable Currency"), "basetype": n, "stack": 1})
                 for n, (v, t) in self.r["prices"].items() if tiers.of(v) == top and n not in overrides]
        base_class = {l["name"]: NINJA_CLASS.get(l.get("itemType")) for l in self.data["stash"]["BaseType"]["lines"]}
        items += [(f"base {name} ilvl{lo} {infl or ''} ({chaos:.0f}c)",
                   {"class": base_class.get(name), "basetype": name, "rarity": "Rare", "ilvl": lo,
                    "influence": infl.split("/") if infl else []})
                  for tier, lo, hi, infl, name, chaos in self.r["cbases"] if tier == top]
        items += [(f"cluster {base} {n}p {node} ilvl{lo} ({chaos:.0f}c)",
                   {"class": "Jewels", "basetype": base, "rarity": "Normal", "ilvl": lo, "area_level": 83,
                    "cluster_passives": n, "cluster_node": node})
                  for (tier, base, n, lo, hi, node), chaos in self.r["clusters"].items() if tier == top and node]
        bad = not_tink(self.blocks, self.cfg, items)
        self.assertFalse(bad, f"{len(bad)} top-priced items not tink:\n" +
                         "\n".join(f"  {lab}  <- {b}" for lab, b in bad[:40]))

    def test_priced_stackables_visible(self):
        floor = self.r["tiers"].shown_floor(self.cfg)
        overrides = self.cfg.get("overrides", {})
        sl = bf.small_loot(self.cfg)
        wrist = lambda v, t: sl and t in sl[1] and v < sl[0]  # non-stackable below small_loot: hidden on purpose
        items = [(f"{n} ({v:.2f}c)", {"class": STACK_CLASS.get(t, "Stackable Currency"), "basetype": n, "stack": 1})
                 for n, (v, t) in self.r["prices"].items()
                 if v >= floor and overrides.get(n) != "hide" and not wrist(v, t)]
        self.assertGreater(len(items), 100)
        self.assert_all_visible(items, "priced stackables")

    def test_unpriced_reference_cards_visible(self):
        keep = {"top", "high", "mid", "minor", "low", "unknown", "variable"}
        items = [(n, {"class": "Divination Cards", "basetype": n})
                 for n, tier in self.r["ref_cards"].items() if n not in self.r["prices"] and tier in keep]
        self.assertGreater(len(items), 50)
        self.assert_all_visible(items, "reference-tier cards")

    def test_valuable_crafting_bases_visible(self):
        base_class = {l["name"]: NINJA_CLASS.get(l.get("itemType")) for l in self.data["stash"]["BaseType"]["lines"]}
        items = []
        for tier, lo, hi, infl, name, chaos in self.r["cbases"]:
            if bf.hidden(self.cfg, tier):
                continue
            item = {"class": base_class.get(name), "basetype": name, "rarity": "Rare", "ilvl": lo,
                    "influence": infl.split("/") if infl else []}
            items.append((f"{name} ilvl{lo} {infl or ''} ({chaos:.0f}c)", item))
        self.assert_all_visible(items, "valuable crafting bases")

    def ninja_drop(self, t, line):
        """poe.ninja line of a BASE_TYPES / CHECK_TYPES feed -> the item as it drops in a map,
        None when it can't drop like that. Unknown feed -> fails: add it here."""
        name, base = line["name"], line.get("baseType")
        if t in bf.BASE_TYPES:
            infl = line.get("variant")
            if infl and "/" in infl or line.get("count", 0) < self.cfg["bases"]["min_samples"]:
                return None  # dual influence: Awakener's Orb crafts only; thin sample: not a price
            return {"class": NINJA_CLASS.get(line.get("itemType")), "basetype": name, "rarity": "Rare",
                    "ilvl": line.get("levelRequired", 0), "influence": infl.split("/") if infl else []}
        if t == "ClusterJewel":
            self.assertIn(name, bf.CLUSTER_NODES, f"new cluster enchant {name!r}: add it to CLUSTER_NODES")
            self.assertIn(bf.CLUSTER_NODES[name], self.cluster_nodes | VERIFIED_CLUSTER_NODES,
                          f"valuable cluster {name!r}: check its in-game EnchantmentPassiveNode name "
                          f"{bf.CLUSTER_NODES[name]!r} (NeverSink's reference doesn't use it)")
            # price covers its ilvl bucket (1/50/68/75/84+); below 68 it drops in the campaign
            ilvl = line.get("levelRequired", 0)
            return {"class": "Jewels", "basetype": base, "rarity": "Normal", "ilvl": ilvl,
                    "area_level": ilvl if ilvl < 68 else 83, "cluster_node": bf.CLUSTER_NODES[name],
                    "cluster_passives": int(line["variant"].split()[0])}
        if t in ("SkillGem", "ImbuedGem"):
            # every variant (level / quality / corrupted) can drop: Vaal side areas, strongboxes, rewards
            # alternate gems: BaseType is the plain gem (Cyclone of Tumult -> Cyclone)
            alt = bf.alt_gem(line)
            basetype = line["tradeFilter"]["query"]["type"]["option"] if alt else name
            return {"class": "Support Gems" if name.endswith(" Support") else "Skill Gems", "basetype": basetype,
                    "quality": line.get("gemQuality") or 0, "gem_level": line.get("gemLevel", 1),
                    "corrupted": bool(line.get("corrupted")), "transfigured": alt}
        if t in ("ForbiddenJewel", "ShrineBelt"):
            return unid_unique(base, NINJA_CLASS.get(line.get("itemType")))
        if t == "ScryingOrb":
            return {"basetype": base, "class": "Stackable Currency"}
        if t == "IncursionTemple":
            return {"basetype": base, "class": "Misc Map Items"}
        if t == "Map":
            return map_drop(name, base)
        if t == "BlightedMap":
            return map_drop(name, blighted=True)
        if t == "BlightRavagedMap":
            return map_drop(name, blighted=True, uber_blighted=True)
        if t == "ValdoMap":
            return map_drop(name, base, rarity="Rare")
        self.fail(f"poe.ninja feed {t}: no drop model in LiveCache.ninja_drop")

    def test_valuable_ninja_items_visible(self):
        # every confident poe.ninja value >= SAFETY_DIVINE of the feeds not priced into the
        # filter (NeverSink / hand rules decide), as it drops, must be visible. Maps too.
        floor = SAFETY_DIVINE * self.r["divine"]
        items = []
        min_listings = self.cfg["uniques"]["min_listings"]
        for t in bf.BASE_TYPES + bf.CHECK_TYPES:
            lines = self.data["stash"][t]["lines"]
            if t in ("SkillGem", "ImbuedGem"):  # price capped by a confident better variant
                gems = [l for l in lines if l.get("listingCount", 0) and not bf.alt_gem(l)]
                caps = bf.gem_caps(gems, min_listings)
                lines = [l for i, l in enumerate(gems) if caps.get(i, math.inf) >= floor] \
                    + [l for l in lines if l.get("listingCount", 0) and bf.alt_gem(l)]
            for line in lines:
                if line["chaosValue"] < floor or line.get("listingCount", 0) < min_listings:
                    continue
                item = self.ninja_drop(t, line)
                if item is not None:
                    label = f"{t}: {line['name']} [{line.get('variant') or ''}] ilvl{line.get('levelRequired', '')} ({line['chaosValue']:.0f}c)"
                    items.append((label, item))
        self.assertGreater(len(items), 20)
        self.assert_all_visible(items, "valuable poe.ninja items")

    def test_every_ninja_category_handled(self):
        # poe.ninja's sidebar (scraped by build_filter.check_ninja_categories) vs our type lists
        cached = ROOT / "cache" / "ninja_categories.json"
        if not cached.exists():
            self.skipTest("no cache/ninja_categories.json, run build_filter.py once")
        self.assertFalse(set(json.loads(cached.read_text(encoding="utf-8"))) - set(bf.NINJA_TYPES))

    def test_filter_fully_modelled(self):
        # every condition in the built filter is understood by the simulator
        for b in self.blocks:
            for k, op, v, no in b.conds:
                try:
                    fs._match({}, k, op, v, no)
                except NotImplementedError as e:
                    self.fail(str(e))
                except (KeyError, ValueError, IndexError):
                    pass


if __name__ == "__main__":
    unittest.main()
