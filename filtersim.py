"""Tiny PoE1/PoE2 item filter evaluator, enough to replay items through the built filter.

Only the conditions our filter uses are modelled. An unknown condition raises, so a new
rule in rules/*.filter can't silently pass the tests: add it here first.
Used by tests/ and by report.py (shown/hidden per item).
"""
import re
import shlex

RARITY = {"Normal": 0, "Magic": 1, "Rare": 2, "Unique": 3}
ACTIONS = ("Set", "Play", "MinimapIcon", "DisableDropSound", "EnableDropSound",
           "CustomAlertSound", "Continue")
OPS = ("==", "!=", "<=", ">=", "=", "!", "<", ">")
NUMERIC = {"StackSize": "stack", "ItemLevel": "ilvl", "Quality": "quality",
           "LinkedSockets": "links", "CorruptedMods": "corrupted_mods", "Sockets": "sockets",
           "DropLevel": "drop_level", "Width": "width", "Height": "height", "AreaLevel": "area_level",
           "BaseArmour": "armour", "BaseEvasion": "evasion", "BaseEnergyShield": "es",
           "EnchantmentPassiveNum": "cluster_passives", "MemoryStrands": "memory_strands",
           "MapTier": "map_tier",
           "HasSearingExarchImplicit": "exarch_implicit", "HasEaterOfWorldsImplicit": "eater_implicit",
           "BaseDefencePercentile": "defence_percentile",
           # PoE2
           "GemLevel": "gem_level", "WaystoneTier": "waystone_tier",
           "UnidentifiedItemTier": "unid_tier"}
# Name conditions: "==" exact, else substring. EnchantmentPassiveNode = cluster jewel enchant
TEXT = {"Class": "class", "BaseType": "basetype", "EnchantmentPassiveNode": "cluster_node"}
# Missing item values. area_level: items are dropped in a map unless a test says otherwise.
DEFAULTS = {"area_level": 83}
BOOL = {"Corrupted": "corrupted", "Mirrored": "mirrored", "Identified": "identified",
        "Foulborn": "foulborn", "TransfiguredGem": "transfigured", "FracturedItem": "fractured",
        "BlightedMap": "blighted", "UberBlightedMap": "uber_blighted", "ZanaMemory": "zana_memory",
        "HasImplicitMod": "implicit", "Imbued": "imbued", "SynthesisedItem": "synthesised",
        "HasCruciblePassiveTree": "crucible", "Vestigial": "vestigial", "Replica": "replica",
        "Fated": "fated",  # PoE1 3.28 (Covens of Umbra)
        # PoE2
        "AnyEnchantment": "enchanted", "TwiceCorrupted": "twice_corrupted",
        "IsVaalUnique": "vaal_unique", "HasVaalUniqueMod": "vaal_unique_mod",
        "AlwaysShow": "always_show"}
# "HasExplicitMod >=2 ..." = at least 2 mods match one of the names
COUNT = re.compile(r"^(==|=|!=|<=|>=|<|>)(\d+)$")


class Block:
    def __init__(self, action, comment, line_no):
        self.action, self.comment, self.line_no = action, comment, line_no
        self.conds, self.style, self.cont = [], [], False

    def __repr__(self):
        return f"{self.action} #{self.comment} (line {self.line_no})"


def parse(text):
    blocks, cur = [], None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word = line.split()[0]
        if word in ("Show", "Hide", "Minimal"):
            cur = Block(word, line.partition("#")[2].strip(), no)
            blocks.append(cur)
        elif cur is None:
            raise ValueError(f"line {no}: rule outside a block: {line}")
        elif word == "Continue":
            cur.cont = True
        elif word.startswith(ACTIONS):
            cur.style.append(line)
        else:
            toks = shlex.split(line.partition(" #")[0])
            key, rest = toks[0], toks[1:]
            op = "="
            if rest and rest[0] in OPS:
                op, rest = rest[0], rest[1:]
            cur.conds.append((key, op, rest, no))
    return blocks


def _cmp(a, op, b):
    return {"=": a == b, "==": a == b, "!=": a != b, "!": a != b,
            "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _match(item, key, op, vals, no):
    if key in TEXT:
        have = item.get(TEXT[key]) or ""
        hit = any(have == v for v in vals) if op == "==" else any(v in have for v in vals)
        return not hit if op in ("!", "!=") else hit
    if key == "Rarity":
        r = RARITY[item.get("rarity", "Normal")]
        if op in ("=", "=="):
            return any(r == RARITY[v] for v in vals)
        if op in ("!", "!="):
            return all(r != RARITY[v] for v in vals)
        return _cmp(r, op, RARITY[vals[0]])
    if key == "Sockets" and re.search(r"[A-Z]", vals[0]):
        # "Sockets >= AAAA" / "5GGG": optional count + colour letters (A = abyss). Item field
        # "socket_colours" = one letter per socket; each letter needs at least that many
        m = re.fullmatch(r"(\d*)([RGBWAD]+)", vals[0])
        if not m or op not in ("=", "==", ">="):
            raise NotImplementedError(f"line {no}: Sockets {op} {vals[0]} not modelled in filtersim")
        have = item.get("socket_colours", "")
        return ((not m.group(1) or _cmp(item.get("sockets", 0), op, int(m.group(1))))
                and all(have.count(c) >= m.group(2).count(c) for c in set(m.group(2))))
    if key in NUMERIC:
        return _cmp(item.get(NUMERIC[key], DEFAULTS.get(NUMERIC[key], 0)), op, int(vals[0]))
    if key == "SocketGroup":
        return any(v in item.get("socket_group", "") for v in vals)
    if key == "HasExplicitMod":
        count = COUNT.match(vals[0]) if vals else None
        if count:
            hits = sum(1 for m in item.get("mods", []) if any(v in m for v in vals[1:]))
            return _cmp(hits, count.group(1), int(count.group(2)))
        if op in ("=", "=="):
            return any(v in m for v in vals for m in item.get("mods", []))
    if key in BOOL:
        return bool(item.get(BOOL[key], False)) == (vals[0] == "True")
    if key == "HasInfluence":
        infl = set(item.get("influence", []))
        if vals == ["None"]:
            return not infl
        return all(v in infl for v in vals) if op == "==" else any(v in infl for v in vals)
    raise NotImplementedError(f"line {no}: condition {key} not modelled in tests/filtersim.py")


def evaluate(blocks, item):
    """-> (deciding block, style lines applied incl. Continue blocks). None if nothing matched."""
    style = []
    for b in blocks:
        if all(_match(item, k, op, v, no) for k, op, v, no in b.conds):
            style += b.style
            if not b.cont:
                return b, style
    return None, style


def visible(blocks, item):
    b, _ = evaluate(blocks, item)
    return b is None or b.action != "Hide"
