"""The dialog text carries obligations the spec makes non-negotiable."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "kicad"))

from plugin import runner, summary  # noqa: E402


def _result(verdict=None, messages="", stale=False, code=0):
    return runner.Result(code=code, verdict=verdict, messages=messages,
                         zones_were_stale=stale)


PASSED = {"passed": True, "blocking": [], "cosmetic": []}


class SummaryTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = os.path.join(self.tmp.name, "demo.kicad_pcb")
        with open(self.board, "w") as handle:
            handle.write("(kicad_pcb)")

    def test_always_names_the_file_it_read(self):
        """Unsaved editor changes cannot be detected, so the plugin shows what
        it checked instead of guessing."""
        text = summary.summarise(_result(PASSED), self.board)
        self.assertIn(self.board, text)
        self.assertIn("Last saved:", text)

    def test_always_says_it_wrote_nothing(self):
        text = summary.summarise(_result(PASSED), self.board)
        self.assertIn(summary.WROTE_NOTHING, text)

    def test_stale_zones_are_reported_not_silently_repaired(self):
        text = summary.summarise(_result(PASSED, stale=True), self.board)
        self.assertIn(summary.STALE_ZONES, text)

    def test_no_stale_notice_when_fills_were_current(self):
        text = summary.summarise(_result(PASSED, stale=False), self.board)
        self.assertNotIn(summary.STALE_ZONES, text)

    def test_passing_verdict_reads_as_passed(self):
        self.assertIn("PASSED", summary.summarise(_result(PASSED), self.board))

    def test_blocking_findings_are_listed_with_their_type(self):
        verdict = {"passed": False,
                   "blocking": [{"type": "parity_not_run",
                                 "description": "parity never ran"}],
                   "cosmetic": []}
        text = summary.summarise(_result(verdict), self.board)
        self.assertIn("BLOCKED", text)
        self.assertIn("parity_not_run", text)
        self.assertIn("parity never ran", text)

    def test_cosmetic_findings_are_shown_as_waived(self):
        verdict = {"passed": True, "blocking": [],
                   "cosmetic": [{"type": "silk_overlap",
                                 "description": "Silkscreen clearance"}]}
        text = summary.summarise(_result(verdict), self.board)
        self.assertIn("waived", text)
        self.assertIn("silk_overlap", text)

    def test_a_missing_verdict_never_reads_as_a_pass(self):
        """Exit 3 means the gate could not judge. Saying nothing would let an
        unverified board look fine."""
        text = summary.summarise(_result(None, messages="kicad-cli missing"), self.board)
        self.assertNotIn("PASSED", text)
        self.assertIn("unverified", text)
        self.assertIn("kicad-cli missing", text)

    def test_unsaved_board_does_not_crash_the_summary(self):
        text = summary.summarise(_result(PASSED), "")
        self.assertIn("unsaved board", text)
        self.assertIn("unknown", text)


if __name__ == "__main__":
    unittest.main()
