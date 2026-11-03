import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter_poe2 as bf  # noqa: E402
import filtersim as fs  # noqa: E402

CURRENCY = "Stackable Currency"
# Stand-in for the NeverSink export: header, a tink block, a calm-able block, a catch-all.
REFERENCE = """# NeverSink header
# [[0100]] Gold

#===
# [[1900]] Socketables
#===

Show # ns tink
\tBaseType == "Ref Tink Rune"
\tSetBorderColor 255 0 0 255
\tSetBackgroundColor 255 255 255 255

Show # ns known
\tBaseType == "Known Thin Rune"
\tSetBorderColor 10 20 30
\tSetBackgroundColor 0 0 0 200
\tSetFontSize 40

Show # ns catch-all
\tSetFontSize 45
"""


def empty_data():
    # Currency quoted in divines (1 div = 100c = 500ex); Runes quoted in chaos.
    return {
        "exchange": {
            "Currency": {"core": {"primary": "divine", "rates": {"chaos": 100.0, "exalted": 500.0}},
                         "items": [], "lines": []},
            "Runes": {"core": {"primary": "chaos", "rates": {"divine": 0.01}},
                      "items": [], "lines": []},
            "UncutGems": {"core": {"primary": "divine", "rates": {"chaos": 100.0}},
                          "items": [], "lines": []},
        }
    }


def add_item(data, item_type, name, div, volume=1000.0):
    """Price and traded volume in divines, stored in the feed's primary currency."""
    factor = bf.divine_per_primary(data["exchange"][item_type]["core"])
    item_id = name.lower().replace(" ", "-")
    data["exchange"][item_type]["items"].append({"id": item_id, "name": name})
    data["exchange"][item_type]["lines"].append({
        "id": item_id, "primaryValue": div / factor, "volumePrimaryValue": volume / factor})


