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
from report import NINJA_CLASS, STACK_CLASS, unique_class  # noqa: E402

# Safety line: no unique worth this much (chaos) may sit on a hidden base. Fixed here on
# purpose, so raising config never_hide_chaos fails the tests instead of shrinking them.
SAFETY_CHAOS = 125


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
        self.data = empty_data()

    def build(self):
        text, r = bf.build_text(self.cfg, self.data, "Test")
        return fs.parse(text), r

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

    def test_crafting_base_jackpot_beats_floor(self):
        # ilvl 86 entry is a jackpot, but a cheaper higher-ilvl entry floors it
        for ilvl, chaos in [(86, 20 * 400), (87, 2)]:
            self.data["stash"]["BaseType"]["lines"].append(
                {"name": "Some Base", "variant": "Shaper", "levelRequired": ilvl, "chaosValue": chaos,
                 "listingCount": 50, "count": 10, "itemType": "Ring"})
        blocks, r = self.build()
        ring = {"class": "Rings", "basetype": "Some Base", "rarity": "Rare", "ilvl": 86, "influence": ["Shaper"]}
        self.assertTrue(fs.visible(blocks, ring))
        self.assertIn("variable", {e[0] for e in r["cbases"] if e[4] == "Some Base"})

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

    def test_base_with_only_boss_uniques_hidden(self):
        # Vermillion Ring: only Enmity's Embrace (memory boss) -> hidden, not "unpriced" blue
        self.data["nomap"] = {"Enmity's Embrace": "boss"}
        add_unique(self.data, "Vermillion Ring", "Enmity's Embrace", 5000, item_type="Ring")
        blocks, r = self.build()
        self.assertEqual(r["ubases"]["Vermillion Ring"][0], "hide")
        self.assertFalse(fs.visible(blocks, unid_unique("Vermillion Ring", "Rings")))

    def test_all_cheap_base_hidden(self):
        # the point of the filter: a base with only junk uniques is hidden
        add_unique(self.data, "Heavy Belt", "Junk A", 1)
        add_unique(self.data, "Heavy Belt", "Junk B", self.cfg["uniques"]["never_hide_chaos"] - 1)
        blocks, _ = self.build()
        self.assertFalse(fs.visible(blocks, unid_unique("Heavy Belt", "Belts")))

    def test_unpriced_unique_base_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Brand New Base", "Rings")))

    def test_top_base_stays_tink(self):
        add_unique(self.data, "Gold Ring", "Pricey", 300, item_type="Ring")
        add_unique(self.data, "Gold Ring", "Pricier", 900000, item_type="Ring")
        _, r = self.build()
        self.assertEqual(r["ubases"]["Gold Ring"][0], "top")

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
        self.assertEqual(r["fbases"]["Nubuck Boots"][0], "low")
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

    def test_small_loot_keeps_valuable_variant(self):
        # cheapest variant 2c, another 300c: never_hide_chaos keeps it visible (variable)
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
        tier, cheapest, best, _ = r["fbases"]["Lion Sword"]
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

    def test_unpriced_foulborn_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, unid_unique("Brand New Base", "Rings", foulborn=True)))

    def test_low_volume_expensive_card_shown(self):
        add_exchange(self.data, "DivinationCard", "Thin Card", 21, volume=3)
        add_exchange(self.data, "DivinationCard", "Thin Junk", 0.1, volume=1)
        blocks, r = self.build()
        self.assertIn("Thin Card", r["prices"])
        self.assertNotIn("Thin Junk", r["prices"])  # thin price not trusted to hide
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Thin Card"}))

    def test_cards_missing_from_ninja_use_reference_tiers(self):
        blocks, r = self.build()
        for card in ["Abandoned Wealth", "The Endless Darkness", "Brother's Stash", "House of Mirrors"]:
            self.assertIn(card, r["ref_cards"])
            self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": card}), card)
        self.assertTrue(fs.visible(blocks, {"class": "Divination Cards", "basetype": "Card From Next League"}))

    def test_stack_lifts_hidden_item(self):
        add_exchange(self.data, "Currency", "Half Orb", 0.5)
        blocks, _ = self.build()
        orb = {"class": "Stackable Currency", "basetype": "Half Orb"}
        self.assertFalse(fs.visible(blocks, dict(orb, stack=1)))
        self.assertTrue(fs.visible(blocks, dict(orb, stack=10)))

    def test_unknown_currency_shown(self):
        blocks, _ = self.build()
        self.assertTrue(fs.visible(blocks, {"class": "Stackable Currency", "basetype": "Orb Of Next League"}))

    def test_special_items_shown(self):
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
            "nomap": bf.non_map_drops(rows, cfg)}


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

    def test_valuable_uniques_visible_unidentified(self):
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
            if v >= SAFETY_CHAOS:
                items.append((f"{name} ({base}, {v:.0f}c)", unid_unique(base, cls)))
        self.assertGreater(len(items), 30)
        self.assert_all_visible(items, "valuable unique bases")

    def test_valuable_foulborn_visible_unidentified(self):
        items = []
        for t in bf.UNIQUE_TYPES:
            for line in self.data["stash"][t]["lines"]:
                if line["name"].startswith("Foulborn ") and line.get("baseType") and not line.get("links")                         and not bf.no_map_drop(self.data, line["name"]):
                    if line["chaosValue"] < SAFETY_CHAOS or line.get("listingCount", 0) < 1:
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
                if line.get("baseType") and line.get("listingCount", 0) >= 1 and line["chaosValue"] >= jackpot                         and not bf.no_map_drop(self.data, line["name"]):
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
        keep = {"top", "high", "mid", "low", "unknown", "variable"}
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
