"""Tiny PoE1 item filter evaluator, enough to replay items through the built filter.

Only the conditions our filter uses are modelled. An unknown condition raises, so a new
rule in rules/*.filter can't silently pass the tests: add it here first.
Used by tests/ and by report.py (shown/hidden per item).
"""
import shlex

RARITY = {"Normal": 0, "Magic": 1, "Rare": 2, "Unique": 3}
ACTIONS = ("Set", "Play", "MinimapIcon", "DisableDropSound", "EnableDropSound",
           "CustomAlertSound", "Continue")
OPS = ("==", "!=", "<=", ">=", "=", "!", "<", ">")
NUMERIC = {"StackSize": "stack", "ItemLevel": "ilvl", "Quality": "quality",
           "LinkedSockets": "links", "CorruptedMods": "corrupted_mods", "Sockets": "sockets",
           "DropLevel": "drop_level", "Width": "width", "Height": "height", "AreaLevel": "area_level",
           "BaseArmour": "armour", "BaseEvasion": "evasion", "BaseEnergyShield": "es"}
# Missing item values. area_level: items are dropped in a map unless a test says otherwise.
DEFAULTS = {"area_level": 83}
BOOL = {"Corrupted": "corrupted", "Mirrored": "mirrored", "Identified": "identified",
        "Foulborn": "foulborn"}


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
    if key in ("Class", "BaseType"):
        have = item.get("class" if key == "Class" else "basetype") or ""
        hit = any(have == v for v in vals) if op == "==" else any(v in have for v in vals)
        return not hit if op in ("!", "!=") else hit
    if key == "Rarity":
        r = RARITY[item.get("rarity", "Normal")]
        if op in ("=", "=="):
            return any(r == RARITY[v] for v in vals)
        if op in ("!", "!="):
            return all(r != RARITY[v] for v in vals)
        return _cmp(r, op, RARITY[vals[0]])
    if key in NUMERIC:
        return _cmp(item.get(NUMERIC[key], DEFAULTS.get(NUMERIC[key], 0)), op, int(vals[0]))
    if key == "SocketGroup":
        return any(v in item.get("socket_group", "") for v in vals)
    if key == "HasExplicitMod" and op in ("=", "=="):
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