class Poe2FilterTests(unittest.TestCase):
    def setUp(self):
        self.cfg = bf.load_cfg()
        self.cfg["hide_tiers"] = ["low", "brown", "dust"]  # tests assume these, not the user's config
        self.cfg["quiet_tiers"] = []
        self.data = empty_data()
        add_item(self.data, "Currency", "Chaos Orb", 0.01)
        add_item(self.data, "Currency", "Exalted Orb", 0.002)

    def build(self):
        text, results = bf.build_text(self.cfg, self.data, "Test League", REFERENCE)
        self.text = text
        return fs.parse(text), results

    def decide(self, blocks, name, cls=CURRENCY, **item):
        block, _ = fs.evaluate(blocks, {"class": cls, "basetype": name, **item})
        return block

    def test_prices_convert_to_divines_from_any_primary(self):
        add_item(self.data, "Runes", "Chaos Priced Rune", 0.05)
        prices = bf.price_exchange(self.data)
        self.assertAlmostEqual(prices["Chaos Priced Rune"][0], 0.05)
        self.assertAlmostEqual(prices["Chaos Orb"][0], 0.01)

    def test_tiers_follow_divine_not_chaos(self):
        # 100c per divine: a chaos is 1/100 div -> below minor (1/64) -> hidden "low"
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Chaos Orb").action, "Hide")
        # 9c per divine: a chaos is ~1/9 div -> shown
        self.data = empty_data()
        add_item(self.data, "Currency", "Chaos Orb", 1 / 9)
        blocks, _ = self.build()
        block = self.decide(blocks, "Chaos Orb")
        self.assertEqual((block.action, block.comment), ("Show", "mid"))

    def test_exalt_singles_hide_stacks_show(self):
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Exalted Orb", stack=1).action, "Hide")
        block = self.decide(blocks, "Exalted Orb", stack=8)  # 8 x 1/500 = 1/62.5 div >= minor
        self.assertEqual((block.action, block.comment), ("Show", "minor stack x8"))

    def test_hidden_tiers_get_no_stack_blocks(self):
        add_item(self.data, "Currency", "Dust Orb", 0.0003)
        self.build()
        for tier in self.cfg["hide_tiers"]:
            self.assertNotIn(f"# {tier} stack", self.text)

    def test_pinned_always_top(self):
        add_item(self.data, "Currency", "Hinekora's Lock", 0.0001, volume=0)
        blocks, _ = self.build()
        for name in bf.PINNED_TOP:
            block, style = fs.evaluate(blocks, {"class": CURRENCY, "basetype": name})
            self.assertEqual(block.comment, f"pinned {name}")
            self.assertIn("PlayAlertSound 6 300", style)

    def test_thin_market_never_tinks(self):
        add_item(self.data, "Runes", "Fake Rune", 5.0, volume=0.2)
        blocks, _ = self.build()
        block, style = fs.evaluate(blocks, {"class": "Augment", "basetype": "Fake Rune"})
        self.assertEqual(block.comment, "thin market, not in NeverSink: never hide")
        self.assertNotIn("PlayAlertSound 6 300", style)

    def test_thin_market_cheap_item_not_hidden(self):
        add_item(self.data, "Runes", "Thin Cheap Rune", 0.0001, volume=0.001)
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {"class": "Augment", "basetype": "Thin Cheap Rune"}))

    def test_thin_market_known_item_uses_neversink_tier(self):
        add_item(self.data, "Runes", "Known Thin Rune", 5.0, volume=0.2)
        blocks, results = self.build()
        self.assertEqual(self.decide(blocks, "Known Thin Rune", "Augment").comment, "ns known")
        self.assertIn("Known Thin Rune", results["deferred"])

    def test_expensive_item_trading_few_units_is_trusted(self):
        add_item(self.data, "Runes", "Rare Rune", 100.0, volume=50.0)  # 0.5 units, 50 div traded
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Rare Rune", "Augment").comment, "top")

    def test_uncut_gems_tier_by_gem_level(self):
        add_item(self.data, "UncutGems", "Uncut Skill Gem (Level 19)", 0.1)
        add_item(self.data, "UncutGems", "Uncut Skill Gem (Level 18)", 0.0001)
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Uncut Skill Gem", "Uncut Skill Gems", gem_level=19).comment, "mid")
        self.assertEqual(self.decide(blocks, "Uncut Skill Gem", "Uncut Skill Gems", gem_level=18).action, "Hide")
        self.assertEqual(self.decide(blocks, "Uncut Skill Gem", "Uncut Skill Gems", gem_level=5).comment,
                         "ns catch-all")

    def test_level_names_outside_gem_feed_stay_literal(self):
        add_item(self.data, "Runes", "Thaumaturgic Flux (Level 20)", 0.5)
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Thaumaturgic Flux (Level 20)", "Augment").comment, "high")

    def test_reference_appended_and_calmed(self):
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Some Boots", "Boots").comment, "ns catch-all")
        tink = next(b for b in blocks if b.comment == "ns tink")
        known = next(b for b in blocks if b.comment == "ns known")
        self.assertIn("SetBackgroundColor 255 255 255 255", tink.style)
        self.assertEqual(known.style, ["SetFontSize 45"])  # calmed + full text size
        self.assertNotIn("NeverSink header", self.text)

    def test_gold_hidden_unless_show_gold(self):
        gold = {"class": CURRENCY, "basetype": "Gold", "stack": 5000}
        self.cfg["show_gold"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gold))
        self.cfg["show_gold"] = True
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Gold", stack=5000).comment, "ns catch-all")

    def test_shown_items_full_text_size(self):
        add_item(self.data, "Currency", "Minor Orb", 0.02)
        blocks, _ = self.build()
        _, style = fs.evaluate(blocks, {"class": CURRENCY, "basetype": "Minor Orb"})
        self.assertIn("SetFontSize 45", style)

    def test_dust_is_everything_below_brown(self):
        add_item(self.data, "Currency", "Tiny Orb", 1e-9)
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Tiny Orb").comment, "dust")

    def test_report_rows_and_tier_strip(self):
        import tempfile
        import report_poe2
        add_item(self.data, "Currency", "Minor Orb", 0.02)
        add_item(self.data, "Runes", "Known Thin Rune", 5.0, volume=0.2)
        text, results = bf.build_text(self.cfg, self.data, "Test League", REFERENCE)
        rows = {row["name"]: row for row in report_poe2.collect(self.cfg, fs.parse(text), results)}
        self.assertEqual((rows["Minor Orb"]["tier"], rows["Minor Orb"]["shown"]), ("minor", True))
        self.assertEqual(rows["Exalted Orb"]["shown"], False)
        self.assertEqual(rows["Known Thin Rune"]["tier"], "neversink")
        with tempfile.TemporaryDirectory() as tmp:
            page = report_poe2.write(self.cfg, text, results, "Test League", Path(tmp) / "r.html")
            html = page.read_text(encoding="utf-8")
        self.assertIn('"ex":500.0', html)
        self.assertIn('"chaos":100.0', html)

    def test_tiers_sorted_and_distinct(self):
        values = [value for _, value in bf.Tiers(self.cfg).ordered]
        self.assertEqual(values, sorted(set(values), reverse=True))


def live_league():
    leagues = [d for d in (ROOT / "cache" / "poe2").glob("*/") if (d / "ex_Currency.json").exists()]
    return max(leagues, key=lambda d: d.stat().st_mtime) if leagues else None


@unittest.skipUnless(live_league(), "needs cache/poe2/<league> (run build_filter_poe2.py once)")
class Poe2LiveCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = bf.load_cfg()
        cache = live_league()
        data = {"exchange": {}}
        for item_type in cfg["exchange"]["types"]:
            path = cache / f"ex_{item_type}.json"
            if path.exists():
                data["exchange"][item_type] = json.loads(path.read_text(encoding="utf-8"))
        text, cls.results = bf.build_text(cfg, data, cache.name, bf.load_reference(cfg))
        cls.blocks = fs.parse(text)

    def test_filter_fully_modelled(self):
        for b in self.blocks:
            for k, op, v, no in b.conds:
                try:
                    fs._match({}, k, op, v, no)
                except NotImplementedError as e:
                    self.fail(str(e))
                except (KeyError, ValueError, IndexError):
                    pass

    def test_pinned_visible(self):
        for name in bf.PINNED_TOP:
            self.assertTrue(fs.visible(self.blocks, {"class": "Stackable Currency", "basetype": name}))

    def test_trusted_prices_decide_visibility(self):
        tiers = self.results["tiers"]
        for name, (value, item_type, volume) in self.results["prices"].items():
            if name in bf.PINNED_TOP or item_type in bf.LEVELED_FEEDS:
                continue
            if bf.reliable(tiers.cfg, value, volume):
                shown = fs.visible(self.blocks, {"class": "Stackable Currency", "basetype": name})
                self.assertEqual(shown, not tiers.hidden(tiers.of(value)), name)


if __name__ == "__main__":
    unittest.main()
