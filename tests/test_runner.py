"""The runner adapts the gate's CLI contract for the GUI."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "kicad"))

from plugin import runner  # noqa: E402

PASSING = {"passed": True, "blocking": [], "cosmetic": []}


def _write(path, text):
    with open(path, "w") as handle:
        handle.write(text)
    return path


def _read(path):
    with open(path) as handle:
        return handle.read()


def _fake_main(stdout="", stderr="", code=0, writes=None):
    """Stand in for prefab_gate.main, which the runner calls in-process."""
    def main(argv):
        if writes is not None:
            _write(argv[1], writes)
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return code
    return main


class RunCheckTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = _write(os.path.join(self.tmp.name, "demo.kicad_pcb"),
                            "(kicad_pcb)")
        _write(os.path.join(self.tmp.name, "demo.kicad_sch"), "(kicad_sch)")

    def test_parses_the_json_verdict_from_stdout(self):
        result = runner.run_check(
            self.board, main=_fake_main(stdout=json.dumps(PASSING)))
        self.assertEqual(PASSING, result.verdict)
        self.assertEqual(0, result.code)

    def test_keeps_stderr_as_messages(self):
        result = runner.run_check(
            self.board,
            main=_fake_main(stdout=json.dumps(PASSING),
                            stderr="kicad-cli missing"))
        self.assertIn("kicad-cli missing", result.messages)

    def test_survives_a_gate_that_printed_no_verdict(self):
        """Exit 3 paths print to stderr and never emit a verdict."""
        result = runner.run_check(
            self.board, main=_fake_main(stderr="boom", code=3))
        self.assertIsNone(result.verdict)
        self.assertEqual(3, result.code)
        self.assertIn("boom", result.messages)

    def test_survives_unparseable_stdout(self):
        result = runner.run_check(
            self.board, main=_fake_main(stdout="not json at all"))
        self.assertIsNone(result.verdict)

    def test_reports_stale_zone_fills_when_the_board_changed(self):
        result = runner.run_check(
            self.board,
            main=_fake_main(stdout=json.dumps(PASSING), writes="(refilled)"))
        self.assertTrue(result.zones_were_stale)

    def test_no_stale_report_when_the_board_is_untouched(self):
        result = runner.run_check(
            self.board, main=_fake_main(stdout=json.dumps(PASSING)))
        self.assertFalse(result.zones_were_stale)

    def test_runs_against_a_copy_not_the_original(self):
        """The guarantee: the user's board is never the file DRC is given."""
        original = _read(self.board)
        runner.run_check(
            self.board,
            main=_fake_main(stdout=json.dumps(PASSING), writes="(refilled)"))
        self.assertEqual(original, _read(self.board))

    def test_checks_a_path_inside_a_temporary_directory(self):
        seen = {}

        def main(argv):
            seen["board"] = argv[1]
            sys.stdout.write(json.dumps(PASSING))
            return 0

        runner.run_check(self.board, main=main)
        self.assertNotEqual(os.path.abspath(self.board),
                            os.path.abspath(seen["board"]))
        self.assertFalse(os.path.exists(seen["board"]),
                         "the staging directory must be cleaned up")

    def test_asks_the_gate_for_a_json_check(self):
        """The whole contract depends on --json putting only the verdict on
        stdout; a plain `check` would print prose there instead."""
        seen = {}

        def main(argv):
            seen["argv"] = list(argv)
            sys.stdout.write(json.dumps(PASSING))
            return 0

        runner.run_check(self.board, main=main)
        self.assertEqual("check", seen["argv"][0])
        self.assertIn("--json", seen["argv"])


if __name__ == "__main__":
    unittest.main()
