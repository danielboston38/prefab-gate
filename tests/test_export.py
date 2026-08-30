import os
import tempfile
import unittest
from unittest import mock
import gate.export
from gate.export import (export_package, locate_schematic, schematic_candidates,
                         schematic_for)
from gate.kicad import KicadUnavailable


class TestSchematicFor(unittest.TestCase):
    def test_swaps_the_extension(self):
        self.assertEqual(schematic_for("/p/board.kicad_pcb"), "/p/board.kicad_sch")


class TestLocateSchematic(unittest.TestCase):
    """Roughly one real KiCad project in five has no same-named schematic.

    Refusing to start on that basis would make the gate unusable; guessing
    silently would reintroduce the fail-open. So: convention, then a sole
    candidate, then None — and None becomes a finding, never a silent skip.
    """

    def test_the_conventional_sibling_wins(self):
        found = locate_schematic("/p/board.kicad_pcb",
                                 exists=lambda x: x == "/p/board.kicad_sch",
                                 globber=lambda pattern: ["/p/other.kicad_sch"])
        self.assertEqual(found, "/p/board.kicad_sch")

    def test_a_sole_differently_named_schematic_is_used(self):
        found = locate_schematic("/p/example_pcb.kicad_pcb",
                                 exists=lambda x: False,
                                 globber=lambda p: ["/p/example_schematic.kicad_sch"])
        self.assertEqual(found, "/p/example_schematic.kicad_sch")

    def test_several_candidates_are_ambiguous_and_yield_none(self):
        found = locate_schematic("/p/board.kicad_pcb", exists=lambda x: False,
                                 globber=lambda p: ["/p/a.kicad_sch", "/p/b.kicad_sch"])
        self.assertIsNone(found)

    def test_no_candidates_at_all_yields_none(self):
        self.assertIsNone(locate_schematic("/p/board.kicad_pcb",
                                           exists=lambda x: False,
                                           globber=lambda p: []))

    def test_an_override_wins_over_everything(self):
        found = locate_schematic("/p/board.kicad_pcb", override="/elsewhere/s.kicad_sch",
                                 exists=lambda x: True,
                                 globber=lambda p: ["/p/a.kicad_sch"])
        self.assertEqual(found, "/elsewhere/s.kicad_sch")

    def test_an_override_that_does_not_exist_is_an_environment_error(self):
        with self.assertRaises(KicadUnavailable) as ctx:
            locate_schematic("/p/board.kicad_pcb", override="/nope.kicad_sch",
                             exists=lambda x: False, globber=lambda p: [])
        self.assertIn("/nope.kicad_sch", str(ctx.exception))


