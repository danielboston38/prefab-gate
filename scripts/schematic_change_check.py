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


def project(schematic: str) -> tuple[str, str]:
    """(project folder, root sheet relative to it) for any sheet of a project.

    A subsheet's netlist alone is incomplete, so a subsheet path is taken up to
    the nearest folder holding a .kicad_pro whose root sheet exists.
    """
    path = os.path.abspath(schematic)
    folder = os.path.dirname(path)
    for _ in range(4):
        for name in sorted(os.listdir(folder)):
            root = name[:-len(".kicad_pro")] + SHEET
            if name.endswith(".kicad_pro") and os.path.exists(os.path.join(folder, root)):
                return folder, root
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return os.path.dirname(path), os.path.basename(path)


def default_store(schematic: str) -> str:
    folder, _ = project(schematic)
    key = hashlib.sha256(folder.encode()).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".cache", "prefab-gate", "snapshots", key)


def _project_files(folder: str) -> list[str]:
    """Sheets in any subfolder, plus the project file and symbol table."""
    found = []
    for here, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        rel = os.path.relpath(here, folder)
        for name in files:
            if name.endswith(SHEET) or (rel == "." and (name.endswith(".kicad_pro")
                                                        or name == "sym-lib-table")):
                found.append(os.path.normpath(os.path.join(rel, name)))
    return sorted(found)


def _sheet_hashes(folder: str) -> dict[str, str]:
    return {n: _sha(os.path.join(folder, n)) for n in _project_files(folder) if n.endswith(SHEET)}


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def snapshot(schematic: str, store: str | None = None) -> str:
    folder, _ = project(schematic)
    store = store or default_store(schematic)
    # Build beside the store and swap it in, so no reader sees half a snapshot.
    parent = os.path.dirname(os.path.abspath(store))
    os.makedirs(parent, exist_ok=True)
    building = tempfile.mkdtemp(prefix=".building-", dir=parent)
    try:
        for name in _project_files(folder):
            os.makedirs(os.path.join(building, os.path.dirname(name)), exist_ok=True)
            shutil.copy2(os.path.join(folder, name), os.path.join(building, name))
        with open(os.path.join(building, HASHES), "w", encoding="utf-8") as f:
            json.dump(_sheet_hashes(building), f, indent=1)
        shutil.rmtree(store, ignore_errors=True)
        os.replace(building, store)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return store


def changed_files(schematic: str, store: str | None = None) -> list[str]:
    folder, _ = project(schematic)
    store = store or default_store(schematic)
    try:
        with open(os.path.join(store, HASHES), encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        raise NoSnapshot(f"no snapshot of {folder} in {store}; run `snapshot` first") from None
    now = _sheet_hashes(folder)
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
    folder, root = project(schematic)
    old = read_netlist(export(os.path.join(store, root)))
    new = read_netlist(export(os.path.join(folder, root)))
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
    except (NoSnapshot, ExportFailed, KicadUnavailable, OSError, ValueError) as e:
        print(f"schematic_change_check: {e}", file=sys.stderr)
        return 3
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
