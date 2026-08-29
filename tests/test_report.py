import json
import unittest
from gate.model import Finding, Verdict
from gate.report import render_text, render_json


def f(blocking, description="Courtyards overlap", items=("Footprint TP1", "Footprint J3")):
    return Finding(kind="violation", type="courtyards_overlap", description=description,
                   severity="error" if blocking else "warning", items=items,
                   blocking=blocking, reason="DRC severity is error")


class TestRenderText(unittest.TestCase):
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
