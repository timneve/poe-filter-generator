"""Safety tests: the filter must never hide something valuable or maybe-valuable after ID.

Run:  python -m unittest discover tests        (from the poe-filter-generator folder)

Two kinds of tests:
  Synthetic   - small fake poe.ninja data, checks the pricing rules themselves.
  Live cache  - builds the real filter from cache/<league>/ and replays every priced
                item through it with filtersim.py. Skipped when there is no cache.
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter as bf  # noqa: E402
import filtersim as fs  # noqa: E402
from report import NINJA_CLASS, STACK_CLASS, browser_rules, unique_class, vendor_recipes  # noqa: E402

# Safety line: no unique worth this many divines may sit on a hidden base. Fixed here on
# purpose, so raising config never_hide_tier fails the tests instead of shrinking them.
SAFETY_DIVINE = 1


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


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(bf.load_cfg())
        self.cfg["tiers_follow_divine"] = False  # fixed chaos tiers: the numbers below assume them
        self.cfg["tiers"] = dict(FIXED_TIERS)
        self.cfg["uniques"]["ev"]["enabled"] = False  # cheapest-unique rules; EV has its own tests
        self.cfg["uniques"]["variable_jackpot_only"] = False
        self.cfg["uniques"]["always_show_bases"] = []
        self.cfg["content"]["ultimatum"]["drops"] = {}
        self.cfg["content"]["blight"]["drops"] = {}
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
        blocks, _ = self.build()
        for key, item in recipes.items():
            block, style = fs.evaluate(blocks, item)
            self.assertEqual(block.comment, f"vendor recipe: {key}")
            self.assertTrue(any(l.startswith("MinimapIcon") and l.endswith("Diamond") for l in style), key)
        self.assertNotIn("recipe", fs.evaluate(blocks, gem20)[0].comment)  # own cyan 20% rule
        self.assertIn("MinimapIcon 1 Red Diamond", fs.evaluate(blocks, awakened)[1])
        self.assertFalse(fs.visible(blocks, flask_low))
        self.assertFalse(fs.visible(blocks, dict(rgb, socket_group="RGG")))
        for key in recipes:
            self.cfg["vendor_recipes"][key]["enabled"] = False
        blocks, _ = self.build()
        for key, item in recipes.items():
            self.assertFalse(fs.visible(blocks, item), key)

    def test_vendor_recipe_floor_keeps_crafting_base_tier(self):
        # 6-socket Plate Vest: pricey ilvl 86 base keeps its top tier, cheap ilvl 84 one (hidden by
        # price) gets the jeweller recipe tier.
        for ilvl, chaos in [(84, 1), (86, 600)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": "Plate Vest", "levelRequired": ilvl, "chaosValue": chaos,
                 "listingCount": 69, "count": 10, "itemType": "Body Armour"})
        self.cfg["vendor_recipes"]["jeweller"]["enabled"] = True
        blocks, r = self.build()
        vest = {"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Normal", "sockets": 6}
        block, style = fs.evaluate(blocks, dict(vest, ilvl=86))
        self.assertEqual(block.comment, "vendor recipe: jeweller (worth more: base top ilvl86+ plain)")
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
                             "jewellery": ["t1", "t2"], "text_color": "200 200 150 255"}
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
            return fs.evaluate(blocks, dict(body_armour, quality=quality, **attrs))[0]

        self.assertEqual(self.cfg["overquality"], {
            "quality_30": True, "quality_27": False, "quality_21": False})
        self.assertEqual(decided_at(30).comment, "overquality 30%+")
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
        # same unique, mutated-mod variants 50c .. 30 div: tier by cheapest, flagged variable
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Red Immortal", 30 * 400, listings=3, item_type="Two Handed Sword", t="UniqueWeapon")
        add_foulborn(self.data, "Lion Sword", "Doomsower", "Other", 50, listings=3, item_type="Two Handed Sword", t="UniqueWeapon")
        _, r = self.build()
        tier, cheapest, best, *_ = r["fbases"]["Lion Sword"]
        self.assertEqual(cheapest, 50)  # 3+3 listings summed >= min_listings
        self.assertEqual(best, 30 * 400)
        self.assertEqual(tier, "variable")

    def test_foulborn_does_not_raise_normal_tier(self):
        add_unique(self.data, "Leather Belt", "Junk", 1)
        add_foulborn(self.data, "Leather Belt", "Headhunter", "Culling Strike", 200000)
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Leather Belt"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Leather Belt", "Belts")))
        self.assertTrue(fs.visible(blocks, unid_unique("Leather Belt", "Belts", foulborn=True)))

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
            ({"class": "Jewels", "basetype": "Cobalt Jewel", "rarity": "Magic"}, False),
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
            ({"class": "Body Armours", "basetype": "Plate Vest", "rarity": "Magic", "armour": 10, "links": 4}, False),
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

    def test_mirrored_item_rule_config_toggle(self):
        item = {"class": "Rings", "basetype": "Iron Ring", "rarity": "Rare", "mirrored": True}
        self.cfg["vendor_recipes"]["grasping_mail"]["enabled"] = False
        blocks, _ = self.build()
        mirrored_rules = [
            block for block in blocks
            if any(key == "Mirrored" and op in ("=", "==") and values == ["True"]
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
        cls.cluster_nodes = bf.neversink_cluster_nodes((ROOT / "reference/league.filter").read_text(encoding="utf-8"))

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
            self.assertIn(bf.CLUSTER_NODES[name], self.cluster_nodes,
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
        for t in bf.BASE_TYPES + bf.CHECK_TYPES:
            for line in self.data["stash"][t]["lines"]:
                if line["chaosValue"] < floor or line.get("listingCount", 0) < self.cfg["uniques"]["min_listings"]:
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
