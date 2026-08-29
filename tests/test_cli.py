import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from gate.kicad import KicadUnavailable
from prefab_gate import main

CLEAN = {"violations": [], "unconnected_items": [], "schematic_parity": []}
BLOCKED = {"violations": [{"type": "courtyards_overlap", "description": "Courtyards overlap",
                           "severity": "error", "items": [{"description": "Footprint TP1"}]}],
           "unconnected_items": [], "schematic_parity": []}
# A warning-severity violation is cosmetic, not blocking, so the gate still
# passes and exports — but the manifest must still record it as something it
# knowingly waved through.
CLEAN_WITH_COSMETIC = {
    "violations": [{"type": "silk_overlap", "description": "Silkscreen overlaps courtyard",
                     "severity": "warning", "items": [{"description": "Footprint R1"}]}],
    "unconnected_items": [], "schematic_parity": []}


def deps(drc, exported=None, record=None):
    def export(cli, board, out_dir, *args, **kwargs):
        if record is not None:
            record.append((cli, board, out_dir))
        # Real export_package always returns an existing directory (atomic
        # os.replace on success) — the manifest write in prefab_gate.py is
        # unconditional on that, so the double must honor it too.
        package = os.path.abspath("2026-01-01-00-00-00")
        os.makedirs(package, exist_ok=True)
        return package
    return {"locate_cli": lambda: "kicad-cli", "probe_capability": lambda cli: None,
            "run_drc": lambda cli, board: drc, "export_package": export,
            "cli_version": lambda cli: "10.0.5", "board_hash": lambda path: "same"}


class TestCli(unittest.TestCase):
    # build_manifest hashes the real board file on disk (gate.manifest.sha256),
    # so "b.kicad_pcb" needs to actually exist wherever the test runs from.
    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")

    def test_check_on_a_clean_board_exits_zero(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out.getvalue())

    def test_check_on_a_blocked_board_exits_two(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=deps(BLOCKED))
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out.getvalue())

    def test_package_does_not_export_when_blocked(self):
        record = []
        with redirect_stdout(io.StringIO()):
            code = main(["package", "b.kicad_pcb"], deps=deps(BLOCKED, record=record))
        self.assertEqual(code, 2)
        self.assertEqual(record, [])

    def test_package_exports_when_clean(self):
        record = []
        with redirect_stdout(io.StringIO()) as out:
            code = main(["package", "b.kicad_pcb"], deps=deps(CLEAN, record=record))
        self.assertEqual(code, 0)
        self.assertEqual(len(record), 1)
        self.assertIn("2026-01-01-00-00-00", out.getvalue())

    def test_package_writes_a_real_manifest_recording_what_it_waved_through(self):
        import json
        record = []
        with redirect_stdout(io.StringIO()):
            code = main(["package", "b.kicad_pcb"],
                        deps=deps(CLEAN_WITH_COSMETIC, record=record))
        self.assertEqual(code, 0)
        self.assertEqual(len(record), 1)

        package = os.path.abspath("2026-01-01-00-00-00")
        manifest_path = os.path.join(package, "manifest.json")
        self.assertTrue(os.path.isfile(manifest_path))
        with open(manifest_path) as fh:
            manifest = json.load(fh)

        self.assertIs(manifest["verdict"]["passed"], True)
        cosmetic_types = [f["type"] for f in manifest["verdict"]["cosmetic"]]
        self.assertIn("silk_overlap", cosmetic_types)

    def test_missing_kicad_cli_exits_three(self):
        def boom():
            raise KicadUnavailable("kicad-cli not found")
        d = deps(CLEAN)
        d["locate_cli"] = boom
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("kicad-cli not found", out.getvalue())

    def test_json_flag_emits_machine_readable_output(self):
        import json
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb", "--json"], deps=deps(CLEAN))
        self.assertIs(json.loads(out.getvalue().split("\n\n")[-1])["passed"], True)

    def test_says_so_when_the_refill_modified_the_board(self):
        d = deps(CLEAN)
        hashes = iter(["before", "after"])
        d["board_hash"] = lambda path: next(hashes)
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=d)
        self.assertIn("zone fills", out.getvalue())

    def test_stays_quiet_when_the_board_was_already_filled(self):
        d = deps(CLEAN)
        d["board_hash"] = lambda path: "same"
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=d)
        self.assertNotIn("zone fills", out.getvalue())


class TestExitContract(unittest.TestCase):
    """0 clean, 2 blocked by findings, 3 the gate could not run. Nothing else.

    A traceback with exit 1, or a usage error sharing exit 2 with "this board
    is blocked", both leave CI unable to tell a broken gate from a bad board.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")

    def test_a_nonexistent_board_exits_three_not_a_traceback(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "nope.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 3)
        self.assertIn("nope.kicad_pcb", out.getvalue())

    def test_an_unknown_flag_exits_three_not_two(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main(["check", "b.kicad_pcb", "--frobnicate"], deps=deps(CLEAN))
        self.assertEqual(ctx.exception.code, 3)

    def test_no_subcommand_exits_three_not_two(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main([], deps=deps(CLEAN))
        self.assertEqual(ctx.exception.code, 3)

    def test_check_does_not_accept_an_out_it_would_ignore(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main(["check", "b.kicad_pcb", "--out", "fab"], deps=deps(CLEAN))
        self.assertEqual(ctx.exception.code, 3)

    def test_malformed_drc_json_exits_three(self):
        def bad_json(cli, board):
            raise json.JSONDecodeError("Expecting value", "{", 0)
        d = deps(CLEAN)
        d["run_drc"] = bad_json
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("JSON", out.getvalue())

    def test_an_unreadable_board_exits_three(self):
        def boom(path):
            raise OSError(13, "Permission denied")
        d = deps(CLEAN)
        d["board_hash"] = boom
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("Permission denied", out.getvalue())

    def test_a_failed_manifest_write_exits_three(self):
        def export(cli, board, out_dir, *args, **kwargs):
            package = os.path.abspath("pkg")
            # A directory where manifest.json belongs: open() raises OSError.
            os.makedirs(os.path.join(package, "manifest.json"), exist_ok=True)
            return package
        d = deps(CLEAN)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()) as out:
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("could not complete", out.getvalue())

    def test_an_export_failure_mid_run_exits_three(self):
        def export(cli, board, out_dir, *args, **kwargs):
            raise KicadUnavailable("export gerbers failed (exit 1): no plot params")
        d = deps(CLEAN)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()) as out:
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("export gerbers failed", out.getvalue())
