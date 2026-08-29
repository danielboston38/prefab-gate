import unittest
from gate.model import Finding, Verdict


def finding(blocking=True):
    return Finding(kind="violation", type="clearance", description="Clearance violation",
                   severity="error", items=("Track F.Cu", "Pad U1.2"),
                   blocking=blocking, reason="severity is error")


class TestVerdict(unittest.TestCase):
    def test_verdict_with_no_blocking_findings_has_passed_true(self):
        self.assertTrue(Verdict(blocking=[], cosmetic=[finding(False)]).passed)

    def test_verdict_with_a_blocking_finding_has_passed_false(self):
        self.assertFalse(Verdict(blocking=[finding()], cosmetic=[]).passed)

    def test_finding_is_hashable_so_verdicts_can_be_deduplicated(self):
        self.assertEqual(len({finding(), finding()}), 1)
