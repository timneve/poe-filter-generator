"""Parity with the user's FilterBlade filter: every item reference/league.filter shows must be
shown by ours, unless the reason is known (confident poe.ninja price in a hidden tier, or an
explicit decision in EXPLAINED below).

Run:  python -m unittest discover tests -k parity
      python tests/test_parity.py          (full listing: gaps, explained counts, reverse direction)

Corpus (replays cache/<league>/, skipped without it):
  - cache items: every priced stackable, fallback-tier currency / card (+ every card x3), unique base (unID,
    + Foulborn), poe.ninja base / gem / cluster / map line, as it drops (test_filter helpers);
  - one item per league.filter Show block and BaseType value, built from the block's own
    conditions (`items_for_block`), so every FilterBlade feature is probed.
Both filters are evaluated with filtersim (league.filter conditions all modelled).
"""
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_filter as bf  # noqa: E402
import filtersim as fs  # noqa: E402
import test_filter as tf  # noqa: E402  (module import: its TestCases must not run twice)
from report import STACK_CLASS, unique_class  # noqa: E402

REF = ROOT / "reference" / "league.filter"

# Why our filter may hide an item league.filter shows: regex on OUR deciding Hide block's
# comment -> reason. "price:" = a confident poe.ninja price (or price-derived EV) in a tier
# config.toml hides; the rest = explicit decisions. Keep each reason specific.
EXPLAINED = [
    # --- price (poe.ninja, confident) in a config-hidden tier
    (r"^(brown|dust|low|minor)( stack x\d+)?$", "price: stackable / card priced in a hidden tier"),
    (r"^priced below lowest tier$", "price: stackable priced below the lowest tier"),
    (r"priced below gems\.min_tier", "price: gem variant priced below [gems] min_tier"),
    (r"^unique", "price: unique base (EV / cheapest unique) in a hidden tier ([uniques.show])"),
    (r"^foulborn", "price: Foulborn base priced in a hidden tier ([foulborn] min_tier)"),
    (r"^corrupted map below \[maps\] corrupted_min_tier", "price: corrupted map tier ([maps] corrupted_min_tier)"),
    # --- explicit config decisions (config.toml, documented there)
    (r"^override hide$", "decision: config.toml [overrides] = hide"),
    (r"config tier hide$", "decision: config.toml [exchange.unpriced_tiers] hide (FilterBlade conditional Hides)"),
    (r"^unpriced cards, reference tier hide", "decision: unpriced low-volume card, regular NeverSink group "
                                              "t4 / t4c / t5 / t5c -> hide ([exchange.reference_card_tiers]): "
                                              "ranked cheap by NeverSink, not 'maybe valuable'"),
    (r"^unpriced currency, reference tier (dust|brown)", "decision: unpriced currency, NeverSink tier 5+ "
                                                         "([exchange.reference_currency_tiers]): ranked cheap"),
    (r"show_contracts|hide_forbidden_tome|show_gold", "decision: config.toml toggle"),
]


def ref_classes(blocks):
    """BaseType -> Class from league.filter blocks naming exactly one class ("==": exact name)."""
    out = {}
    for b in blocks:
        cls = [v for k, op, v, _ in b.conds if k == "Class" and op == "=="]
        if len(cls) == 1 and len(cls[0]) == 1:
            for k, op, vals, _ in b.conds:
                if k == "BaseType":
                    for v in vals:
                        out.setdefault(v, cls[0][0])
    return out


def _bound(lo, hi, field, op, n):
    """Narrow the [lo, hi] range of one numeric field by a condition."""
    if op in (">=", ">"):
        lo[field] = max(lo.get(field, -1), n + (op == ">"))
    elif op in ("<=", "<"):
        hi[field] = min(hi.get(field, 10 ** 9), n - (op == "<"))
    elif op in ("=", "=="):
        lo[field] = hi[field] = n
    else:  # != : any other value
        lo[field] = n + 1


