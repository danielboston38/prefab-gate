#!/usr/bin/env python3
"""Say what changed electrically in a KiCad schematic since a snapshot.

    schematic_change_check.py snapshot <file.kicad_sch> [--store DIR]
    schematic_change_check.py diff     <file.kicad_sch> [--store DIR]

`diff` exits 0 when nothing changed electrically, 2 when something did (each
change is printed), and 3 when it could not run.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate.kicad import KicadUnavailable, locate_cli   # noqa: E402
from gate.schdiff import compare, read_netlist        # noqa: E402

HASHES = "hashes.json"
SHEET = ".kicad_sch"


class NoSnapshot(Exception):
    pass


class ExportFailed(Exception):
    pass


def default_store(schematic: str) -> str:
    folder = os.path.dirname(os.path.abspath(schematic))
    key = hashlib.sha256(folder.encode()).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".cache", "prefab-gate", "snapshots", key)


def _project_files(folder: str) -> list[str]:
    return sorted(n for n in os.listdir(folder)
                  if n.endswith((SHEET, ".kicad_pro")) or n == "sym-lib-table")


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def snapshot(schematic: str, store: str | None = None) -> str:
    folder = os.path.dirname(os.path.abspath(schematic))
    store = store or default_store(schematic)
    shutil.rmtree(store, ignore_errors=True)
    os.makedirs(store)
    hashes = {}
    for name in _project_files(folder):
        shutil.copy2(os.path.join(folder, name), os.path.join(store, name))
        if name.endswith(SHEET):
            hashes[name] = _sha(os.path.join(folder, name))
    with open(os.path.join(store, HASHES), "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=1)
    return store


def changed_files(schematic: str, store: str | None = None) -> list[str]:
    folder = os.path.dirname(os.path.abspath(schematic))
    store = store or default_store(schematic)
    try:
        with open(os.path.join(store, HASHES), encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        raise NoSnapshot(f"no snapshot of {folder} in {store}; run `snapshot` first") from None
    now = {n: _sha(os.path.join(folder, n)) for n in _project_files(folder) if n.endswith(SHEET)}
    return sorted(n for n in set(old) | set(now) if old.get(n) != now.get(n))


def kicad_export(sch_path: str) -> str:
    """The kicad-cli netlist of one schematic, as text."""
    cli = locate_cli()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "netlist.net")
        result = subprocess.run([cli, "sch", "export", "netlist", "-o", out, sch_path],
                                capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(out):
            raise ExportFailed(f"kicad-cli could not export {sch_path}: "
                               f"{result.stderr.strip() or result.returncode}")
        with open(out, encoding="utf-8") as f:
            return f.read()


def diff(schematic: str, store: str | None = None, export=kicad_export) -> tuple[int, list[str]]:
    store = store or default_store(schematic)
    changed = changed_files(schematic, store)
    if not changed:
        return 0, ["no change"]
    name = os.path.basename(schematic)
    old = read_netlist(export(os.path.join(store, name)))
    new = read_netlist(export(os.path.abspath(schematic)))
    lines = compare(old, new)
    if not lines:
        return 0, [f"file changed, connectivity unchanged: {', '.join(changed)}"]
    return 2, lines


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(3)


def main(argv=None, export=kicad_export) -> int:
    parser = _Parser(prog="schematic_change_check", description="Say what changed electrically in a KiCad schematic since a snapshot.")
    parser.add_argument("command", choices=("snapshot", "diff"))
    parser.add_argument("schematic")
    parser.add_argument("--store", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 3
    try:
        if args.command == "snapshot":
            print(f"snapshot saved: {snapshot(args.schematic, args.store)}")
            return 0
        code, lines = diff(args.schematic, args.store, export)
    except (NoSnapshot, ExportFailed, KicadUnavailable, OSError) as e:
        print(f"schematic_change_check: {e}", file=sys.stderr)
        return 3
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
