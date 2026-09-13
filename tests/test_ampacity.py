import unittest

from gate import ampacity


def board(segments=(), footprints=""):
    """Minimal .kicad_pcb text. Segments are laid end-to-end along x so that
    same-width neighbours form one contiguous run, as on a real board."""
    segs, x = "", 0.0
    for n, w, *rest in segments:
        ln = rest[0] if rest else 1.0
        segs += (f'\t(segment\n\t\t(start {x} 0)\n\t\t(end {x + ln} 0)\n'
                 f'\t\t(width {w})\n\t\t(layer "F.Cu")\n\t\t(net "{n}")\n\t)\n')
        x += ln
    return segs + footprints


def fuse(ref="F1", spec="PPTC, IH 2.0 A / IT 3.8 A", nets=("/raw_5v",)):
    pads = "".join(f'\t\t(pad "{i}" thru_hole circle\n\t\t\t(net "{n}")\n\t\t)\n'
                   for i, n in enumerate(nets, 1))
    body = (f'\t\t(property "Reference" "{ref}"\n\t\t)\n'
            + (f'\t\t(property "Spec" "{spec}"\n\t\t)\n' if spec else "")
            + pads)
    return f'\t(footprint "F"\n{body}\t)\n\t(gr_line)\n'


PROJECT = {"net_settings": {
    "classes": [{"name": "Default", "track_width": 0.2},
                {"name": "Power", "track_width": 0.8}],
    "netclass_patterns": [{"netclass": "Power", "pattern": "/5V*"},
                          {"netclass": "Power", "pattern": "GND*"}]}}


class TestDamageCurrent(unittest.TestCase):
    def test_narrow_trace_has_lower_damage_current_than_wide(self):
        self.assertLess(ampacity.damage_current(0.2), ampacity.damage_current(0.8))

    def test_matches_ipc_2221_closed_form_for_1oz_copper(self):
        # 0.2 mm at 1 oz reaching a 130 C Tg from 25 C ambient
        self.assertAlmostEqual(ampacity.damage_current(0.2), 2.10, places=1)

    def test_thinner_copper_lowers_the_damage_current(self):
        self.assertLess(ampacity.damage_current(0.2, thickness_mm=0.0175),
                        ampacity.damage_current(0.2, thickness_mm=0.035))


class TestNetclassConformance(unittest.TestCase):
    def test_net_routed_narrower_than_its_netclass_is_reported(self):
        f = ampacity.netclass_conformance(board([("/5V", 0.2)]), PROJECT)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].type, "netclass_width")

    def test_netclass_width_reports_but_does_not_block(self):
        # A short neck-down at a pad is normal; blocking on width alone would
        # fire on almost every board and get the gate ignored.
        f = ampacity.netclass_conformance(board([("/5V", 0.2)]), PROJECT)
        self.assertFalse(f[0].blocking)

    def test_net_routed_at_its_netclass_width_is_clean(self):
        self.assertEqual(ampacity.netclass_conformance(board([("/5V", 0.8)]), PROJECT), [])

    def test_net_routed_wider_than_its_netclass_is_clean(self):
        self.assertEqual(ampacity.netclass_conformance(board([("/5V", 1.2)]), PROJECT), [])

    def test_the_narrowest_segment_decides(self):
        f = ampacity.netclass_conformance(
            board([("/5V", 0.8), ("/5V", 0.2), ("/5V", 0.8)]), PROJECT)
        self.assertEqual(len(f), 1)
        self.assertIn("0.2 mm", f[0].description)

    def test_net_matching_no_pattern_is_not_checked(self):
        # This is the defect the checks exist for: /raw_5v matches no pattern,
        # so it inherits Default and nothing here can flag it. fuse_ampacity is
        # the check that catches it.
        self.assertEqual(ampacity.netclass_conformance(board([("/raw_5v", 0.2)]), PROJECT), [])

    def test_glob_patterns_are_not_treated_as_regexes(self):
        project = {"net_settings": {
            "classes": [{"name": "Power", "track_width": 0.8}],
            "netclass_patterns": [{"netclass": "Power", "pattern": "/5V*"}]}}
        # "/5VX" matches the glob; "/x5V" must not
        self.assertEqual(len(ampacity.netclass_conformance(board([("/5VX", 0.2)]), project)), 1)
        self.assertEqual(ampacity.netclass_conformance(board([("/x5V", 0.2)]), project), [])


class TestFuseAmpacity(unittest.TestCase):
    def test_long_hairline_run_below_the_fuse_trip_is_blocking(self):
        f = ampacity.fuse_ampacity(board([("/raw_5v", 0.2, 8.0)], fuse()))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].type, "fuse_trace_ordering")
        self.assertTrue(f[0].blocking)
        self.assertIn("3.8", f[0].description)

    def test_trace_that_survives_the_fuse_trip_is_clean(self):
        self.assertEqual(
            ampacity.fuse_ampacity(board([("/raw_5v", 0.8, 8.0)], fuse())), [])

    def test_short_neck_flanked_by_wide_copper_is_not_reported(self):
        # The distinction the healing length exists to make: this is the shape
        # of the corrected board, and it must come out clean.
        b = board([("/raw_5v", 0.8, 6.0), ("/raw_5v", 0.2, 0.7),
                   ("/raw_5v", 0.8, 6.0)], fuse())
        self.assertEqual(ampacity.fuse_ampacity(b), [])

    def test_a_long_neck_between_the_same_wide_copper_is_reported(self):
        b = board([("/raw_5v", 0.8, 6.0), ("/raw_5v", 0.2, 8.0),
                   ("/raw_5v", 0.8, 6.0)], fuse())
        self.assertEqual(len(ampacity.fuse_ampacity(b)), 1)

    def test_healing_credit_grows_with_run_length(self):
        self.assertGreater(ampacity.damage_current(0.2, run_mm=0.5),
                           ampacity.damage_current(0.2, run_mm=5.0))

    def test_a_very_long_run_converges_on_the_uncorrected_value(self):
        self.assertAlmostEqual(ampacity.damage_current(0.2, run_mm=100.0),
                               ampacity.damage_current(0.2), places=2)

    def test_fuse_without_a_recorded_trip_current_warns_but_does_not_block(self):
        f = ampacity.fuse_ampacity(board([("/raw_5v", 0.2, 8.0)], fuse(spec="")))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].type, "fuse_trip_unknown")
        self.assertFalse(f[0].blocking)

    def test_unrouted_fused_net_is_not_reported(self):
        self.assertEqual(ampacity.fuse_ampacity(board([], fuse())), [])

    def test_both_nets_of_a_two_pin_fuse_are_checked(self):
        b = board([("/raw_5v", 0.2, 8.0), ("/fused_5v", 0.2, 8.0)],
                  fuse(nets=("/raw_5v", "/fused_5v")))
        self.assertEqual(len(ampacity.fuse_ampacity(b)), 2)

    def test_non_fuse_references_are_ignored(self):
        b = board([("/raw_5v", 0.2, 8.0)], fuse(ref="R1"))
        self.assertEqual(ampacity.fuse_ampacity(b), [])

    def test_thinner_copper_can_turn_a_clean_board_into_a_finding(self):
        b = board([("/raw_5v", 0.8, 8.0)], fuse())
        self.assertEqual(ampacity.fuse_ampacity(b), [])
        self.assertEqual(len(ampacity.fuse_ampacity(b, thickness_mm=0.0175)), 1)


if __name__ == "__main__":
    unittest.main()