class TestSchematicCandidates(unittest.TestCase):
    def test_lists_every_schematic_beside_the_board(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("b.kicad_sch", "a.kicad_sch", "b.kicad_pcb"):
            open(os.path.join(tmp.name, name), "w").close()
        self.assertEqual(
            [os.path.basename(c) for c in
             schematic_candidates(os.path.join(tmp.name, "b.kicad_pcb"))],
            ["a.kicad_sch", "b.kicad_sch"])


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = os.path.join(self.tmp.name, "b.kicad_pcb")
        for path in (self.board, os.path.join(self.tmp.name, "b.kicad_sch")):
            with open(path, "w") as fh:
                fh.write("x")
        self.calls = []

    def runner(self, fail_on=None):
        def _run(cmd, **kwargs):
            self.calls.append(cmd)
            class R:
                pass
            r = R()
            r.returncode = 1 if fail_on and fail_on in " ".join(cmd) else 0
            r.stdout = r.stderr = ""
            if r.returncode == 0 and "-o" in cmd:
                target = cmd[cmd.index("-o") + 1]
                if target.endswith(".csv"):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    open(target, "w").close()
                else:
                    os.makedirs(target, exist_ok=True)
                    open(os.path.join(target, "plot.gbr"), "w").close()
            return r
        return _run

    def test_produces_a_timestamped_directory(self):
        out = os.path.join(self.tmp.name, "fab")
        package = export_package("kicad-cli", self.board, out, runner=self.runner())
        self.assertTrue(os.path.isdir(package))
        self.assertTrue(package.startswith(out))

    def test_runs_gerbers_drill_pos_and_bom(self):
        export_package("kicad-cli", self.board, os.path.join(self.tmp.name, "fab"),
                       runner=self.runner())
        joined = [" ".join(c) for c in self.calls]
        self.assertTrue(any("export gerbers" in c for c in joined))
        self.assertTrue(any("export drill" in c for c in joined))
        self.assertTrue(any("export pos" in c for c in joined))
        self.assertTrue(any("sch export bom" in c for c in joined))

    def test_a_failure_leaves_no_package_behind(self):
        out = os.path.join(self.tmp.name, "fab")
        with self.assertRaises(Exception):
            export_package("kicad-cli", self.board, out, runner=self.runner(fail_on="drill"))
        self.assertEqual([] if not os.path.isdir(out) else os.listdir(out), [])

    def _fixed_stamp(self):
        class FixedDatetime(gate.export.datetime):
            @classmethod
            def now(cls, tz=None):
                return gate.export.datetime(2026, 1, 1, 0, 0, 0)
        return mock.patch.object(gate.export, "datetime", FixedDatetime)

    def _collides_with(self, populate):
        out = os.path.join(self.tmp.name, "fab")
        fixed_stamp = "2026-01-01-00-00-00"
        os.makedirs(os.path.join(out, fixed_stamp))
        populate(os.path.join(out, fixed_stamp))
        with self._fixed_stamp():
            with self.assertRaises(KicadUnavailable) as ctx:
                export_package("kicad-cli", self.board, out, runner=self.runner())
        self.assertIn(os.path.join(out, fixed_stamp), str(ctx.exception))
        self.assertEqual([d for d in os.listdir(out) if d.startswith(".staging-")], [])
        return str(ctx.exception)

    def test_a_pre_existing_final_path_raises_a_comprehensible_error(self):
        def populate(path):
            with open(os.path.join(path, "gerbers"), "w") as fh:
                fh.write("existing package from a prior run")
        self.assertIn("directory", self._collides_with(populate))

    def test_an_empty_pre_existing_final_path_is_reported_not_silently_claimed(self):
        """os.replace renames onto an empty directory without complaint."""
        self.assertIn("empty directory", self._collides_with(lambda path: None))

    def test_on_staged_runs_after_the_exports_and_before_the_publish(self):
        out = os.path.join(self.tmp.name, "fab")
        seen = {}

        def on_staged(staging):
            seen["staging"] = staging
            seen["contents"] = sorted(os.listdir(staging))
            with open(os.path.join(staging, "manifest.json"), "w") as fh:
                fh.write("{}")

        package = export_package("kicad-cli", self.board, out,
                                 runner=self.runner(), on_staged=on_staged)
        # It saw every export, and it saw them in staging, not in the package.
        self.assertEqual(seen["contents"], ["bom.csv", "cpl.csv", "drill", "gerbers"])
        self.assertNotEqual(seen["staging"], package)
        # The manifest arrived with the package, in one atomic rename.
        self.assertTrue(os.path.isfile(os.path.join(package, "manifest.json")))

    def test_a_failing_on_staged_publishes_nothing(self):
        """No window in which a complete package exists without its receipt."""
        out = os.path.join(self.tmp.name, "fab")

        def on_staged(staging):
            raise OSError("disk full")

        with self.assertRaises(OSError):
            export_package("kicad-cli", self.board, out, runner=self.runner(),
                           on_staged=on_staged)
        self.assertEqual(os.listdir(out), [])


class TestBomUsesTheLocatedSchematic(unittest.TestCase):
    """The BOM must not assume a schematic at the board's basename.

    export_package called schematic_for(board) unconditionally, so a PCB-only
    board packaged with --no-parity ran three successful exports and then died
    on a schematic that was never there -- surfacing as exit 3, which by its
    own contract means kicad-cli is missing or too old. Unlike `pcb drc`,
    `sch export bom` does take a path, so the located schematic can be used.
    """

    def _calls(self, **kwargs):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)

            class R:
                returncode, stdout, stderr = 0, "", ""
            return R()
        with tempfile.TemporaryDirectory() as tmp:
            board = os.path.join(tmp, "b.kicad_pcb")
            open(board, "w").write("(x)")
            export_package("kicad-cli", board, os.path.join(tmp, "out"),
                           runner=runner, **kwargs)
        return calls

    def test_a_named_schematic_is_passed_to_the_bom_export(self):
        calls = self._calls(schematic="/elsewhere/design.kicad_sch")
        bom = [c for c in calls if "bom" in c]
        self.assertEqual(len(bom), 1)
        self.assertIn("/elsewhere/design.kicad_sch", bom[0])

    def test_no_schematic_means_no_bom_export_rather_than_a_failure(self):
        calls = self._calls(schematic=None)
        self.assertEqual([c for c in calls if "bom" in c], [])
        # the three board-only exports still ran
        self.assertEqual(len([c for c in calls if "export" in c]), 3)