def items_for_block(block, base_class):
    """Items matching every condition of one league.filter block: one per BaseType value (first
    otherwise) and rarity the block allows (no Rarity line + a Class line: Normal / Magic / Rare;
    no Class: Normal). Numbers at the bound the block names (lower bound first), ilvl = area
    level unless the block bounds it. May still be decided by an
    earlier league.filter block: the caller evaluates the whole filter."""
    conds = block.conds
    bases = next((v for k, op, v, _ in conds if k == "BaseType" and op not in ("!", "!=")), [None])
    classes = next((v for k, op, v, _ in conds if k == "Class" and op not in ("!", "!=")), None)
    out = []
    for base in bases:
        it, lo, hi = {"stack": 1}, {}, {}
        rarities = ["Normal", "Magic", "Rare"] if classes else ["Normal"]
        if base:
            it["basetype"] = base
        if classes:
            it["class"] = base_class.get(base) if base_class.get(base) in classes else classes[0]
            if base and it["class"] == "Skill Gems" and base.endswith(" Support"):
                it["class"] = "Support Gems"
        for k, op, vals, _ in conds:
            if k in ("Class", "BaseType"):
                continue
            if k in fs.TEXT:  # EnchantmentPassiveNode
                if op not in ("!", "!="):
                    it[fs.TEXT[k]] = vals[0]
            elif k == "Rarity":
                r = fs.RARITY
                if op in ("=", "=="):
                    rarities = list(vals)
                else:
                    rarities = [n for n in r if fs._cmp(r[n], op, r[vals[0]])]
            elif k == "Sockets" and re.search(r"[A-Z]", vals[0]):
                m = re.fullmatch(r"(\d*)([RGBWAD]+)", vals[0])
                it["socket_colours"] = m.group(2)
                it["sockets"] = max(int(m.group(1) or 0), len(m.group(2)))
            elif k in fs.NUMERIC:
                _bound(lo, hi, fs.NUMERIC[k], op, int(vals[0]))
            elif k == "SocketGroup":
                it["socket_group"] = vals[0]
            elif k == "HasExplicitMod":
                count = fs.COUNT.match(vals[0])
                if count:  # ">=2 a b c": that many of the names; "<1": none
                    c, n = count.group(1), int(count.group(2))
                    it["mods"] = vals[1:1 + n + (c == ">")] if c in ("=", "==", ">=", ">") else []
                else:
                    it["mods"] = vals[:1]
            elif k in fs.BOOL:
                it[fs.BOOL[k]] = vals[0] == "True"
            elif k == "HasInfluence":
                it["influence"] = [] if vals == ["None"] else (list(vals) if op == "==" else vals[:1])
            else:
                raise NotImplementedError(f"items_for_block: {k}")
        for f in set(lo) | set(hi):
            it[f] = lo[f] if f in lo else hi[f]
        it.setdefault("area_level", fs.DEFAULTS["area_level"])
        it.setdefault("ilvl", it["area_level"])
        out += [dict(it, rarity=r) for r in rarities]
    return out


def cache_items(tc):
    """(label, item) for every cache-priced item, as it drops."""
    r, data, cls_of = tc.r, tc.data, tc.base_class
    items = []
    for n, (v, t) in r["prices"].items():
        items.append((f"stackable {n}", {"class": cls_of.get(n, STACK_CLASS.get(t, "Stackable Currency")),
                                         "basetype": n, "stack": 1}))
    for n in set(r["ref_currency"]) - set(r["prices"]):
        items.append((f"fallback currency {n}", {"class": cls_of.get(n, "Stackable Currency"), "basetype": n, "stack": 1}))
    for n in set(r["ref_cards"]) - set(r["prices"]):
        items.append((f"fallback card {n}", {"class": "Divination Cards", "basetype": n, "stack": 1}))
    cards = {n for n, (_, t) in r["prices"].items() if t == "DivinationCard"} | set(r["ref_cards"])
    items += [(f"card {n} x3", {"class": "Divination Cards", "basetype": n, "stack": 3}) for n in cards]
    seen = set()
    for t in bf.UNIQUE_TYPES:
        for line in data["stash"][t]["lines"]:
            base = line.get("baseType")
            foul = line["name"].startswith("Foulborn ")
            if not base or bf.no_map_drop(data, line["name"]) or (base, foul) in seen:
                continue
            seen.add((base, foul))
            items.append((f"unique base {base}" + (" (Foulborn)" if foul else ""),
                          tf.unid_unique(base, unique_class(line, t), foulborn=foul)))
    for t in bf.BASE_TYPES + bf.CHECK_TYPES:
        for line in data["stash"][t]["lines"]:
            if line.get("listingCount", 0) < 1:
                continue
            try:
                item = tf.LiveCache.ninja_drop(tc, t, line)
            except AssertionError:  # unknown cluster node: test_filter's own check
                continue
            if item is not None:
                items.append((f"{t} {line['name']} [{line.get('variant') or ''}] ilvl{line.get('levelRequired', '')}",
                              dict({"area_level": 83, "stack": 1}, **item)))
    return items


