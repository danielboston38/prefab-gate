"""Staging picks the files DRC needs and nothing else."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "kicad"))

from plugin import staging  # noqa: E402


def _write(path, text):
    with open(path, "w") as handle:
        handle.write(text)
    return path


def _read(path):
    with open(path) as handle:
        return handle.read()


def _project(tmp, *, pro=True, dru=True, sheets=(), libs=False):
    """A believable KiCad project directory. Returns the board path."""
    board = _write(os.path.join(tmp, "demo.kicad_pcb"), "(kicad_pcb)")
    _write(os.path.join(tmp, "demo.kicad_sch"), "(kicad_sch)")
    for name in sheets:
        _write(os.path.join(tmp, name + ".kicad_sch"), "(kicad_sch)")
    if pro:
        _write(os.path.join(tmp, "demo.kicad_pro"), "{}")
    if dru:
        _write(os.path.join(tmp, "demo.kicad_dru"), "(version 1)")
    if libs:
        _write(os.path.join(tmp, "fp-lib-table"),
               '(fp_lib_table\n(lib (name "local") (type "KiCad")'
               ' (uri "${KIPRJMOD}/Local.pretty") (options "") (descr ""))\n)')
        _write(os.path.join(tmp, "sym-lib-table"),
               '(sym_lib_table\n(lib (name "s") (type "KiCad")'
               ' (uri "${KIPRJMOD}/Local.pretty/s.kicad_sym"))\n)')
        os.mkdir(os.path.join(tmp, "Local.pretty"))
        _write(os.path.join(tmp, "Local.pretty", "part.kicad_mod"), "(footprint)")
        _write(os.path.join(tmp, "Local.pretty", "s.kicad_sym"), "(symbol)")
    return board


class CollectTest(unittest.TestCase):

    def test_board_comes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp)
            self.assertEqual(staging.collect(board)[0], os.path.abspath(board))

    def test_collects_every_schematic_sheet(self):
        """Hierarchical designs have more than the root sheet, and parity
        needs all of them."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp, sheets=("power", "video"))
            names = {os.path.basename(p) for p in staging.collect(board)}
            self.assertEqual(
                {"demo.kicad_sch", "power.kicad_sch", "video.kicad_sch"},
                {n for n in names if n.endswith(".kicad_sch")})

    def test_collects_project_and_rules_files(self):
        """Severities live in .kicad_pro and custom rules in .kicad_dru.
        Without them DRC silently uses defaults and judges a different board."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp)
            names = {os.path.basename(p) for p in staging.collect(board)}
            self.assertIn("demo.kicad_pro", names)
            self.assertIn("demo.kicad_dru", names)

    def test_tolerates_missing_optional_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp, pro=False, dru=False)
            names = {os.path.basename(p) for p in staging.collect(board)}
            self.assertEqual({"demo.kicad_pcb", "demo.kicad_sch"}, names)

    def test_excludes_everything_drc_does_not_read(self):
        """3D models and libraries are what make projects large; footprints
        are embedded in the board and symbols in the schematic."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp)
            os.mkdir(os.path.join(tmp, "lib.pretty"))
            _write(os.path.join(tmp, "lib.pretty", "a.kicad_mod"), "x")
            _write(os.path.join(tmp, "part.step"), "x" * 1000)
            _write(os.path.join(tmp, "board-F_Cu.gbr"), "x")
            _write(os.path.join(tmp, "backup.zip"), "x")
            names = {os.path.basename(p) for p in staging.collect(board)}
            for unwanted in ("a.kicad_mod", "part.step", "board-F_Cu.gbr",
                             "backup.zip"):
                self.assertNotIn(unwanted, names)

    def test_unsaved_board_refuses(self):
        """pcbnew returns an empty filename for a board never saved."""
        with self.assertRaises(staging.StagingError):
            staging.collect("")

    def test_missing_board_refuses(self):
        with self.assertRaises(staging.StagingError):
            staging.collect("/nonexistent/demo.kicad_pcb")


class LibraryTableTest(unittest.TestCase):
    """Measured regression: staging without the library tables invented two
    lib_footprint_issues findings against the real project. Cosmetic there, but
    a project that raises that check to error would block a good board."""

    def test_collects_the_library_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp, libs=True)
            names = {os.path.basename(p) for p in staging.collect(board)}
            self.assertIn("fp-lib-table", names)
            self.assertIn("sym-lib-table", names)

    def test_follows_project_local_libraries(self):
        """A copied fp-lib-table pointing at a library that was not copied is
        worse than no table at all."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp, libs=True)
            names = {os.path.basename(p) for p in staging.collect(board)}
            self.assertIn("part.kicad_mod", names)
            self.assertIn("s.kicad_sym", names)

    def test_ignores_libraries_outside_the_project(self):
        """A global library is already on the machine; copying it would be
        wrong, and a path escaping the project is not ours to follow."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp)
            _write(os.path.join(tmp, "fp-lib-table"),
                   '(fp_lib_table\n(lib (name "esc") (type "KiCad")'
                   ' (uri "${KIPRJMOD}/../escape.pretty"))\n'
                   '(lib (name "abs") (type "KiCad") (uri "/opt/kicad/x.pretty"))\n)')
            collected = staging.collect(board)
            self.assertFalse([p for p in collected if "escape" in p])
            self.assertFalse([p for p in collected if p.startswith("/opt")])

    def test_tolerates_a_project_with_no_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = _project(tmp)
            self.assertTrue(staging.collect(board))

    def test_library_layout_survives_the_copy(self):
        """The table says ${KIPRJMOD}/Local.pretty, so the copy must have a
        Local.pretty — flattening the files into the root would break it."""
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as dest:
            staging.stage(_project(tmp, libs=True), dest)
            self.assertTrue(os.path.isfile(
                os.path.join(dest, "Local.pretty", "part.kicad_mod")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "fp-lib-table")))


class StageTest(unittest.TestCase):

    def test_preserves_basenames(self):
        """kicad-cli derives the schematic from the board's basename."""
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as dest:
            staging.stage(_project(tmp), dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, "demo.kicad_pcb")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "demo.kicad_sch")))

    def test_returns_the_staged_board(self):
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as dest:
            staged = staging.stage(_project(tmp), dest)
            self.assertEqual(os.path.join(dest, "demo.kicad_pcb"), staged)
            self.assertTrue(os.path.isfile(staged))

    def test_leaves_the_originals_alone(self):
        """The whole reason staging exists."""
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as dest:
            board = _project(tmp)
            before = {n: _read(os.path.join(tmp, n)) for n in os.listdir(tmp)}
            staging.stage(board, dest)
            after = {n: _read(os.path.join(tmp, n)) for n in os.listdir(tmp)}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
