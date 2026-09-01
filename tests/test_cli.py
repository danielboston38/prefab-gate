import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from gate.kicad import KicadUnavailable
from gate.manifest import sha256
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
    def export(cli, board, out_dir, *args, on_staged=None, **kwargs):
        if record is not None:
            record.append((cli, board, out_dir))
        # Real export_package builds in a staging directory, calls on_staged
        # there once every export has succeeded, then publishes with a single
        # os.replace. The manifest is written by that callback, so a double
        # that skips it would quietly test a gate that writes no receipt.
        staging = os.path.abspath(".staging")
        os.makedirs(staging, exist_ok=True)
        if on_staged is not None:
            on_staged(staging)
        package = os.path.abspath("2026-01-01-00-00-00")
        os.replace(staging, package)
        return package
    # run_drc returns (drc, parity_error); parity_error is kicad-cli's stderr
    # when it could not run the parity tests despite exiting 0.
    return {"locate_cli": lambda: "kicad-cli", "probe_capability": lambda cli: None,
            "run_drc": lambda cli, board, parity=True: (drc, ""),
            "export_package": export,
            "cli_version": lambda cli: "10.0.5", "file_hash": lambda path: "same",
            "locate_schematic": lambda board, override=None: "b.kicad_sch",
            "schematic_candidates": lambda board: []}


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
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

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
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("kicad-cli not found", err.getvalue())

    def test_json_flag_emits_machine_readable_output(self):
        import json
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb", "--json"], deps=deps(CLEAN))
        self.assertIs(json.loads(out.getvalue().split("\n\n")[-1])["passed"], True)

    def test_says_so_when_the_refill_modified_the_board(self):
        d = deps(CLEAN)
        hashes = iter(["before", "after"])
        d["file_hash"] = lambda path: (next(hashes)
                                       if path.endswith(".kicad_pcb") else "sch")
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=d)
        self.assertIn("zone fills", out.getvalue())

    def test_stays_quiet_when_the_board_was_already_filled(self):
        d = deps(CLEAN)
        d["file_hash"] = lambda path: "same"
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
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def test_a_nonexistent_board_exits_three_not_a_traceback(self):
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["check", "nope.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 3)
        self.assertIn("nope.kicad_pcb", err.getvalue())

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
        def bad_json(cli, board, parity=True):
            raise json.JSONDecodeError("Expecting value", "{", 0)
        d = deps(CLEAN)
        d["run_drc"] = bad_json
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("JSON", err.getvalue())

    def test_an_unreadable_board_exits_three(self):
        def boom(path):
            raise OSError(13, "Permission denied")
        d = deps(CLEAN)
        d["file_hash"] = boom
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("Permission denied", err.getvalue())

    def test_a_failed_manifest_write_exits_three(self):
        def export(cli, board, out_dir, *args, on_staged=None, **kwargs):
            staging = os.path.abspath(".staging")
            # A directory where manifest.json belongs: open() raises OSError.
            os.makedirs(os.path.join(staging, "manifest.json"), exist_ok=True)
            on_staged(staging)
            return staging
        d = deps(CLEAN)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("could not complete", err.getvalue())

    def test_an_export_failure_mid_run_exits_three(self):
        def export(cli, board, out_dir, *args, **kwargs):
            raise KicadUnavailable("export gerbers failed (exit 1): no plot params")
        d = deps(CLEAN)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("export gerbers failed", err.getvalue())


class TestManifestIsAtomicWithThePackage(unittest.TestCase):
    """A published package without its receipt is a package nobody can audit."""

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def test_the_manifest_is_written_into_staging_before_the_package_exists(self):
        observed = {}

        def export(cli, board, out_dir, *args, on_staged=None, **kwargs):
            staging = os.path.abspath(".staging")
            os.makedirs(staging, exist_ok=True)
            on_staged(staging)
            observed["in_staging"] = os.path.isfile(
                os.path.join(staging, "manifest.json"))
            package = os.path.abspath("pkg")
            os.replace(staging, package)
            return package

        d = deps(CLEAN)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()):
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 0)
        self.assertIs(observed["in_staging"], True)

    def test_the_manifest_records_the_policy_the_run_used(self):
        with redirect_stdout(io.StringIO()):
            main(["package", "b.kicad_pcb", "--out", "pcbway_production"],
                 deps=deps(CLEAN))
        with open(os.path.join(os.path.abspath("2026-01-01-00-00-00"),
                               "manifest.json")) as fh:
            manifest = json.load(fh)
        self.assertIs(manifest["policy"]["strict"], False)
        self.assertEqual(manifest["policy"]["out_dir"], "pcbway_production")