# Price decisions the user confirmed where league.filter shows by a rule instead of a price
STACKED_CARDS = ("decision: card stacks decided by price x stack (league.filter exstack shows any 3 cards; "
                 "user: confident cheap card 3-stacks stay hidden)")
GEMS_18_20 = ("decision: cheap level 18-20 gems decided by price (league.filter lt2 / lt3 show every "
              "level 18+ gem; user: price decides)")


def explain(comment):
    return next((reason for rx, reason in EXPLAINED if re.search(rx, comment)), None)


def overquality_reason(cfg, ref_block):
    """league.filter showed the item by a quality-threshold block that config.toml
    [overquality] turns off (OVERQUALITY_KEYS / OVERQUALITY_TOGGLES)."""
    toggles = dict(bf.OVERQUALITY_TOGGLES, **{k: f"quality_{n}" for k, n in bf.OVERQUALITY_KEYS.items()})
    for key, name in toggles.items():
        typ, tier = key.rsplit(".", 1)
        if (re.search(rf"\$type->{re.escape(typ)}\s+\$tier->{re.escape(tier)}(?!\w)", ref_block.comment or "")
                and not cfg["overquality"][name]):
            return f"decision: config.toml [overquality] {name} = false"
    return None


def reason_for(tc, block, it, ref_block=None):
    reason = (explain(block.comment) or price_reason(tc, it)
              or (overquality_reason(tc.cfg, ref_block) if ref_block else None))
    if reason and reason.startswith("price"):
        if it.get("class") == "Divination Cards" and it.get("stack", 1) > 1:
            return STACKED_CARDS
        if it.get("class") in ("Skill Gems", "Support Gems") and 18 <= it.get("gem_level", 1) <= 20:
            return GEMS_18_20
    return reason


def price_reason(tc, it):
    """Item-level price explanation where our hiding block is a generic catch-all
    (rules/bottom.filter, rare hide layer): poe.ninja knows the item confidently and below the
    shown floor, so no price Show exists for it."""
    cfg, data = tc.cfg, tc.data
    if it.get("class") in ("Skill Gems", "Support Gems"):
        # the variant at or below the item's level / quality: emit_gems' GemLevel >= / Quality >=
        floor = tc.cfg["tiers"][cfg.get("gems", {}).get("min_tier", "minor")]
        for t in ("SkillGem", "ImbuedGem"):
            for l in data["stash"][t]["lines"]:
                if (l["name"] == it.get("basetype") and not bf.alt_gem(l)
                        and l.get("listingCount", 0) >= cfg["uniques"]["min_listings"]
                        and bool(l.get("corrupted")) == bool(it.get("corrupted"))):
                    lq, iq = (l.get("gemLevel", 1), l.get("gemQuality") or 0), (it.get("gem_level", 1), it.get("quality", 0))
                    if lq[0] <= iq[0] and lq[1] <= iq[1]:
                        return "price: gem variant confidently priced below [gems] min_tier (bottom.filter hides)"
                    if lq[0] >= iq[0] and lq[1] >= iq[1] and l["chaosValue"] < floor:
                        return "price: gem capped by a confident better variant below [gems] min_tier (gem_caps)"
    if it.get("rarity") in ("Normal", "Magic", "Rare") and it.get("basetype"):
        b = cfg["bases"]
        infl = "/".join(it.get("influence") or []) or None
        lines = [l for l in data["stash"]["BaseType"]["lines"] + data["stash"]["Flask"]["lines"]
                 if l["name"] == it["basetype"] and (l.get("variant") or None) == infl
                 and l.get("levelRequired", 0) <= it.get("ilvl", 0)]
        if lines:
            l = max(lines, key=lambda l: l.get("levelRequired", 0))  # covers its own ilvl range only
            if (l.get("listingCount", 0) >= b["min_listings"] and l.get("count", 0) >= b["min_samples"]
                    and tc.r["tiers"].rank(tc.r["tiers"].of(l["chaosValue"])) > tc.r["tiers"].rank(b["min_tier"])):
                return "price: crafting base (base + influence + ilvl) confidently below [bases] min_tier"
    return None


