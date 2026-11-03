import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter_poe2 as bf  # noqa: E402
import filtersim as fs  # noqa: E402


def empty_data():
    return {
        "exchange": {
            "Currency": {
                "core": {"primary": "divine", "rates": {"chaos": 100.0}},
                "items": [], "lines": [],
            },
            "Runes": {
                "core": {"primary": "chaos", "rates": {"divine": 0.01}},
                "items": [], "lines": [],
            },
        }
    }


def add_item(data, item_type, name, chaos, volume=1000):
    primary = data["exchange"][item_type]["core"]["primary"]
    chaos_per_primary = (data["exchange"][item_type]["core"]["rates"]["chaos"]
                         if primary != "chaos" else 1)
    item_id = name.lower().replace(" ", "-")
    data["exchange"][item_type]["items"].append({"id": item_id, "name": name})
    data["exchange"][item_type]["lines"].append({
        "id": item_id,
        "primaryValue": chaos / chaos_per_primary,
        "volumePrimaryValue": volume / chaos_per_primary,
    })


class Poe2FilterTests(unittest.TestCase):
    def setUp(self):
        self.cfg = bf.load_cfg()
        self.cfg["tiers_follow_divine"] = False
        self.cfg["hide_tiers"] = ["brown", "dust"]
        self.data = empty_data()

    def build(self):
        text, results = bf.build_text(self.cfg, self.data, "Test League")
        return fs.parse(text), results

    def test_primary_divine_prices_are_converted_to_chaos(self):
        add_item(self.data, "Currency", "Expensive Orb", 30)
        prices, divine = bf.price_exchange(self.data, self.cfg)
        self.assertEqual(prices["Expensive Orb"][0], 30)
        self.assertEqual(divine, 100)

    def test_stack_size_reaches_higher_price_tier(self):
        add_item(self.data, "Currency", "Test Orb", 1)
        blocks, _ = self.build()
        item = {"class": "Currency", "basetype": "Test Orb", "stack": 5}
        block, _ = fs.evaluate(blocks, item)
        self.assertEqual(block.action, "Show")
        self.assertIn("mid stack x5", block.comment)

    def test_runes_are_not_given_undocumented_stack_size_rules(self):
        add_item(self.data, "Runes", "Test Rune", 1)
        blocks, _ = self.build()
        item = {"class": "Socketable Currency", "basetype": "Test Rune", "stack": 5}
        block, _ = fs.evaluate(blocks, item)
        self.assertEqual(block.comment, "low")

    def test_reliable_low_price_is_hidden(self):
        add_item(self.data, "Runes", "Cheap Rune", 0.1)
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, {"class": "Socketable Currency", "basetype": "Cheap Rune"}))

    def test_low_volume_low_price_is_shown_as_unknown(self):
        add_item(self.data, "Currency", "Thin Market Orb", 0.1, volume=0.1)
        blocks, _ = self.build()
        item = {"class": "Currency", "basetype": "Thin Market Orb"}
        block, style = fs.evaluate(blocks, item)
        self.assertEqual(block.action, "Show")
        self.assertEqual(block.comment, "low-volume price: never hide")
        self.assertIn("PlayEffect Blue", style)

    def test_unique_and_campaign_gear_remain_visible(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {"class": "Body Armours", "basetype": "Test Armour",
                                            "rarity": "Normal", "area_level": 10}))
        self.assertTrue(fs.visible(blocks, {"class": "Body Armours", "basetype": "Test Armour",
                                            "rarity": "Unique", "area_level": 83}))
        self.assertFalse(fs.visible(blocks, {"class": "Body Armours", "basetype": "Test Armour",
                                             "rarity": "Normal", "area_level": 83}))


if __name__ == "__main__":
    unittest.main()
