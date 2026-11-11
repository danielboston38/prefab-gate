import json
import os
import tempfile
import unittest

from gate import position

# A 2x2 header in footprint coordinates, 2.54 mm pitch.
PADS = (("1", 0, 0), ("2", 2.54, 0), ("3", 0, 2.54), ("4", 2.54, 2.54))


def part(ref, x, y, rot=0, pads=PADS):
    body = "".join(
        f'\t\t(pad "{num}" thru_hole rect\n\t\t\t(at {px} {py} {rot})\n'
        f'\t\t\t(size 1.7 1.7)\n\t\t\t(layers "*.Cu")\n\t\t)\n'
        for num, px, py in pads)
    return (f'\t(footprint "Connector:Header_2x02"\n\t\t(layer "F.Cu")\n'
            f'\t\t(at {x} {y} {rot})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
            f'{body}\t)\n')


def board(*footprints):
    return "(kicad_pcb\n" + "".join(footprints) + ")\n"


# Where the pads of a header placed unrotated at (30, 40) are.
AT_30_40 = {"1": [30, 40], "2": [32.54, 40], "3": [30, 42.54], "4": [32.54, 42.54]}


def rule(pads=None, tolerance=0.1):
    r = {"pads": AT_30_40 if pads is None else pads}
    if tolerance is not None:
        r["tolerance"] = tolerance
    return r


def run_check(pcb, rules):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "demo.kicad_pcb")
        with open(path, "w", encoding="utf-8") as f:
            f.write(pcb)
        config = os.path.join(tmp, "prefab-gate.json")
        with open(config, "w", encoding="utf-8") as f:
            f.write(rules if isinstance(rules, str) else json.dumps(rules))
        return position.check(path, config)


class TestPadPosition(unittest.TestCase):
    def check(self, pcb, r=None):
        return run_check(pcb, {"pad_position": {"J1": rule() if r is None else r}})

    def assertBlocks(self, findings, kind):
        self.assertEqual([x.type for x in findings], [kind])
        self.assertTrue(findings[0].blocking)
        self.assertEqual(findings[0].items, ("J1",))
        return findings[0]

    def test_pads_where_declared_are_clean(self):
        self.assertEqual(self.check(board(part("J1", 30, 40))), [])

    def test_pads_within_tolerance_are_clean(self):
        self.assertEqual(self.check(board(part("J1", 30.07, 39.95))), [])

    def test_part_shifted_one_pitch_blocks(self):
        f = self.assertBlocks(self.check(board(part("J1", 32.54, 40))), "pad_position")
        self.assertIn("4 of 4", f.description)
        self.assertIn("2.54", f.description)

    def test_part_just_outside_tolerance_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30.15, 40))), "pad_position")

    def test_part_turned_180_about_its_centre_blocks(self):
        # Same outline, same place, pin 1 in the opposite corner.
        f = self.assertBlocks(self.check(board(part("J1", 32.54, 42.54, 180))),
                              "pad_position")
        self.assertIn("4 of 4", f.description)

    def test_mirrored_footprint_blocks(self):
        # The flip a bottom-side part can bring: columns swapped, rows kept.
        mirrored = (("1", 2.54, 0), ("2", 0, 0), ("3", 2.54, 2.54), ("4", 0, 2.54))
        self.assertBlocks(self.check(board(part("J1", 30, 40, pads=mirrored))),
                          "pad_position")

    def test_one_pad_off_names_that_pad(self):
        moved = PADS[:3] + (("4", 2.54, 3.54),)
        f = self.assertBlocks(self.check(board(part("J1", 30, 40, pads=moved))),
                              "pad_position")
        self.assertIn("1 of 4", f.description)
        self.assertIn("pad 4", f.description)

    def test_pads_not_in_the_rule_are_not_checked(self):
        # A mounting hole, say, that the rule does not care about.
        extra = PADS + (("MH", 10, 10),)
        self.assertEqual(self.check(board(part("J1", 30, 40, pads=extra))), [])

    def test_a_reference_not_on_the_board_blocks(self):
        f = run_check(board(part("J1", 30, 40)), {"pad_position": {"J9": rule()}})
        self.assertEqual([x.type for x in f], ["pad_position_config"])

    def test_a_pad_not_on_the_footprint_blocks(self):
        f = self.assertBlocks(self.check(board(part("J1", 30, 40)),
                                         rule(pads={**AT_30_40, "5": [0, 0]})),
                              "pad_position_config")
        self.assertIn("5", f.description)

    def test_a_rule_without_a_tolerance_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30, 40)), rule(tolerance=None)),
                          "pad_position_config")

    def test_a_negative_tolerance_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30, 40)), rule(tolerance=-0.1)),
                          "pad_position_config")

    def test_a_tolerance_that_is_not_a_number_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30, 40)), rule(tolerance="0.1")),
                          "pad_position_config")

    def test_a_rule_with_no_pads_blocks(self):
        # A rule that checks nothing must not read as a pass.
        self.assertBlocks(self.check(board(part("J1", 30, 40)), rule(pads={})),
                          "pad_position_config")

    def test_a_position_that_is_not_two_numbers_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30, 40)),
                                     rule(pads={"1": [30]})),
                          "pad_position_config")

    def test_a_rule_that_is_not_an_object_blocks(self):
        self.assertBlocks(self.check(board(part("J1", 30, 40)), [30, 40]),
                          "pad_position_config")

    def test_unreadable_rules_block(self):
        f = run_check(board(part("J1", 30, 40)), "{not json")
        self.assertEqual([x.type for x in f], ["pad_position_config"])

    def test_rules_without_the_section_check_nothing(self):
        self.assertEqual(run_check(board(part("J1", 30, 40)),
                                   {"pad_direction": {}}), [])

    def test_no_rules_file_checks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.kicad_pcb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(board(part("J1", 30, 40)))
            self.assertEqual(position.check(path, None), [])


if __name__ == "__main__":
    unittest.main()
