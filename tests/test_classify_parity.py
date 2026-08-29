import unittest
from gate.classify import classify
from gate.model import Parity


def parity(description, type_="footprint_symbol_mismatch"):
    return {"type": type_, "description": description, "severity": "warning",
            "items": [{"description": "Footprint J5"}]}


def drc(parity_entries):
    return {"violations": [], "unconnected_items": [], "schematic_parity": list(parity_entries)}


class TestClassifyParity(unittest.TestCase):
    def test_footprint_mismatch_blocks(self):
        v = classify(drc([parity(
            "PinHeader_1x03_P2.54mm_Vertical doesn't match footprint given by symbol "
            "(Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical)")]))
        self.assertEqual(len(v.blocking), 1)

    def test_dnp_mismatch_blocks(self):
        v = classify(drc([parity(
            "Footprint attributes don't match symbol: 'Do not populate' settings differ")]))
        self.assertEqual(len(v.blocking), 1)

    def test_missing_symbol_field_is_cosmetic(self):
        v = classify(drc([parity("Missing symbol field 'Manufacturer' in footprint",
                                 "footprint_symbol_field_mismatch")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)

    def test_exclude_from_bom_is_cosmetic(self):
        v = classify(drc([parity(
            "Footprint attributes don't match symbol: "
            "'Exclude from bill of materials' settings differ")]))
        self.assertEqual(len(v.cosmetic), 1)

    def test_unrecognised_description_blocks(self):
        v = classify(drc([parity("Some future KiCad wording nobody has seen")]))
        self.assertEqual(len(v.blocking), 1)

    def test_unrecognised_description_names_the_string_it_did_not_match(self):
        v = classify(drc([parity("Some future KiCad wording nobody has seen")]))
        self.assertIn("Some future KiCad wording nobody has seen", v.blocking[0].reason)

    def test_missing_footprint_blocks(self):
        v = classify(drc([parity("Missing footprint R5 (Resistor_SMD:R_0805)",
                                 "footprint_missing")]))
        self.assertEqual(len(v.blocking), 1)

    def test_net_mismatch_blocks(self):
        v = classify(drc([parity(
            "Pad net (GND) doesn't match net given by schematic (/AUDIO_OUT)")]))
        self.assertEqual(len(v.blocking), 1)

    def test_pad_missing_net_given_by_schematic_blocks(self):
        v = classify(drc([parity(
            "Pad missing net given by schematic (/AUDIO_OUT)")]))
        self.assertEqual(len(v.blocking), 1)

    def test_no_corresponding_pin_found_blocks(self):
        v = classify(drc([parity("No corresponding pin found in schematic")]))
        self.assertEqual(len(v.blocking), 1)

    def test_no_pad_found_for_pin_blocks(self):
        v = classify(drc([parity("No pad found for pin 3 in schematic")]))
        self.assertEqual(len(v.blocking), 1)

    def test_symbol_value_mismatch_is_cosmetic(self):
        v = classify(drc([parity(
            "Value (220) doesn't match symbol value (330)",
            "footprint_symbol_value_mismatch")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)

    def test_field_differs_is_cosmetic(self):
        v = classify(drc([parity(
            "Field 'MPN' differs (PCB: '', Schematic: 'TPS2553DBVR')",
            "footprint_symbol_field_mismatch")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)


class TestParityNotRun(unittest.TestCase):
    """The gate cannot tell an unchecked board from a clean one."""

    def test_parity_that_could_not_run_blocks_by_default(self):
        v = classify(drc([]), parity=Parity(ran=False, reason="no schematic found"))
        self.assertEqual(len(v.blocking), 1)
        self.assertEqual(v.blocking[0].type, "parity_not_run")
        self.assertEqual(v.blocking[0].reason, "no schematic found")
        self.assertFalse(v.passed)

    def test_an_explicit_waiver_is_cosmetic_but_still_recorded(self):
        v = classify(drc([]), parity=Parity(ran=False, waived=True,
                                            reason="skipped at your request"))
        self.assertTrue(v.passed)
        self.assertEqual([f.type for f in v.cosmetic], ["parity_not_run"])

    def test_a_waiver_does_not_survive_strict(self):
        """--strict is for a final pre-order run; nothing rides on a waiver."""
        v = classify(drc([]), strict=True,
                     parity=Parity(ran=False, waived=True, reason="skipped"))
        self.assertFalse(v.passed)
        self.assertEqual(v.blocking[0].type, "parity_not_run")

    def test_parity_that_ran_adds_no_finding_and_is_recorded(self):
        v = classify(drc([]), parity=Parity(ran=True, schematic="/p/b.kicad_sch"))
        self.assertEqual((v.blocking, v.cosmetic), ([], []))
        self.assertEqual(v.parity.schematic, "/p/b.kicad_sch")

    def test_the_default_is_that_parity_ran(self):
        self.assertTrue(classify(drc([])).parity.ran)
