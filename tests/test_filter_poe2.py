import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_filter_poe2 as bf  # noqa: E402
import filtersim as fs  # noqa: E402
from build_filter import parse_module  # noqa: E402

CURRENCY = "Stackable Currency"
# Stand-in rule module (rules/modules_poe2/<name>.filter): a tink block, a bordered block, an
# off block, a catch-all.
MODULE = """# test module
# [1900] Socketables

Show # ns.tink
	BaseType == "Ref Tink Rune"
	SetBorderColor 255 0 0 255
	SetBackgroundColor 255 255 255 255

Show # ns.known
	BaseType == "Known Thin Rune"
	SetBorderColor 10 20 30
	SetFontSize 40

Show # ns.off
	BaseType == "Off Rune"
	SetFontSize 45

Show # ns.catch_all
	SetFontSize 45
"""
MODULE_TOGGLES = {"ns.tink": True, "ns.known": True, "ns.off": False, "ns.catch_all": True}


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
        self.cfg["modules"] = {"test": True}
        self.cfg["module_blocks"] = {"test": {"blocks": dict(MODULE_TOGGLES)}}
        self.modules = {"test": parse_module(MODULE)}
        self.data = empty_data()
        add_item(self.data, "Currency", "Chaos Orb", 0.01)
        add_item(self.data, "Currency", "Exalted Orb", 0.002)


    def test_every_colour_from_palette(self):
        text, _ = bf.build_text(self.cfg, self.data, "Test League", self.modules)
        used = set(re.findall(r"Set(?:Text|Border|Background)Color (.+)", text))
        self.assertTrue(used)
        self.assertEqual(used - set(self.cfg["colors"].values()), set())
    def build(self):
        text, results = bf.build_text(self.cfg, self.data, "Test League", self.modules)
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
        self.assertEqual(self.decide(blocks, "Known Thin Rune", "Augment").comment, "test ns.known")
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
                         "test ns.catch_all")

    def test_level_names_outside_gem_feed_stay_literal(self):
        add_item(self.data, "Runes", "Thaumaturgic Flux (Level 20)", 0.5)
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Thaumaturgic Flux (Level 20)", "Augment").comment, "high")

    def test_modules_appended_no_borders_except_tink(self):
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Some Boots", "Boots").comment, "test ns.catch_all")
        tink = next(b for b in blocks if b.comment == "test ns.tink")
        known = next(b for b in blocks if b.comment == "test ns.known")
        self.assertIn("SetBackgroundColor 255 255 255 255", tink.style)
        self.assertIn("SetBorderColor 255 0 0 255", tink.style)
        clear = f"SetBorderColor {self.cfg['colors']['clear']}"
        self.assertEqual(known.style, ["SetFontSize 45", clear])  # full text size, border opacity 0
        tink_bg = f"SetBackgroundColor {self.cfg['colors']['tink_bg']}"
        for b in blocks:  # price blocks too: a border only on tink
            if tink_bg not in b.style:
                self.assertEqual([s for s in b.style if s.startswith("SetBorderColor")], [clear], b.comment)

    def test_module_block_toggle_and_module_off(self):
        rune = {"class": "Augment", "basetype": "Off Rune"}
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, rune)[0].comment, "test ns.catch_all")
        self.cfg["module_blocks"]["test"]["blocks"]["ns.off"] = True
        blocks, _ = self.build()
        self.assertEqual(fs.evaluate(blocks, rune)[0].comment, "test ns.off")
        self.cfg["modules"]["test"] = False
        blocks, _ = self.build()
        self.assertFalse(any(b.comment.startswith("test ") for b in blocks))

    def test_module_missing_toggle_raises(self):
        del self.cfg["module_blocks"]["test"]["blocks"]["ns.known"]
        with self.assertRaises(KeyError):
            self.build()
        self.cfg["module_blocks"]["test"]["blocks"]["ns.known"] = True
        del self.cfg["modules"]["test"]
        with self.assertRaises(KeyError):
            self.build()

    def test_gold_hidden_unless_show_gold(self):
        gold = {"class": CURRENCY, "basetype": "Gold", "stack": 5000}
        self.cfg["show_gold"] = False
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, gold))
        self.cfg["show_gold"] = True
        blocks, _ = self.build()
        self.assertEqual(self.decide(blocks, "Gold", stack=5000).comment, "test ns.catch_all")

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
        text, results = bf.build_text(self.cfg, self.data, "Test League", self.modules)
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
        text, cls.results = bf.build_text(cfg, data, cache.name, bf.load_modules())
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


class Poe2Modules(unittest.TestCase):
    """rules/modules_poe2 vs modules_poe2.toml / config_poe2.toml / the FilterBlade export."""

    def setUp(self):
        self.cfg = bf.load_cfg()
        self.modules = bf.load_modules()

    def test_keys_match_toggles(self):
        self.assertEqual(set(self.cfg["modules"]), set(self.modules))
        for name, blocks in self.modules.items():
            keys = [b["key"] for b in blocks]
            self.assertEqual(len(keys), len(set(keys)), name)
            self.assertEqual(keys, list(self.cfg["module_blocks"][name]["blocks"]), name)

    def test_every_export_block_in_a_module(self):
        """Same blocks (key, action, conditions) as the export the modules came from: a refresh
        (tools/import_neversink.py --game poe2) that missed a section shows up here."""
        sys.path.insert(0, str(ROOT / "tools"))
        import import_neversink as imp
        ref = (ROOT / "reference" / "league-filterblade-poe2.filter").read_text(encoding="utf-8")
        exported = {b["key"]: (b["action"], b["conds"]) for b in imp.parse_ref_blocks(ref, *imp.section_span(ref))}
        ours = {b["key"]: (b["action"], b["conds"]) for blocks in self.modules.values() for b in blocks}
        self.assertEqual(ours, exported)

    def test_sections_belong_to_one_module(self):
        owner = {}
        for name, blocks in self.modules.items():
            for b in blocks:
                self.assertEqual(owner.setdefault(b["section"], name), name, b["section"])


if __name__ == "__main__":
    unittest.main()


class LeagueList(unittest.TestCase):
    """write_league_list: poe.ninja index-state -> leagues TOML (shared by both builds)."""

    def test_groups_and_valid_toml(self):
        import tempfile
        import tomllib
        state = {"economyLeagues": [
                     {"name": "Runes of Aldur", "indexed": True},
                     {"name": "Forbidden Rites", "indexed": False},
                     {"name": "Standard", "indexed": True}],
                 "oldEconomyLeagues": [{"name": "Dawn Ⅳ"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leagues.toml"
            bf.write_league_list(state, path, "config_poe2.toml")
            got = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(got, {"current": ["Runes of Aldur", "Standard"],
                               "no_prices": ["Forbidden Rites"], "old": ["Dawn Ⅳ"]})
