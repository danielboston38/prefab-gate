import os
import tempfile
import unittest
from unittest import mock
import gate.export
from gate.export import export_package, schematic_for
from gate.kicad import KicadUnavailable


class TestSchematicFor(unittest.TestCase):
    def test_swaps_the_extension(self):
        self.assertEqual(schematic_for("/p/board.kicad_pcb"), "/p/board.kicad_sch")


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

    def test_a_pre_existing_final_path_raises_a_comprehensible_error(self):
        out = os.path.join(self.tmp.name, "fab")
        os.makedirs(out, exist_ok=True)
        fixed_stamp = "2026-01-01-00-00-00"
        os.makedirs(os.path.join(out, fixed_stamp))
        with open(os.path.join(out, fixed_stamp, "gerbers"), "w") as fh:
            fh.write("existing package from a prior run")

        class FixedDatetime(gate.export.datetime):
            @classmethod
            def now(cls, tz=None):
                return gate.export.datetime(2026, 1, 1, 0, 0, 0)

        with mock.patch.object(gate.export, "datetime", FixedDatetime):
            with self.assertRaises(KicadUnavailable) as ctx:
                export_package("kicad-cli", self.board, out, runner=self.runner())

        self.assertIn(os.path.join(out, fixed_stamp), str(ctx.exception))
        staging_dirs = [d for d in os.listdir(out) if d.startswith(".staging-")]
        self.assertEqual(staging_dirs, [])
