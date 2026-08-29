import unittest
from gate.classify import classify


def drc(violations=(), unconnected=(), parity=()):
    return {"violations": list(violations), "unconnected_items": list(unconnected),
            "schematic_parity": list(parity)}


def violation(severity, type_="clearance"):
    return {"type": type_, "description": f"{type_} problem", "severity": severity,
            "items": [{"description": "Pad U1.2"}]}


class TestClassifyViolations(unittest.TestCase):
    def test_error_severity_blocks(self):
        v = classify(drc(violations=[violation("error")]))
        self.assertEqual(len(v.blocking), 1)
        self.assertFalse(v.passed)

    def test_warning_severity_is_cosmetic(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)

    def test_exclusion_severity_is_neither_blocking_nor_cosmetic(self):
        v = classify(drc(violations=[violation("exclusion")]))
        self.assertEqual((len(v.blocking), len(v.cosmetic)), (0, 0))

    def test_unconnected_items_always_block(self):
        v = classify(drc(unconnected=[{"description": "Net /5V", "items": []}]))
        self.assertEqual(len(v.blocking), 1)

    def test_strict_mode_promotes_cosmetic_to_blocking(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]), strict=True)
        self.assertEqual(len(v.blocking), 1)
        self.assertEqual(len(v.cosmetic), 0)

    def test_finding_records_affected_items(self):
        v = classify(drc(violations=[violation("error")]))
        self.assertEqual(v.blocking[0].items, ("Pad U1.2",))
