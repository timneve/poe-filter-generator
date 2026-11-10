"""tools/league_start.py: start / status / restore / finish on temp copies of config.toml +
modules.toml (--root), and "start-written files, flag off" == "repo files, league_start = true"
(one table: build_filter.league_start_values). No network."""
import contextlib
import io
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_filter as bf  # noqa: E402
import filtersim as fs  # noqa: E402
import league_start as ls  # noqa: E402
from test_filter import add_exchange, add_unique, empty_data, latest_cache, load_cache  # noqa: E402

FILES = ("config.toml", "modules.toml")


def load_cfg(root):
    """bf.load_cfg with config.toml / modules.toml from root (other files from the repo)."""
    cfg = bf.split_tiers(tomllib.loads((root / "config.toml").read_text(encoding="utf-8")))
    raw = tomllib.loads((ROOT / "unique_tiers.toml").read_text(encoding="utf-8"))
    cfg["unique_tiers"] = {n: int(t) for t, names in raw.items() for n in names}
    cfg["modules"] = tomllib.loads((root / "modules.toml").read_text(encoding="utf-8"))
    cfg["fallback_tiers"] = tomllib.loads((ROOT / "fallback_tiers.toml").read_text(encoding="utf-8"))
    return cfg


def body(text):
    """Filter text without the header (generated time, LEAGUE START marker)."""
    return text.split("\n# Do not edit", 1)[1]


def some_data():
    data = empty_data()
    add_exchange(data, "Currency", "Cheap Shard", 0.01)
    add_exchange(data, "Currency", "Orb of Alchemy", 0.3)
    add_unique(data, "Gold Ring", "Junk Ring", 0.1, item_type="Ring")
    add_unique(data, "Heavy Belt", "Mageblood", 13 * 400 * 10)
    add_unique(data, "Heavy Belt", "Cheap Belt", 1)
    data["stash"]["SkillGem"]["lines"].append({"name": "Fireball", "gemLevel": 1, "gemQuality": 0,
                                               "chaosValue": 1, "listingCount": 50})
    for name, chaos, item_type in [("Imbued Wand", 2, "Wand"), ("Saintly Chainmail", 2, "Body Armour"),
                                   ("Profane Wand", 500, "Wand")]:
        data["stash"]["BaseType"]["lines"].append({"name": name, "levelRequired": 82, "chaosValue": chaos,
                                                   "listingCount": 50, "count": 10, "itemType": item_type})
    return data


ITEMS = [
    {"class": "Stackable Currency", "basetype": "Cheap Shard"},
    {"class": "Stackable Currency", "basetype": "Scroll of Wisdom"},
    {"class": "Stackable Currency", "basetype": "Gold", "stack": 10, "area_level": 83},
    {"class": "Rings", "basetype": "Gold Ring", "rarity": "Unique"},
    {"class": "Maps", "basetype": "Map (Tier 1)", "rarity": "Normal", "map_tier": 1, "area_level": 83},
    {"class": "Skill Gems", "basetype": "Fireball"},
    {"class": "Skill Gems", "basetype": "Some Gem"},
    {"class": "Two Hand Swords", "basetype": "Reaver Sword", "rarity": "Normal", "ilvl": 84, "area_level": 83},
    {"class": "Body Armours", "basetype": "Saintly Chainmail", "rarity": "Normal", "ilvl": 84, "area_level": 83,
     "armour": 300, "es": 80},  # armour/ES: used by both builds
]


