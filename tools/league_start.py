"""League start: write "show (almost) everything" values INTO config.toml / modules.toml, so you
can tighten them one by one over the first week. Player guide: docs/LEAGUE_START.md.

    python tools/league_start.py start [--dry-run] [--force]   backup, then write loosened values
    python tools/league_start.py status                         what still differs from the backup
    python tools/league_start.py restore [KEY ...]              put backup values back
    python tools/league_start.py finish [--force]               done: delete the backup

The loosened values are build_filter.league_start_values: the same table config.toml
league_start = true applies at build time (one source of truth). Files are edited as text:
only the value of each changed `key = value` line is replaced, comments / order / spacing stay.
Backup: league_start/backup/ next to config.toml (gitignored, personal state); only start,
restore (no KEY) and finish touch it. KEY = dotted path, a prefix picks a whole table:
uniques.show.minor, uniques, exchange.reference_card_tiers, jewels.blocks, modules.toml ...
--root DIR: folder with config.toml / modules.toml (default: the repo; tests use temp copies).
"""
import argparse
import json
import shutil
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import build_filter as bf  # noqa: E402

FILES = ("config.toml", "modules.toml")


# ---------------------------------------------------------------- TOML text editing

def _parse_key(text, i):
    """Dotted key at text[i:] -> (parts, index after the key). Bare / "basic" / 'literal' parts."""
    parts = []
    while True:
        while i < len(text) and text[i] in " \t":
            i += 1
        if i < len(text) and text[i] == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            parts.append(json.loads(text[i:j + 1]))
            i = j + 1
        elif i < len(text) and text[i] == "'":
            j = text.index("'", i + 1)
            parts.append(text[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] in "_-"):
                j += 1
            if j == i:
                raise ValueError(f"bad key: {text!r}")
            parts.append(text[i:j])
            i = j
        while i < len(text) and text[i] in " \t":
            i += 1
        if i < len(text) and text[i] == ".":
            i += 1
            continue
        return parts, i


def _value_end(lines, row, start):
    """Value starting at lines[row][start:] -> (last row, end column on that row) of the value
    itself (multi-line arrays included, trailing comment and spaces excluded)."""
    for last in range(row, len(lines)):
        head = lines[row][start:] + "".join(lines[row + 1:last + 1])
        try:
            tomllib.loads("x = " + head)
        except tomllib.TOMLDecodeError:
            continue
        tail = lines[last].rstrip("\r\n")
        first = start if last == row else 0
        before = lines[row][start:] + "".join(lines[row + 1:last]) if last > row else ""
        for c in [c for c in range(first, len(tail)) if tail[c] == "#"] + [len(tail)]:
            try:
                tomllib.loads("x = " + before + tail[first:c] + "\n")
            except tomllib.TOMLDecodeError:
                continue
            return last, len(tail[:c].rstrip())
    raise ValueError(f"cannot parse value at line {row + 1}")


def index_values(text):
    """TOML text -> {key path tuple: (row, col, last row, end col)} of every key's value."""
    lines = text.splitlines(keepends=True)
    out, table, row = {}, (), 0
    while row < len(lines):
        s = lines[row].strip()
        if not s or s.startswith("#"):
            row += 1
            continue
        if s.startswith("["):
            if s.startswith("[["):
                raise ValueError("arrays of tables not supported")
            parts, i = _parse_key(s, 1)
            table = tuple(parts)
            row += 1
            continue
        line = lines[row]
        indent = len(line) - len(line.lstrip())
        parts, i = _parse_key(line, indent)
        if line[i] != "=":
            raise ValueError(f"line {row + 1}: expected '=': {line!r}")
        i += 1
        while line[i] in " \t":
            i += 1
        last, end = _value_end(lines, row, i)
        out[table + tuple(parts)] = (row, i, last, end)
        row = last + 1
    return out


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{dotted((k,))} = {toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"no TOML writer for {v!r}")


def set_values(text, changes):
    """Replace the values of existing keys (path -> value) in TOML text; comments, order and
    spacing stay. Missing key = error (no hidden settings: every key is written out)."""
    idx, parsed = index_values(text), tomllib.loads(text)
    flat = flatten(parsed)
    changes = {p: v for p, v in changes.items() if p not in flat or flat[p] != v}  # unchanged: text as is
    for p in [p for p in changes if p not in idx]:
        pre = next((p[:n] for n in range(len(p) - 1, 0, -1) if p[:n] in idx), None)
        if pre is None:
            continue
        whole = changes.get(pre) or json.loads(json.dumps(_get(parsed, pre)))  # inline table: write it whole
        _set(whole, p[len(pre):], changes.pop(p))
        changes[pre] = whole
    missing = [p for p in changes if p not in idx]
    if missing:
        raise KeyError("not in file (add it with its default first): " + ", ".join(".".join(p) for p in missing))
    lines = text.splitlines(keepends=True)
    for path in sorted(changes, key=lambda p: idx[p][0], reverse=True):
        row, col, last, end = idx[path]
        lines[row:last + 1] = [lines[row][:col] + toml_value(changes[path]) + lines[last][end:]]
    out = "".join(lines)
    tomllib.loads(out)  # still valid
    return out


def _get(d, path):
    for k in path:
        d = d[k]
    return d


def _set(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def flatten(d, path=()):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, path + (k,)))
        else:
            out[path + (k,)] = v
    return out


def dotted(path):
    bare = lambda p: p and all(ch.isalnum() or ch in "_-" for ch in p)
    return ".".join(p if bare(p) else json.dumps(p, ensure_ascii=False) for p in path)