@unittest.skipIf(tf.CACHE is None or not REF.exists(), "no price cache / reference/league.filter")
class Parity(unittest.TestCase):
    longMessage = False

    @classmethod
    def setUpClass(cls):
        cls.cfg = bf.load_cfg()
        cls.data = tf.load_cache(tf.CACHE, cls.cfg)
        text, cls.r = bf.build_text(cls.cfg, cls.data, tf.CACHE.name)
        cls.ours = fs.parse(text)
        cls.ref = fs.parse(REF.read_text(encoding="utf-8"))
        cls.cluster_nodes = bf.module_cluster_nodes()
        cls.base_class = ref_classes(cls.ref)
        cls.corpus = cache_items(cls("test_corpus_size"))  # instance: ninja_drop asserts
        for b in cls.ref:
            if b.action == "Show":
                cls.corpus += [(f"league.filter line {b.line_no} {it.get('class')} / {it.get('basetype')}", it)
                               for it in items_for_block(b, cls.base_class)]
        cls.gaps, cls.explained, cls.reverse = [], Counter(), Counter()
        for label, it in cls.corpus:
            ref_shows, ours_shows = fs.visible(cls.ref, it), fs.visible(cls.ours, it)
            if ref_shows and not ours_shows:
                block = fs.evaluate(cls.ours, it)[0]
                reason = reason_for(cls, block, it, fs.evaluate(cls.ref, it)[0])
                if reason:
                    cls.explained[reason] += 1
                else:
                    cls.gaps.append((label, block, it))
            elif ours_shows and not ref_shows:
                cls.reverse[it.get("class") or "?"] += 1

    def test_corpus_size(self):
        self.assertGreater(len(self.corpus), 5000)

    def test_shown_by_league_filter_shown_by_ours(self):
        lines = [f"  {lab}  <- ours: {b}" for lab, b, _ in self.gaps[:60]]
        self.assertFalse(self.gaps, f"{len(self.gaps)} items league.filter shows, ours hides without "
                                    f"a known reason (fix, or add to EXPLAINED with a reason):\n" + "\n".join(lines))

    def test_reference_conditions_modelled(self):
        for b in self.ref:
            for k, op, v, no in b.conds:
                try:
                    fs._match({}, k, op, v, no)
                except NotImplementedError as e:
                    self.fail(str(e))
                except (KeyError, ValueError, IndexError):
                    pass


class NoReference(unittest.TestCase):
    """The build never reads reference/ (only tools/import_*.py do)."""

    def test_build_without_reference(self):
        real = {name: getattr(Path, name) for name in ("read_text", "read_bytes", "open")}

        def guard(name):
            def f(self, *a, **k):
                if "reference" in self.parts:
                    raise AssertionError(f"build read {self}")
                return real[name](self, *a, **k)
            return f
        try:
            for name in real:
                setattr(Path, name, guard(name))
            cfg = bf.load_cfg()
            text, _ = bf.build_text(cfg, tf.empty_data(), "Test")
            cfg = bf.load_cfg()
            cfg["league_start"] = True
            bf.build_text(bf.apply_league_start(cfg), tf.empty_data(), "Test")
        finally:
            for name, fn in real.items():
                setattr(Path, name, fn)
        self.assertIn("Show", text)

    @unittest.skipUnless(REF.exists(), "no reference/league.filter")
    def test_importer_still_parses_reference(self):
        # tools/import_neversink.py owns the NeverSink parser now: heist keys round-trip
        sys.path.insert(0, str(ROOT / "tools"))
        import import_neversink as imp
        blocks = imp.parse_ref_blocks(REF.read_text(encoding="utf-8"), "2900", "3000")
        self.assertEqual([b["key"] for b in blocks], list(bf.load_cfg()["modules"]["heist"]["blocks"]))


if __name__ == "__main__":
    Parity.setUpClass()
    p = Parity
    print(f"corpus {len(p.corpus)}; gaps {len(p.gaps)}")
    for comment, n in Counter(b.comment for _, b, _ in p.gaps).most_common():
        print(f"  {n:5}  {comment}")
    for lab, b, it in p.gaps[:200]:
        print(f"    {lab}  <- {b}  {it}")
    print("explained:")
    for reason, n in p.explained.most_common():
        print(f"  {n:5}  {reason}")
    print("reverse (ours shows, league.filter hides) by class:")
    for cls, n in p.reverse.most_common():
        print(f"  {n:5}  {cls}")