class LeagueStartScript(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for f in FILES:
            shutil.copy2(ROOT / f, self.root / f)
        self.orig = {f: (ROOT / f).read_bytes() for f in FILES}
        self.backup = self.root / "league_start" / "backup"

    def run_tool(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ls.main(["--root", str(self.root), *args])
        return out.getvalue()

    def test_start_writes_values_keeps_comments(self):
        self.run_tool("start")
        for f in FILES:
            self.assertEqual((self.backup / f).read_bytes(), self.orig[f])
            old, new = (ROOT / f).read_text(encoding="utf-8"), (self.root / f).read_text(encoding="utf-8")
            comments = lambda t: [l for l in t.splitlines() if l.lstrip().startswith("#") or not l.strip()]
            self.assertEqual(comments(old), comments(new), f)       # every comment / blank line kept
            self.assertEqual(len(old.splitlines()), len(new.splitlines()), f)
        conf = tomllib.loads((self.root / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(conf["hide_tiers"], [])
        self.assertFalse(conf["league_start"])                       # values, not the flag
        self.assertTrue(conf["gems"]["show_all"])
        mods = tomllib.loads((self.root / "modules.toml").read_text(encoding="utf-8"))
        orig = tomllib.loads(self.orig["modules.toml"].decode())
        for name, table in mods.items():                            # Shows on, Hides off, keep-lists untouched
            for b in bf.load_module(name):
                v, was = table["blocks"][b["key"]], orig[name]["blocks"][b["key"]]
                keep = bf.LS_KEEP_SECTIONS if b["action"] == "Show" else bf.LS_KEEP_HIDES
                if isinstance(v, str) or any(a <= (b["section"] or "") < z for a, z in keep.get(name, [])):
                    self.assertEqual(v, was, b["key"])
                else:
                    self.assertEqual(v, b["action"] == "Show", b["key"])
        # nothing left to loosen: the written files are a fixed point
        c, m = bf.league_start_values(conf, mods)
        flat = ls.flatten(conf), ls.flatten(mods)
        self.assertEqual([p for p, v in c.items() if flat[0].get(p) != v], [])
        self.assertEqual([p for p, v in m.items() if flat[1].get(p) != v], [])

    def test_refuses_double_start(self):
        self.run_tool("start")
        with self.assertRaises(SystemExit):
            self.run_tool("start")
        self.run_tool("start", "--force")  # backup = the loosened files now
        self.assertNotEqual((self.backup / "config.toml").read_bytes(), self.orig["config.toml"])

    def test_status_restore_finish(self):
        self.run_tool("start")
        out = self.run_tool("status")
        self.assertIn('hide_tiers: ["brown", "dust"] -> [] [loose]', out)
        self.assertIn("[jewels.blocks]", out)
        # partial restore: a key and a whole table go back, the rest stays loose
        self.run_tool("restore", "hide_tiers", "uniques.show")
        conf = tomllib.loads((self.root / "config.toml").read_text(encoding="utf-8"))
        orig = tomllib.loads(self.orig["config.toml"].decode())
        self.assertEqual(conf["hide_tiers"], orig["hide_tiers"])
        self.assertEqual(conf["uniques"]["show"], orig["uniques"]["show"])
        self.assertEqual(conf["small_loot"]["enabled"], False)
        out = self.run_tool("status")
        self.assertNotIn("hide_tiers", out)
        self.assertNotIn("uniques.show.", out)
        with self.assertRaises(SystemExit):
            self.run_tool("finish")                                  # still loose values
        self.run_tool("restore")                                     # everything: byte for byte
        for f in FILES:
            self.assertEqual((self.root / f).read_bytes(), self.orig[f], f)
        self.assertFalse(self.backup.exists())

    def test_tightened_by_hand_then_finish(self):
        self.run_tool("start")
        rows = ls.diffs(self.root, self.backup)
        for f in FILES:  # user edits every loose line back by hand (restore per key does the same)
            changes = {p: old for g, p, old, _ in rows if g == f}
            (self.root / f).write_text(ls.set_values(ls.read(self.root, f), changes), encoding="utf-8", newline="")
        self.assertIn("nothing differs", self.run_tool("status"))
        self.run_tool("finish")
        self.assertFalse(self.backup.exists())
        for f in FILES:
            self.assertEqual((self.root / f).read_bytes(), self.orig[f], f)

    def test_start_equals_league_start_flag(self):
        """Same filter: start-written files (flag off) vs repo files with league_start = true."""
        self.run_tool("start")
        script, flag = load_cfg(self.root), load_cfg(ROOT)
        flag["league_start"] = True
        bf.apply_league_start(flag)
        for cfg in (script, flag):  # fake data: no EV drop weights; gold on (gold_min_stack loosened)
            cfg["uniques"]["ev"]["enabled"] = False
            cfg["show_gold"] = True
        data = some_data()
        a, _ = bf.build_text(script, data, "Test")
        b, _ = bf.build_text(flag, some_data(), "Test")
        self.assertEqual(body(a), body(b))
        blocks = fs.parse(a)
        for item in ITEMS[:7]:
            self.assertTrue(fs.visible(blocks, item), item)
        self.assertFalse(fs.visible(blocks, ITEMS[7]))               # build never uses 2H swords: still hidden
        b, _ = fs.evaluate(blocks, ITEMS[2])
        self.assertEqual(b.comment, "gold: rest (campaign)")         # small gold: shown, small look kept
        self.assertTrue(fs.visible(blocks, ITEMS[8]))

    @unittest.skipUnless(latest_cache(), "no cache/ (run build_filter.py once)")
    def test_start_equals_flag_live_cache(self):
        self.run_tool("start")
        script, flag = load_cfg(self.root), load_cfg(ROOT)
        flag["league_start"] = True
        bf.apply_league_start(flag)
        a, _ = bf.build_text(script, load_cache(latest_cache(), script), "Live")
        b, _ = bf.build_text(flag, load_cache(latest_cache(), flag), "Live")
        self.assertEqual(body(a), body(b))

    def test_text_editor(self):
        text = ('a = 1   # one\n[t]\n"x.y" = "Hide # z"  # c\nl = [\n  "p", # q\n  "r",\n]\n'
                'i = { "0" = 1, b = 2 }\n')
        out = ls.set_values(text, {("a",): 2, ("t", "x.y"): "w", ("t", "l"): ["s"], ("t", "i", "b"): 3})
        self.assertEqual(out, 'a = 2   # one\n[t]\n"x.y" = "w"  # c\nl = ["s"]\ni = { 0 = 1, b = 3 }\n')
        with self.assertRaises(KeyError):
            ls.set_values(text, {("t", "missing"): 1})


if __name__ == "__main__":
    unittest.main()
