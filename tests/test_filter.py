"""Safety tests: the filter must never hide something valuable or maybe-valuable after ID.

Run:  python -m unittest discover tests        (from the poe-filter-generator folder)

Two kinds of tests:
  Synthetic   - small fake poe.ninja data, checks the pricing rules themselves.
  Live cache  - builds the real filter from cache/<league>/ and replays every priced
                item through it with filtersim.py. Skipped when there is no cache.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter as bf  # noqa: E402
import filtersim as fs  # noqa: E402
from report import NINJA_CLASS, STACK_CLASS, browser_rules, unique_class  # noqa: E402

# Safety line: no unique worth this many divines may sit on a hidden base. Fixed here on
# purpose, so raising config never_hide_tier fails the tests instead of shrinking them.
SAFETY_DIVINE = 1


# ------------------------------------------------------------------ synthetic data

def empty_data(divine=400):
    ex = {t: {"core": {"primary": "chaos", "rates": {"divine": 1 / divine}}, "items": [], "lines": []}
          for t in bf.EXCHANGE_TYPES}
    st = {t: {"lines": []} for t in bf.STASH_STACKABLE_TYPES + bf.UNIQUE_TYPES + ["BaseType"]}
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

    def test_divine_tiers_never_fall_below_one_chaos(self):
        self.cfg["tiers_follow_divine"] = True
        self.cfg["tiers_divine"] = {"top": 1, "high": 0.25, "mid": 0.0625, "minor": 0.015625}
        for exchange in self.data["exchange"].values():
            exchange["core"]["rates"]["divine"] = 1 / 8
        _, r = self.build()
        self.assertEqual(r["divine"], 8)
        self.assertEqual(r["tiers"].list[:4], [("top", 8), ("high", 2), ("mid", 1.0), ("minor", 1.0)])
        thresholds = dict(r["tiers"].list)
        self.assertTrue(all(thresholds[name] >= 1 for name in self.cfg["tiers_divine"]))

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
        # With the module enabled, restricted drops use their poe.ninja price, not a blanket show.
        rows = [{"name": "Ixchel's Temptation", "base": "Gold Ring", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Gold Ring", "Ixchel's Temptation", 1, item_type="Ring")
        ring = unid_unique("Gold Ring", "Rings")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        self.data["nomap"] = {"Ixchel's Temptation": "content"}
        self.data["wiki_bases"] = {"Gold Ring": {"Ixchel's Temptation"}}

        self.assertFalse(fs.visible(self.build()[0], ring))
        self.data["stash"]["UniqueAccessory"]["lines"][0]["chaosValue"] = 100
        self.assertTrue(fs.visible(self.build()[0], ring))

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

    def test_ultimatum_unique_is_hidden_by_default(self):
        rows = [{"name": "Temptation Step", "base": "Shagreen Boots", "restricted": True, "enabled": True,
                 "source": "Metadata/Monsters/LeagueUltimatum/TrialMaster/TrialMasterBoss |  | "}]
        add_unique(self.data, "Shagreen Boots", "Temptation Step", 1, item_type="Boots", t="UniqueArmour")
        self.data["content"] = bf.content_bases(rows, self.cfg)
        item = unid_unique("Shagreen Boots", "Boots")

        self.assertFalse(fs.visible(self.build()[0], item))

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

    def test_boss_only_cheap_unique_keeps_tier_honest(self):
        # Titan Greaves: Kaom's Roots 26c drops in maps, Infinite Pursuit 1c is Breach-only.
        # The 1c one still drops, so the base must not claim "high" (normal or Foulborn).
        add_unique(self.data, "Titan Greaves", "Kaom's Roots", 26, item_type="Boots", t="UniqueArmour")
        add_unique(self.data, "Titan Greaves", "The Infinite Pursuit", 1, item_type="Boots", t="UniqueArmour")
        add_foulborn(self.data, "Titan Greaves", "Kaom's Roots", "Strength", 54, item_type="Boots", t="UniqueArmour")
        add_foulborn(self.data, "Titan Greaves", "The Infinite Pursuit", "Bleed Armour", 0.98, item_type="Boots", t="UniqueArmour")
        self.data["nomap"] = {"The Infinite Pursuit": "Breach"}
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
        add_exchange(self.data, "Currency", "Cheap Shard", self.cfg["tiers"]["dust"])
        add_unique(self.data, "Gold Ring", "Junk Ring", 0.1)
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
            {"class": "Rings", "basetype": "Iron Ring", "rarity": "Rare", "mirrored": True},
            {"class": "Quest Items", "basetype": "Some Quest Thing"},
            {"class": "Some Future Class", "basetype": "Thing"},
        ]:
            self.assertTrue(fs.visible(blocks, item), item)


# ------------------------------------------------------------------ live cache

def latest_cache():
    dirs = [d for d in (ROOT / "cache").glob("*") if (d / "st_BaseType.json").exists()]
    return max(dirs, key=lambda d: (d / "st_BaseType.json").stat().st_mtime) if dirs else None


def load_cache(d, cfg):
    rd = lambda f: json.loads((d / f).read_text(encoding="utf-8"))
    wiki = ROOT / "cache" / "wiki_uniques.json"
    rows = json.loads(wiki.read_text(encoding="utf-8")) if wiki.exists() else []
    return {"exchange": {t: rd(f"ex_{t}.json") for t in bf.EXCHANGE_TYPES},
            "stash": {t: rd(f"st_{t}.json") for t in bf.STASH_STACKABLE_TYPES + bf.UNIQUE_TYPES + ["BaseType"]},
            "nomap": bf.non_map_drops(rows, cfg), "wiki_bases": bf.wiki_unique_bases(rows),
            "content": bf.content_bases(rows, cfg),
            "drop_anywhere": {r["name"] for r in rows if r["enabled"] and not r["restricted"]}}


CACHE = latest_cache()


@unittest.skipIf(CACHE is None, "no price cache, run build_filter.py once")
class LiveCache(unittest.TestCase):
    longMessage = False  # our message already lists the hidden items

    @classmethod
    def setUpClass(cls):
        cls.cfg = bf.load_cfg()
        cls.data = load_cache(CACHE, cls.cfg)
        text, cls.r = bf.build_text(cls.cfg, cls.data, CACHE.name)
        cls.blocks = fs.parse(text)

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
        floor = self.cfg["tiers"][self.cfg["uniques"]["min_tier"]]
        always = set(self.cfg["uniques"].get("always_show_bases", []))
        bad = [(b, v) for b, v in self.r["ubases"].items()
               if v[4] is not None and v[0] == "hide" and (v[4] >= floor or b in always)]
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
