import json
import os
import tempfile
import unittest

from gate import orientation

# A two-pin polarised header in footprint coordinates: pad 1 at the origin,
# pad 2 2.54 mm toward +x.
HEADER_PADS = (("1", 0, 0), ("2", 2.54, 0))


def part(ref, x, y, rot=0, layer="F", pads=HEADER_PADS):
    body = "".join(
        f'\t\t(pad "{num}" thru_hole rect\n\t\t\t(at {px} {py} {rot})\n'
        f'\t\t\t(size 1.7 1.7)\n\t\t\t(layers "*.Cu")\n\t\t)\n'
        for num, px, py in pads)
    return (f'\t(footprint "Connector:Header_1x02"\n\t\t(layer "{layer}.Cu")\n'
            f'\t\t(at {x} {y} {rot})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
            f'{body}\t)\n')


def board(*footprints):
    return "(kicad_pcb\n" + "".join(footprints) + ")\n"


def rule(frm="1", to="2", toward="right"):
    return {"from": frm, "to": to, "toward": toward}


class TestPadDirection(unittest.TestCase):
    """Which way a part points, read from two of its pads."""

    def direction(self, pcb, ref="J1", frm="1", to="2"):
        return orientation.pad_direction(pcb, ref, frm, to)

    def test_unrotated_header_points_right(self):
        self.assertEqual(self.direction(board(part("J1", 30, 30))), "right")

    def test_rotated_180_points_left(self):
        # The flip this check exists for: same footprint, opposite way round.
        self.assertEqual(self.direction(board(part("J1", 30, 30, 180))), "left")

    def test_rotation_90_points_up(self):
        # KiCad rotates counter-clockwise on screen with y pointing down, so
        # +90 takes local +x to -y: toward the top.
        self.assertEqual(self.direction(board(part("J1", 30, 30, 90))), "top")

    def test_rotation_270_points_down(self):
        self.assertEqual(self.direction(board(part("J1", 30, 30, 270))), "bottom")

    def test_back_side_pads_are_read_as_stored(self):
        # KiCad stores a back-side footprint already mirrored: a flipped header
        # has pad 2 at local -x, so it points left.
        pcb = board(part("J1", 30, 30, layer="B",
                         pads=(("1", 0, 0), ("2", -2.54, 0))))
        self.assertEqual(self.direction(pcb), "left")

    def test_pads_sharing_a_number_are_averaged(self):
        # Shield tabs are often all pad "S"; their centre is what counts.
        pads = (("1", 0, 0), ("S", 5, -3), ("S", 5, 3))
        self.assertEqual(self.direction(board(part("J1", 30, 30, pads=pads)),
                                        frm="1", to="S"), "right")


class TestCheck(unittest.TestCase):
    def run_check(self, pcb, rules):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.kicad_pcb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(pcb)
            config = os.path.join(tmp, "prefab-gate.json")
            with open(config, "w", encoding="utf-8") as f:
                f.write(rules if isinstance(rules, str) else json.dumps(rules))
            return orientation.check(path, config)

    def test_part_pointing_the_declared_way_is_clean(self):
        self.assertEqual(self.run_check(board(part("J1", 30, 30)),
                                        {"pad_direction": {"J1": rule()}}), [])

    def test_part_flipped_180_blocks(self):
        f = self.run_check(board(part("J1", 30, 30, 180)),
                           {"pad_direction": {"J1": rule()}})
        self.assertEqual([x.type for x in f], ["pad_direction"])
        self.assertTrue(f[0].blocking)
        self.assertIn("left", f[0].description)
        self.assertIn("right", f[0].description)
        self.assertEqual(f[0].items, ("J1",))

    def test_footprint_with_reversed_pin_numbers_blocks(self):
        # Placed the same way, but the footprint numbers its pins the other
        # way round: the wrong footprint, caught by the same rule.
        pads = (("2", 0, 0), ("1", 2.54, 0))
        f = self.run_check(board(part("J1", 30, 30, pads=pads)),
                           {"pad_direction": {"J1": rule()}})
        self.assertEqual([x.type for x in f], ["pad_direction"])

    def test_direction_names_ignore_case(self):
        self.assertEqual(self.run_check(board(part("J1", 30, 30)),
                                        {"pad_direction": {"J1": rule(toward="Right")}}),
                         [])

    def test_a_reference_not_on_the_board_blocks(self):
        f = self.run_check(board(part("J1", 30, 30)),
                           {"pad_direction": {"J9": rule()}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])
        self.assertTrue(f[0].blocking)

    def test_a_pad_not_on_the_footprint_blocks(self):
        f = self.run_check(board(part("J1", 30, 30)),
                           {"pad_direction": {"J1": rule(to="3")}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])
        self.assertIn("3", f[0].description)

    def test_an_unknown_direction_blocks(self):
        f = self.run_check(board(part("J1", 30, 30)),
                           {"pad_direction": {"J1": rule(toward="north")}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])

    def test_a_rule_missing_a_field_blocks(self):
        f = self.run_check(board(part("J1", 30, 30)),
                           {"pad_direction": {"J1": {"from": "1", "toward": "right"}}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])

    def test_diagonal_pads_block(self):
        # Pads at 45 degrees name no single direction; picking one would be a
        # guess, and a guess can pass a flipped part.
        pads = (("1", 0, 0), ("2", 2, 2))
        f = self.run_check(board(part("J1", 30, 30, pads=pads)),
                           {"pad_direction": {"J1": rule()}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])

    def test_pads_at_the_same_place_block(self):
        pads = (("1", 0, 0), ("2", 0, 0))
        f = self.run_check(board(part("J1", 30, 30, pads=pads)),
                           {"pad_direction": {"J1": rule()}})
        self.assertEqual([x.type for x in f], ["pad_direction_config"])

    def test_unreadable_rules_block(self):
        f = self.run_check(board(part("J1", 30, 30)), "{not json")
        self.assertEqual([x.type for x in f], ["pad_direction_config"])

    def test_rules_without_the_section_check_nothing(self):
        self.assertEqual(self.run_check(board(part("J1", 30, 30)),
                                        {"connector_facing": {}}), [])

    def test_no_rules_file_checks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.kicad_pcb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(board(part("J1", 30, 30)))
            self.assertEqual(orientation.check(path, None), [])


if __name__ == "__main__":
    unittest.main()
