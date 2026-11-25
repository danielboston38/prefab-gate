import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import schematic_change_check as scc
from test_schdiff import NETS, PARTS, netlist

CHANGED = [("R5", "4k7", "R_0603"), PARTS[1]]


class FakeExport:
    """Stands in for kicad-cli: the netlist depends on the file's text."""

    def __init__(self):
        self.calls = []

    def __call__(self, sch_path):
        self.calls.append(sch_path)
        with open(sch_path, encoding="utf-8") as f:
            text = f.read()
        return netlist(CHANGED if "4k7" in text else PARTS, NETS)


class Project:
    def __init__(self, test, sheets=("top.kicad_sch",)):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "proj")
        self.store = os.path.join(tmp.name, "store")
        os.mkdir(self.dir)
        for name in sheets:
            self.write(name, "(kicad_sch R5 10k)")
        self.top = os.path.join(self.dir, sheets[0])

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)


class Snapshot(unittest.TestCase):
    def test_snapshot_copies_all_sheets(self):
        p = Project(self, ("top.kicad_sch", "sub.kicad_sch"))
        scc.snapshot(p.top, p.store)
        self.assertTrue(os.path.exists(os.path.join(p.store, "sub.kicad_sch")))
        with open(os.path.join(p.store, "hashes.json"), encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)), ["sub.kicad_sch", "top.kicad_sch"])

    def test_store_outside_project(self):
        p = Project(self)
        self.assertFalse(os.path.realpath(scc.default_store(p.top))
                         .startswith(os.path.realpath(p.dir)))

    def test_new_snapshot_replaces_old(self):
        p = Project(self, ("top.kicad_sch", "sub.kicad_sch"))
        scc.snapshot(p.top, p.store)
        os.remove(os.path.join(p.dir, "sub.kicad_sch"))
        scc.snapshot(p.top, p.store)
        self.assertFalse(os.path.exists(os.path.join(p.store, "sub.kicad_sch")))


class Diff(unittest.TestCase):
    def test_unchanged_files_skip_kicad_cli(self):
        p = Project(self)
        export = FakeExport()
        scc.snapshot(p.top, p.store)
        self.assertEqual(scc.diff(p.top, p.store, export), (0, ["no change"]))
        self.assertEqual(export.calls, [])

    def test_cosmetic_change(self):
        p = Project(self)
        scc.snapshot(p.top, p.store)
        p.write("top.kicad_sch", "(kicad_sch R5 10k (text moved))")
        self.assertEqual(scc.diff(p.top, p.store, FakeExport()),
                         (0, ["file changed, connectivity unchanged: top.kicad_sch"]))

    def test_electrical_change_exits_2(self):
        p = Project(self)
        scc.snapshot(p.top, p.store)
        p.write("top.kicad_sch", "(kicad_sch R5 4k7)")
        self.assertEqual(scc.diff(p.top, p.store, FakeExport()),
                         (2, ["R5 value 10k -> 4k7"]))

    def test_sheet_added_counts_as_changed(self):
        p = Project(self)
        scc.snapshot(p.top, p.store)
        p.write("sub.kicad_sch", "(kicad_sch)")
        self.assertEqual(scc.changed_files(p.top, p.store), ["sub.kicad_sch"])

    def test_diff_without_snapshot_raises(self):
        p = Project(self)
        with self.assertRaises(scc.NoSnapshot):
            scc.diff(p.top, p.store, FakeExport())


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = scc.main(list(args), export=FakeExport())
        return code, out.getvalue(), err.getvalue()

    def test_diff_without_snapshot_exits_3(self):
        p = Project(self)
        code, _, err = self.run_cli("diff", p.top, "--store", p.store)
        self.assertEqual(code, 3)
        self.assertIn("no snapshot", err)

    def test_snapshot_then_change_exits_2(self):
        p = Project(self)
        self.assertEqual(self.run_cli("snapshot", p.top, "--store", p.store)[0], 0)
        p.write("top.kicad_sch", "(kicad_sch R5 4k7)")
        code, out, _ = self.run_cli("diff", p.top, "--store", p.store)
        self.assertEqual((code, out), (2, "R5 value 10k -> 4k7\n"))

    def test_usage_error_exits_3(self):
        code, _, _ = self.run_cli("frobnicate")
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
