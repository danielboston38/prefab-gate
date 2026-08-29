import json
import unittest
from gate.model import Finding, Parity, Verdict
from gate.report import render_text, render_json


def f(blocking, description="Courtyards overlap", items=("Footprint TP1", "Footprint J3")):
    return Finding(kind="violation", type="courtyards_overlap", description=description,
                   severity="error" if blocking else "warning", items=items,
                   blocking=blocking, reason="DRC severity is error")


class TestRenderText(unittest.TestCase):
    def test_blocked_report_does_not_claim_no_files_were_written(self):
        """A refill may have rewritten the board a line earlier."""
        text = render_text(Verdict(blocking=[f(True)], cosmetic=[]))
        self.assertIn("No package was produced.", text)
        self.assertNotIn("No files were produced", text)

    def test_blocked_report_names_the_blocking_finding_and_its_items(self):
        text = render_text(Verdict(blocking=[f(True)], cosmetic=[]))
        self.assertIn("BLOCKED", text)
        self.assertIn("Courtyards overlap", text)
        self.assertIn("Footprint TP1", text)

    def test_clean_report_says_so_and_counts_what_it_waved_through(self):
        text = render_text(Verdict(blocking=[], cosmetic=[f(False), f(False)]))
        self.assertIn("PASSED", text)
        self.assertIn("2", text)

    def test_cosmetic_findings_are_listed_not_just_counted(self):
        text = render_text(Verdict(blocking=[], cosmetic=[f(False, "Silkscreen clipped")]))
        self.assertIn("Silkscreen clipped", text)


class TestRenderJson(unittest.TestCase):
    def test_json_is_machine_readable_and_carries_both_classes(self):
        data = json.loads(render_json(Verdict(blocking=[f(True)], cosmetic=[f(False)])))
        self.assertIs(data["passed"], False)
        self.assertEqual(len(data["blocking"]), 1)
        self.assertEqual(len(data["cosmetic"]), 1)
        self.assertEqual(data["blocking"][0]["type"], "courtyards_overlap")


class TestSwitchedOff(unittest.TestCase):
    """PASSED means little without what the gate was told not to look at."""

    def test_text_reports_excluded_findings_and_disabled_checks(self):
        text = render_text(Verdict(cosmetic=[f(False)], excluded=3, ignored_checks=[
            {"key": "missing_courtyard", "description": "no courtyard"},
            {"key": "track_not_centered_on_via", "description": "off centre"}]))
        self.assertIn("3 excluded", text)
        self.assertIn("2 check categories disabled in project settings", text)
        self.assertIn("missing_courtyard", text)

    def test_text_stays_quiet_when_nothing_was_switched_off(self):
        self.assertNotIn("Not checked", render_text(Verdict(cosmetic=[f(False)])))

    def test_json_carries_them_too(self):
        data = json.loads(render_json(Verdict(excluded=1, ignored_checks=[
            {"key": "missing_courtyard", "description": "no courtyard"}])))
        self.assertEqual(data["excluded"], 1)
        self.assertEqual(data["ignored_checks"][0]["key"], "missing_courtyard")


class TestParityInJson(unittest.TestCase):
    def test_json_says_whether_parity_ran_and_against_what(self):
        data = json.loads(render_json(
            Verdict(parity=Parity(ran=True, schematic="/p/b.kicad_sch"))))
        self.assertIs(data["parity"]["ran"], True)
        self.assertEqual(data["parity"]["schematic"], "/p/b.kicad_sch")

    def test_json_carries_the_reason_parity_did_not_run(self):
        data = json.loads(render_json(
            Verdict(parity=Parity(ran=False, reason="no schematic found"))))
        self.assertIs(data["parity"]["ran"], False)
        self.assertEqual(data["parity"]["reason"], "no schematic found")