class TestParityCannotRun(unittest.TestCase):
    """Parity that did not run is a finding, not a silent skip.

    A hard refusal would make the gate unusable — roughly one real KiCad
    project in five has no schematic under the board's own basename. A silent
    skip is the fail-open this whole fix exists to close. So: a finding.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def verdict_json(self, argv, d):
        with redirect_stdout(io.StringIO()) as out:
            code = main(argv + ["--json"], deps=d)
        return code, json.loads(out.getvalue().split("\n\n")[-1]), out.getvalue()

    def test_no_schematic_anywhere_blocks_and_says_what_it_looked_for(self):
        d = deps(CLEAN)
        d["locate_schematic"] = lambda board, override=None: None
        code, data, text = self.verdict_json(["check", "b.kicad_pcb"], d)
        self.assertEqual(code, 2)
        self.assertEqual([f["type"] for f in data["blocking"]], ["parity_not_run"])
        self.assertIn("no .kicad_sch beside the board", data["blocking"][0]["reason"])
        self.assertIn("--schematic", data["blocking"][0]["reason"])
        self.assertIs(data["parity"]["ran"], False)

    def test_several_candidates_are_named_rather_than_guessed_between(self):
        d = deps(CLEAN)
        d["locate_schematic"] = lambda board, override=None: None
        d["schematic_candidates"] = lambda board: ["a.kicad_sch", "b2.kicad_sch"]
        code, data, _ = self.verdict_json(["check", "b.kicad_pcb"], d)
        self.assertEqual(code, 2)
        reason = data["blocking"][0]["reason"]
        self.assertIn("a.kicad_sch", reason)
        self.assertIn("b2.kicad_sch", reason)

    def test_the_schematic_flag_is_passed_through_to_the_locator(self):
        # The flag still reaches the locator — it chooses the BOM source. What
        # it cannot do is make parity run: `kicad-cli pcb drc` derives the
        # schematic from the board's basename, verified against KiCad 10.0.6,
        # so this test used to assert a pass the tool never actually delivered.
        os.remove("b.kicad_sch")
        seen = {}

        def locate(board, override=None):
            seen["override"] = override
            return override
        d = deps(CLEAN)
        d["locate_schematic"] = locate
        code, data, _ = self.verdict_json(
            ["check", "b.kicad_pcb", "--schematic", "elsewhere/s.kicad_sch"], d)
        self.assertEqual(seen["override"], "elsewhere/s.kicad_sch")
        self.assertEqual(code, 2)
        self.assertIs(data["parity"]["ran"], False)
        self.assertNotEqual(data["parity"]["schematic"], "elsewhere/s.kicad_sch")

    def test_no_parity_downgrades_to_cosmetic_but_still_records_it(self):
        code, data, text = self.verdict_json(["check", "b.kicad_pcb", "--no-parity"], deps(CLEAN))
        self.assertEqual(code, 0)
        self.assertEqual([f["type"] for f in data["cosmetic"]], ["parity_not_run"])
        self.assertIs(data["parity"]["ran"], False)
        self.assertIs(data["parity"]["waived"], True)
        self.assertIn("Schematic parity did not run", text)

    def test_no_parity_stops_the_parity_flag_reaching_kicad_cli(self):
        seen = {}

        def run_drc(cli, board, parity=True):
            seen["parity"] = parity
            return CLEAN, ""
        d = deps(CLEAN)
        d["run_drc"] = run_drc
        with redirect_stdout(io.StringIO()):
            main(["check", "b.kicad_pcb", "--no-parity"], deps=d)
        self.assertIs(seen["parity"], False)

    def test_a_stderr_marker_blocks_even_though_a_schematic_was_located(self):
        """DRC results stay valid; it is the parity half that did not run."""
        d = deps(CLEAN)
        d["run_drc"] = lambda cli, board, parity=True: (
            CLEAN, "Failed to fetch schematic netlist for parity tests.")
        code, data, _ = self.verdict_json(["check", "b.kicad_pcb"], d)
        self.assertEqual(code, 2)
        self.assertEqual([f["type"] for f in data["blocking"]], ["parity_not_run"])
        self.assertIn("Failed to fetch schematic netlist",
                      data["blocking"][0]["reason"])
        self.assertIs(data["parity"]["ran"], False)

    def test_a_bad_schematic_override_is_an_environment_error(self):
        # No conventional sibling: with one present the override guard refuses
        # first, which is a different environment error than the one under test.
        os.remove("b.kicad_sch")

        def locate(board, override=None):
            raise KicadUnavailable("--schematic points at '/nope', which does not exist")
        d = deps(CLEAN)
        d["locate_schematic"] = locate
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(["check", "b.kicad_pcb", "--schematic", "/nope"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("does not exist", err.getvalue())

    def test_a_clean_run_records_the_schematic_parity_actually_used(self):
        code, data, _ = self.verdict_json(["check", "b.kicad_pcb"], deps(CLEAN))
        self.assertEqual(code, 0)
        self.assertIs(data["parity"]["ran"], True)
        self.assertEqual(data["parity"]["schematic"], "b.kicad_sch")

    def test_the_manifest_records_that_parity_ran_and_against_what(self):
        with redirect_stdout(io.StringIO()):
            main(["package", "b.kicad_pcb"], deps=deps(CLEAN))
        with open(os.path.join(os.path.abspath("2026-01-01-00-00-00"),
                               "manifest.json")) as fh:
            manifest = json.load(fh)
        self.assertIs(manifest["verdict"]["parity"]["ran"], True)
        self.assertEqual(manifest["verdict"]["parity"]["schematic"], "b.kicad_sch")


class TestJsonIsMachineReadable(unittest.TestCase):
    """--json must put a parseable document on stdout and nothing else."""

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def test_json_stdout_parses_with_no_stripping(self):
        # The text report used to be printed ahead of the JSON, so a consumer
        # piping --json had to hunt for the document inside the prose.
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            code = main(["check", "--json", "b.kicad_pcb"], deps=deps(BLOCKED))
        self.assertEqual(code, 2)
        verdict = json.loads(out.getvalue())
        self.assertFalse(verdict["passed"])

    def test_zone_refill_note_does_not_pollute_json_stdout(self):
        d = deps(CLEAN)
        hashes = iter(["before", "after"])
        d["file_hash"] = lambda path: (next(hashes)
                                       if path.endswith(".kicad_pcb") else "sch")
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["check", "--json", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 0)
        json.loads(out.getvalue())
        self.assertIn("refilling updated the zone fills", err.getvalue())

    def test_package_path_does_not_pollute_json_stdout(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["package", "--json", "b.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 0)
        json.loads(out.getvalue())
        self.assertIn("Package written to", err.getvalue())

    def test_without_json_the_text_report_still_goes_to_stdout(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out.getvalue())


class TestUnreadableBoardBlocks(unittest.TestCase):
    """A board kicad-cli cannot load must block (exit 2), never claim exit 3.

    Exit 3's contract is "kicad-cli missing or too old". Returning it for a
    corrupt or unloadable board told the user to go fix their KiCad install.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def _deps_raising(self):
        from gate.kicad import BoardUnreadable
        d = deps(CLEAN)

        def boom(cli, board, parity=True):
            raise BoardUnreadable(
                "kicad-cli DRC failed (exit 3): Failed to load board: "
                "Unexpected 'end of input'")
        d["run_drc"] = boom
        return d

    def test_exits_two_not_three(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["check", "b.kicad_pcb"], deps=self._deps_raising())
        self.assertEqual(code, 2)

    def test_reports_it_as_a_blocking_finding(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            main(["check", "--json", "b.kicad_pcb"], deps=self._deps_raising())
        verdict = json.loads(out.getvalue())
        self.assertFalse(verdict["passed"])
        self.assertEqual([f["type"] for f in verdict["blocking"]], ["board_unreadable"])

    def test_package_writes_nothing(self):
        record = []
        d = self._deps_raising()
        d["export_package"] = lambda *a, **k: record.append(a) or "pkg"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["package", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 2)
        self.assertEqual(record, [])

    def test_a_genuinely_missing_kicad_cli_still_exits_three(self):
        d = deps(CLEAN)

        def missing():
            raise KicadUnavailable("kicad-cli not found")
        d["locate_cli"] = missing
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)


