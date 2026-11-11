import json
import os
import tempfile
import unittest

from gate import facing

# A 60 x 60 mm board, outline from (0, 0) to (60, 60). KiCad's y axis points
# down, so "top" is y = 0.
OUTLINE = "".join(
    f'\t(gr_line\n\t\t(start {a} {b})\n\t\t(end {c} {d})\n'
    f'\t\t(layer "Edge.Cuts")\n\t)\n'
    for a, b, c, d in ((0, 0, 60, 0), (60, 0, 60, 60),
                       (60, 60, 0, 60), (0, 60, 0, 0)))

# The courtyard of a right-angle RCA jack, in footprint coordinates: the barrel
# runs out toward -x, well past the pads. Taken from the PJRAN1X1U03X footprint
# whose jacks were found facing the wrong way on a built board.
JACK_COURTYARD = ((-14.5, -6.768), (7, -6.768), (7, 7.9), (-14.5, 7.9))


def jack(ref, x, y, rot=0, layer="F", courtyard=JACK_COURTYARD):
    lines = "".join(
        f'\t\t(fp_line\n\t\t\t(start {a[0]} {a[1]})\n\t\t\t(end {b[0]} {b[1]})\n'
        f'\t\t\t(layer "{layer}.CrtYd")\n\t\t)\n'
        for a, b in zip(courtyard, courtyard[1:] + courtyard[:1]))
    return (f'\t(footprint "nes1:PJRAN1X1U03X"\n\t\t(layer "{layer}.Cu")\n'
            f'\t\t(at {x} {y} {rot})\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
            f'{lines}\t)\n')


def board(*footprints):
    return "(kicad_pcb\n" + "".join(footprints) + OUTLINE + ")\n"


class TestFacingEdge(unittest.TestCase):
    """Which board edge a footprint's courtyard runs out past."""

    def test_unrotated_jack_at_the_left_edge_faces_left(self):
        self.assertEqual(facing.facing_edge(board(jack("J1", 5, 30)), "J1"), "left")

    def test_rotated_180_at_the_right_edge_faces_right(self):
        # The linktovideo v2 placement: rotated 180, barrel out the right edge.
        self.assertEqual(
            facing.facing_edge(board(jack("J1", 55, 30, 180)), "J1"), "right")

    def test_rotation_90_turns_the_barrel_toward_the_bottom(self):
        # KiCad rotates counter-clockwise on screen with y pointing down, so
        # +90 takes local -x to +y: the bottom edge.
        self.assertEqual(
            facing.facing_edge(board(jack("J1", 30, 55, 90)), "J1"), "bottom")

    def test_rotation_270_turns_the_barrel_toward_the_top(self):
        self.assertEqual(
            facing.facing_edge(board(jack("J1", 30, 5, 270)), "J1"), "top")

    def test_a_flush_connector_still_counts(self):
        # Courtyard ends 0.5 mm inside the edge: a front-panel-flush jack.
        self.assertEqual(
            facing.facing_edge(board(jack("J1", 15, 30)), "J1"), "left")

    def test_a_connector_in_the_middle_faces_no_edge(self):
        self.assertIsNone(facing.facing_edge(board(jack("J1", 30, 30)), "J1"))

    def test_back_side_courtyard_is_used(self):
        self.assertEqual(
            facing.facing_edge(board(jack("J1", 5, 30, layer="B")), "J1"), "left")


class TestCheck(unittest.TestCase):
    def run_check(self, pcb, rules):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.kicad_pcb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(pcb)
            config = os.path.join(tmp, "prefab-gate.json")
            with open(config, "w", encoding="utf-8") as f:
                f.write(rules if isinstance(rules, str) else json.dumps(rules))
            return facing.check(path, config)

    def test_connector_on_the_declared_edge_is_clean(self):
        pcb = board(jack("J2", 55, 30, 180))
        self.assertEqual(self.run_check(pcb, {"connector_facing": {"J2": "right"}}), [])

    def test_connector_facing_the_wrong_edge_blocks(self):
        pcb = board(jack("J2", 55, 30, 180))
        f = self.run_check(pcb, {"connector_facing": {"J2": "left"}})
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].type, "connector_facing")
        self.assertTrue(f[0].blocking)
        self.assertIn("right", f[0].description)
        self.assertIn("left", f[0].description)
        self.assertEqual(f[0].items, ("J2",))

    def test_connector_that_reaches_no_edge_blocks(self):
        f = self.run_check(board(jack("J2", 30, 30)),
                           {"connector_facing": {"J2": "left"}})
        self.assertEqual([x.type for x in f], ["connector_facing"])
        self.assertTrue(f[0].blocking)

    def test_a_reference_not_on_the_board_blocks(self):
        # A typo in the rules must not turn the check off without a word.
        f = self.run_check(board(jack("J2", 5, 30)),
                           {"connector_facing": {"J9": "left"}})
        self.assertEqual([x.type for x in f], ["connector_facing_config"])
        self.assertTrue(f[0].blocking)

    def test_a_footprint_with_no_courtyard_blocks(self):
        f = self.run_check(board(jack("J2", 5, 30, courtyard=())),
                           {"connector_facing": {"J2": "left"}})
        self.assertEqual([x.type for x in f], ["connector_facing_config"])

    def test_an_unknown_edge_name_blocks(self):
        f = self.run_check(board(jack("J2", 5, 30)),
                           {"connector_facing": {"J2": "outside"}})
        self.assertEqual([x.type for x in f], ["connector_facing_config"])

    def test_edge_names_ignore_case(self):
        self.assertEqual(self.run_check(board(jack("J2", 5, 30)),
                                        {"connector_facing": {"J2": "Left"}}), [])

    def test_unreadable_rules_block(self):
        f = self.run_check(board(jack("J2", 5, 30)), "{not json")
        self.assertEqual([x.type for x in f], ["connector_facing_config"])
        self.assertTrue(f[0].blocking)

    def test_rules_without_the_section_check_nothing(self):
        self.assertEqual(self.run_check(board(jack("J2", 5, 30)), {}), [])

    def test_no_rules_file_checks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.kicad_pcb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(board(jack("J2", 5, 30)))
            self.assertEqual(facing.check(path, None), [])

    def test_board_without_an_outline_blocks(self):
        pcb = "(kicad_pcb\n" + jack("J2", 5, 30) + ")\n"
        f = self.run_check(pcb, {"connector_facing": {"J2": "left"}})
        self.assertEqual([x.type for x in f], ["connector_facing_config"])


if __name__ == "__main__":
    unittest.main()
