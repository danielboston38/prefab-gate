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

    def test_exclusions_are_counted_not_merely_dropped(self):
        """"Nothing was wrong" and "you told me not to look" are different."""
        v = classify(drc(violations=[violation("exclusion"), violation("exclusion")]))
        self.assertEqual(v.excluded, 2)

    def test_checks_disabled_in_the_project_file_reach_the_verdict(self):
        d = drc()
        d["ignored_checks"] = [{"key": "missing_courtyard",
                                "description": "Footprint has no courtyard defined"}]
        v = classify(d)
        self.assertEqual([c["key"] for c in v.ignored_checks], ["missing_courtyard"])
        self.assertTrue(v.passed)

    def test_a_degenerate_drc_dict_yields_an_empty_verdict(self):
        v = classify({})
        self.assertEqual((v.blocking, v.cosmetic, v.excluded, v.ignored_checks),
                         ([], [], 0, []))

    def test_unconnected_items_always_block(self):
        v = classify(drc(unconnected=[{"description": "Net /5V", "items": []}]))
        self.assertEqual(len(v.blocking), 1)

    def test_strict_mode_promotes_cosmetic_to_blocking(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]), strict=True)
        self.assertEqual(len(v.blocking), 1)
        self.assertEqual(len(v.cosmetic), 0)

    def test_a_strict_promotion_is_marked_blocking_and_says_why(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]), strict=True)
        promoted = v.blocking[0]
        self.assertTrue(promoted.blocking)
        self.assertIn("DRC severity is warning", promoted.reason)
        self.assertIn("promoted by --strict", promoted.reason)
        # The original class survives in the record: it was a warning.
        self.assertEqual(promoted.severity, "warning")

    def test_a_strict_promotion_leaves_the_unpromoted_finding_alone(self):
        """Findings are frozen; promotion must copy, never mutate in place."""
        plain = classify(drc(violations=[violation("warning", "silk_overlap")]))
        strict = classify(drc(violations=[violation("warning", "silk_overlap")]),
                          strict=True)
        self.assertFalse(plain.cosmetic[0].blocking)
        self.assertNotIn("promoted", plain.cosmetic[0].reason)
        self.assertTrue(strict.blocking[0].blocking)


class TestUnknownSeverity(unittest.TestCase):
    """The parity path fails closed on an unfamiliar message; so does this one."""

    def test_a_missing_severity_blocks(self):
        v = classify(drc(violations=[{"type": "clearance", "description": "d"}]))
        self.assertEqual(len(v.blocking), 1)
        self.assertFalse(v.passed)

    def test_an_unrecognised_severity_blocks_and_names_itself(self):
        v = classify(drc(violations=[violation("catastrophe")]))
        self.assertEqual(len(v.blocking), 1)
        self.assertIn("catastrophe", v.blocking[0].reason)

    def test_finding_records_affected_items(self):
        v = classify(drc(violations=[violation("error")]))
        self.assertEqual(v.blocking[0].items, ("Pad U1.2",))
