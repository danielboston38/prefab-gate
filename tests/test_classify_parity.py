import unittest
from gate.classify import classify


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

    def test_extra_footprint_not_in_schematic_blocks(self):
        v = classify(drc([parity("Footprint J2 not in schematic",
                                 "footprint_missing")]))
        self.assertEqual(len(v.blocking), 1)

    def test_net_mismatch_blocks(self):
        v = classify(drc([parity(
            "Pad net (GND) doesn't match net given by schematic (/AUDIO_OUT)")]))
        self.assertEqual(len(v.blocking), 1)