# ---------------------------------------------------------------- commands

def read(root, name):
    with open(root / name, encoding="utf-8", newline="") as f:  # keep CRLF: only values change
        return f.read()


def loosened(root):
    """{file name: {path: loosened value}} for the files in root."""
    conf, mods = (tomllib.loads(read(root, f)) for f in FILES)
    c, m = bf.league_start_values(conf, mods)
    return {"config.toml": c, "modules.toml": m}


def diffs(root, backup):
    """[(file, path, backup value, current value)] of every leaf that differs."""
    out = []
    for f in FILES:
        old, new = (flatten(tomllib.loads(read(d, f))) for d in (backup, root))
        for p in sorted(set(old) | set(new), key=lambda p: [str(x) for x in p]):
            if old.get(p, "<missing>") != new.get(p, "<missing>"):
                out.append((f, p, old.get(p, "<missing>"), new.get(p, "<missing>")))
    return out


def cmd_start(root, backup, dry_run=False, force=False):
    if backup.exists() and not force and not dry_run:
        sys.exit(f"{backup} exists: league start already running (status / restore / finish), "
                 "or --force to overwrite that backup")
    todo = {}
    current = {f: flatten(tomllib.loads(read(root, f))) for f in FILES}
    for f, changes in loosened(root).items():
        todo[f] = {p: v for p, v in changes.items() if current[f].get(p) != v}
    for f, changes in todo.items():
        print(f"{f}: {len(changes)} values loosened")
        for p, v in changes.items():
            print(f"  {dotted(p)}: {toml_value(current[f].get(p))} -> {toml_value(v)}")
    if dry_run:
        return
    texts = {f: set_values(read(root, f), todo[f]) for f in FILES}  # all parse before anything is written
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(root / f, backup / f)
    for f in FILES:
        (root / f).write_text(texts[f], encoding="utf-8", newline="")
    if current["config.toml"].get(("league_start",)):
        print("note: config.toml league_start = true: set it to false, the values above do its job now")
    print(f"backup: {backup}\nnext: python build_filter.py   (tighten later: tools/league_start.py status)")


def cmd_status(root, backup):
    if not backup.exists():
        sys.exit("no league start backup (run: tools/league_start.py start)")
    loose = loosened(backup)  # what start wrote
    rows = diffs(root, backup)
    where = {f: index_values(read(root, f)) for f in FILES}
    if not rows:
        print("nothing differs from the backup: everything tightened. Done: tools/league_start.py finish")
        return
    print(f"{len(rows)} values differ from the backup (backup -> now; [loose] = still the league-start value):")
    group = None
    for f, p, old, new in rows:
        table = p[:2] if f == "modules.toml" else p[:1] if len(p) > 1 else ()
        if (f, table) != group:
            group = (f, table)
            print(f"\n{f} [{dotted(table)}]" if table else f"\n{f} (top level)")
        mark = " [loose]" if loose[f].get(p, object()) == new else ""
        fmt = lambda v: v if v == "<missing>" else toml_value(v)
        row = next((where[f][p[:n]][0] + 1 for n in range(len(p), 0, -1) if p[:n] in where[f]), None)
        print(f"  {dotted(p)}: {fmt(old)} -> {fmt(new)}{mark}" + (f"   (line {row})" if row else ""))
    print("\nTighten: edit those lines, or tools/league_start.py restore KEY ... ; then python build_filter.py")


def cmd_restore(root, backup, keys):
    if not backup.exists():
        sys.exit("no league start backup")
    if not keys:
        for f in FILES:
            shutil.copy2(backup / f, root / f)
        shutil.rmtree(backup)
        if backup.parent.name == "league_start" and not any(backup.parent.iterdir()):
            backup.parent.rmdir()
        print("restored config.toml + modules.toml from the backup (byte for byte), backup deleted")
        return
    rows = diffs(root, backup)
    picked = {}
    for f, p, old, new in rows:
        name = ".".join(p)
        if any(k in (f, name) or name.startswith(k + ".") or f"{f}:{name}".startswith(k) for k in keys):
            if old == "<missing>" or new == "<missing>":
                print(f"skip {f} {dotted(p)}: key added / removed since start, edit by hand")
                continue
            picked.setdefault(f, {})[p] = old
    if not picked:
        sys.exit("no differing key matches " + " ".join(keys) + " (see status)")
    for f, changes in picked.items():
        (root / f).write_text(set_values(read(root, f), changes), encoding="utf-8", newline="")
        for p, v in changes.items():
            print(f"{f}: {dotted(p)} = {toml_value(v)}")


def cmd_finish(root, backup, force=False):
    if not backup.exists():
        sys.exit("no league start backup")
    rows = diffs(root, backup)
    if rows and not force:
        sys.exit(f"{len(rows)} values still differ from the backup (status); keep them: finish --force")
    shutil.rmtree(backup)
    print("backup deleted: league start finished")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=REPO, help="folder with config.toml / modules.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    r = sub.add_parser("restore")
    r.add_argument("keys", nargs="*")
    f = sub.add_parser("finish")
    f.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    backup = root / "league_start" / "backup"
    if a.cmd == "start":
        cmd_start(root, backup, a.dry_run, a.force)
    elif a.cmd == "status":
        cmd_status(root, backup)
    elif a.cmd == "restore":
        cmd_restore(root, backup, a.keys)
    else:
        cmd_finish(root, backup, a.force)


if __name__ == "__main__":
    main()