class TestErrorsGoToStderr(unittest.TestCase):
    """Errors belong on stderr, so --json stdout stays a parseable document.

    _emit prints the verdict before the package step runs, so an export or
    manifest failure lands in main()'s handlers *after* the JSON is already on
    stdout. Printing there appended prose to the document and broke the
    consumer. GateArgumentParser.error already wrote usage errors to stderr;
    runtime errors now agree with it rather than splitting across streams.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def _exploding(self, exc):
        d = deps(CLEAN)

        def export(cli, board, out_dir, *args, **kwargs):
            raise exc
        d["export_package"] = export
        return d

    def test_json_survives_an_export_failure_after_the_verdict_is_emitted(self):
        d = self._exploding(KicadUnavailable("cannot publish the package"))
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["package", "--json", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        json.loads(out.getvalue())
        self.assertIn("cannot publish", err.getvalue())

    def test_json_survives_a_manifest_oserror_after_the_verdict_is_emitted(self):
        d = self._exploding(OSError("No space left on device"))
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["package", "--json", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        json.loads(out.getvalue())
        self.assertIn("No space left", err.getvalue())

    def test_board_not_found_goes_to_stderr(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["check", "nope.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 3)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("board not found", err.getvalue())


class TestOverrideThatKicadCliWillIgnore(unittest.TestCase):
    """--schematic cannot be honoured when a conventional sibling exists.

    `kicad-cli pcb drc` derives the schematic from the board's basename and
    takes no override, so with a sibling present it checks the sibling. The
    gate used to record the override on the verdict and in the manifest,
    claiming a file had been verified that kicad-cli never opened -- the
    receipt lying about the one fact it exists to record.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        for name in ("b.kicad_pcb", "b.kicad_sch", "elsewhere.kicad_sch"):
            with open(name, "w") as fh:
                fh.write("(x)")

    def _deps(self):
        d = deps(CLEAN)
        d["locate_schematic"] = lambda board, override=None: override or "b.kicad_sch"
        return d

    def test_refuses_when_a_sibling_exists_and_the_override_differs(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = main(["check", "--schematic", "elsewhere.kicad_sch",
                         "b.kicad_pcb"], deps=self._deps())
        self.assertEqual(code, 3)
        self.assertIn("elsewhere.kicad_sch", err.getvalue())
        self.assertIn("b.kicad_sch", err.getvalue())

    def test_an_override_equal_to_the_sibling_is_fine(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["check", "--schematic", "b.kicad_sch",
                         "b.kicad_pcb"], deps=self._deps())
        self.assertEqual(code, 0)

    def test_an_override_with_no_sibling_is_accepted_but_cannot_run_parity(self):
        # Not refused — the override is a legitimate BOM source. But it is not
        # a file kicad-cli will read for parity, so the honest answer is "parity
        # did not run", not a pass naming a schematic nothing checked.
        os.remove("b.kicad_sch")
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            code = main(["check", "--json", "--schematic", "elsewhere.kicad_sch",
                         "b.kicad_pcb"], deps=self._deps())
        self.assertEqual(code, 2)
        parity = json.loads(out.getvalue())["parity"]
        self.assertIs(parity["ran"], False)
        self.assertIn("b.kicad_sch", parity["reason"])


class TestPackagingAPcbOnlyBoard(unittest.TestCase):
    """--no-parity is advertised as accepting a PCB-only check; packaging must
    honour that rather than dying on a schematic that was never there."""

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def test_package_no_parity_passes_none_as_the_schematic(self):
        seen = {}
        d = deps(CLEAN)
        d["locate_schematic"] = lambda board, override=None: None
        real = d["export_package"]

        def export(cli, board, out_dir, *a, on_staged=None, schematic="unset", **k):
            seen["schematic"] = schematic
            return real(cli, board, out_dir, on_staged=on_staged)
        d["export_package"] = export
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["package", "--no-parity", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 0)
        self.assertIsNone(seen["schematic"])


class TestSoleSchematicUnderAnotherName(unittest.TestCase):
    """A schematic KiCad will not read is not a schematic parity can use.

    locate_schematic falls back to a sole .kicad_sch beside the board even
    when it is not named after the board, because roughly one project in five
    has no conventional sibling and the BOM export can use any path. But
    `kicad-cli pcb drc` derives the schematic from the board's basename and
    offers no way to point it elsewhere, so parity against that file cannot
    happen. Claiming ran=True made the manifest name a file that was never
    checked — a receipt asserting something untrue, which is worse than no
    receipt. Reproduced against KiCad 10.0.6: it prints a failure to stderr,
    exits 0 and writes "schematic_parity": [].
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")
        with open("my_actual_design.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def _deps(self):
        d = deps(CLEAN)
        d["locate_schematic"] = (
            lambda board, override=None: "my_actual_design.kicad_sch")
        return d

    def test_parity_is_blocking_rather_than_silently_clean(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=self._deps())
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out.getvalue())

    def test_the_reason_names_the_rename_that_would_fix_it(self):
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=self._deps())
        self.assertIn("b.kicad_sch", out.getvalue())

    def test_the_receipt_does_not_name_it_as_verified(self):
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb", "--json"], deps=self._deps())
        parity = json.loads(out.getvalue())["parity"]
        self.assertFalse(parity["ran"])
        self.assertNotEqual(parity["schematic"], "my_actual_design.kicad_sch")


class TestATruncatedReportIsNotACleanBoard(unittest.TestCase):
    """An incomplete report is a gate failure, never a pass.

    The distinction the exit contract turns on: 2 means the gate checked this
    board and rejected it, 3 means the gate could not check it. A report with
    sections missing is the second, and used to be reported as neither — it
    came out as 0.
    """

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        with open("b.kicad_pcb", "w") as fh:
            fh.write("(kicad_pcb)")
        # The default locate_schematic double reports a schematic beside the
        # board; the manifest hashes it for real, so it has to be there. A
        # fixture that named a file it never created was describing a project
        # that could not exist.
        with open("b.kicad_sch", "w") as fh:
            fh.write("(kicad_sch)")

    def _run(self, report, argv=("check", "b.kicad_pcb")):
        with redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = main(list(argv), deps=deps(report))
        return code, out.getvalue(), err.getvalue()

    def test_a_report_missing_violations_exits_three(self):
        code, out, err = self._run({"unconnected_items": [],
                                    "schematic_parity": []})
        self.assertEqual(code, 3)
        self.assertNotIn("PASSED", out)
        self.assertIn("violations", err)

    def test_an_empty_report_exits_three(self):
        code, out, _ = self._run({})
        self.assertEqual(code, 3)
        self.assertNotIn("PASSED", out)

    def test_a_report_missing_parity_exits_three(self):
        code, _, _ = self._run({"violations": [], "unconnected_items": []})
        self.assertEqual(code, 3)

    def test_no_package_is_published_from_a_truncated_report(self):
        record = []
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["package", "b.kicad_pcb"],
                        deps=deps({}, record=record))
        self.assertEqual(code, 3)
        self.assertEqual(record, [])

    def test_no_parity_does_not_demand_a_parity_section(self):
        # --no-parity omits --schematic-parity, so a report without that
        # section is exactly what was asked for.
        code, out, _ = self._run({"violations": [], "unconnected_items": []},
                                 argv=("check", "b.kicad_pcb", "--no-parity"))
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out)


class TestArtifactsCannotChangeAfterVerification(unittest.TestCase):
    """The board fabricated must be the board verified.

    The before/after hashes around the DRC only ever documented that KiCad's
    own refill rewrote the board. Nothing tied the file the gerbers were
    exported from to the file the DRC passed, so an edit landing in that
    window produced a package that looked reproducible — the manifest hash was
    accurate — while describing a board no check had ever seen. Same hole on
    the schematic side, which the gate located a second time at export rather
    than reusing the one parity ran against.
    """

    PACKAGE = "2026-01-01-00-00-00"

    def setUp(self):
        self._prev_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._prev_cwd)
        for name, body in (("b.kicad_pcb", "(kicad_pcb)"),
                           ("b.kicad_sch", "(kicad_sch)")):
            with open(name, "w") as fh:
                fh.write(body)
        self.exported = []

    def _deps(self, mutate=None, locator=None):
        d = deps(CLEAN)
        # Real content hashing: a double returning a constant cannot show a
        # file changing, which is the whole subject here.
        d["file_hash"] = sha256
        if locator is not None:
            d["locate_schematic"] = locator

        def export(cli, board, out_dir, *a, on_staged=None, schematic=None, **k):
            self.exported.append(schematic)
            if mutate is not None:
                mutate()
            staging = os.path.abspath(".staging")
            os.makedirs(staging, exist_ok=True)
            try:
                if on_staged is not None:
                    on_staged(staging)
                package = os.path.abspath(self.PACKAGE)
                os.replace(staging, package)
                return package
            except BaseException:
                # Exactly what the real export_package does, so a rejection
                # here leaves nothing that looks shippable.
                shutil.rmtree(staging, ignore_errors=True)
                raise
        d["export_package"] = export
        return d

    def _package(self, **kwargs):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = main(["package", "b.kicad_pcb"], deps=self._deps(**kwargs))
        return code, err.getvalue()

    def _touch(self, name):
        def mutate():
            with open(name, "a") as fh:
                fh.write(" ")
        return mutate

    def test_a_board_edited_during_export_is_not_published(self):
        code, err = self._package(mutate=self._touch("b.kicad_pcb"))
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.PACKAGE))
        self.assertIn("b.kicad_pcb", err)

    def test_a_schematic_edited_during_export_is_not_published(self):
        code, err = self._package(mutate=self._touch("b.kicad_sch"))
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.PACKAGE))
        self.assertIn("b.kicad_sch", err)

    def test_a_rejected_package_leaves_no_staging_behind(self):
        self._package(mutate=self._touch("b.kicad_pcb"))
        self.assertEqual([p for p in os.listdir(".") if p.startswith(".staging")], [])

    def test_an_unchanged_run_publishes_matching_hashes(self):
        code, _ = self._package()
        self.assertEqual(code, 0)
        with open(os.path.join(self.PACKAGE, "manifest.json")) as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["board"]["sha256"],
                         manifest["board"]["checked_sha256"])
        self.assertEqual(manifest["schematic"]["sha256"],
                         manifest["schematic"]["checked_sha256"])
        self.assertEqual(manifest["schematic"]["path"], "b.kicad_sch")

    def test_the_bom_comes_from_the_schematic_parity_verified(self):
        # The locator returning something different the second time is the
        # F-03 scenario: parity checked one file, the BOM would have been
        # built from another. The export must see the verified one.
        paths = iter(["b.kicad_sch", "someone_elses.kicad_sch"])
        code, _ = self._package(locator=lambda board, override=None: next(paths))
        self.assertEqual(code, 0)
        self.assertEqual(self.exported, ["b.kicad_sch"])
