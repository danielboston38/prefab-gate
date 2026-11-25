import unittest

from gate.schdiff import DuplicateReference, compare, read_netlist


def netlist(parts, nets):
    """kicad-cli netlist text.

    parts: (ref, value, footprint) tuples. nets: {name: [(ref, pin), ...]}.
    """
    comps = "".join(
        f'\t\t(comp\n\t\t\t(ref "{ref}")\n\t\t\t(value "{value}")\n'
        f'\t\t\t(footprint "{fp}")\n'
        f'\t\t\t(libsource\n\t\t\t\t(lib "Device")\n\t\t\t\t(part "R")\n\t\t\t)\n'
        f'\t\t)\n'
        for ref, value, fp in parts)
    body = ""
    for code, (name, nodes) in enumerate(nets.items(), 1):
        node_text = "".join(
            f'\t\t\t(node\n\t\t\t\t(ref "{r}")\n\t\t\t\t(pin "{p}")\n'
            f'\t\t\t\t(pintype "passive")\n\t\t\t)\n'
            for r, p in nodes)
        body += (f'\t\t(net\n\t\t\t(code "{code}")\n\t\t\t(name "{name}")\n'
                 f'\t\t\t(class "Default")\n{node_text}\t\t)\n')
    return (f'(export\n\t(version "E")\n\t(components\n{comps}\t)\n'
            f'\t(nets\n{body}\t)\n)\n')


PARTS = [("R5", "10k", "R_0603"), ("U4", "74LVC245A", "SOIC-20")]
NETS = {"/P_PHI2": [("U4", "3"), ("R5", "1")],
        "GND": [("U4", "10")],
        "Net-(R5-Pad2)": [("R5", "2"), ("U4", "17")]}


class ReadNetlist(unittest.TestCase):
    def test_leading_slash_is_dropped(self):
        n = read_netlist(netlist(PARTS, NETS))
        self.assertEqual(n.pin_net[("U4", "3")], "P_PHI2")

    def test_parts_are_read(self):
        n = read_netlist(netlist(PARTS, NETS))
        self.assertEqual(n.parts["R5"],
                         {"value": "10k", "footprint": "R_0603", "lib": "Device:R"})


class Compare(unittest.TestCase):
    def changes(self, new_parts, new_nets, old_parts=PARTS, old_nets=NETS):
        return compare(read_netlist(netlist(old_parts, old_nets)),
                       read_netlist(netlist(new_parts, new_nets)))

    def test_identical_netlists_have_no_changes(self):
        self.assertEqual(self.changes(PARTS, NETS), [])

    def test_part_added_and_removed(self):
        parts = [("U4", "74LVC245A", "SOIC-20"), ("C9", "100n", "C_0603")]
        nets = {"/P_PHI2": [("U4", "3")], "GND": [("U4", "10"), ("C9", "2")],
                "Net-(U4-B1)": [("U4", "17")]}
        got = self.changes(parts, nets)
        self.assertIn("+ C9 100n (C_0603)", got)
        self.assertIn("- R5 10k (R_0603)", got)

    def test_value_and_footprint_change(self):
        parts = [("R5", "4k7", "R_0805"), PARTS[1]]
        self.assertEqual(self.changes(parts, NETS),
                         ["R5 footprint R_0603 -> R_0805", "R5 value 10k -> 4k7"])

    def test_pin_moves_to_other_named_net(self):
        nets = {"/P_PHI2": [("R5", "1")], "GND": [("U4", "10"), ("U4", "3")],
                "Net-(R5-Pad2)": [("R5", "2"), ("U4", "17")]}
        self.assertEqual(self.changes(PARTS, nets), ["U4.3: P_PHI2 -> GND"])

    def test_pin_disconnected(self):
        nets = {"/P_PHI2": [("R5", "1")], "GND": [("U4", "10")],
                "unconnected-(U4-A1-Pad3)": [("U4", "3")],
                "Net-(R5-Pad2)": [("R5", "2"), ("U4", "17")]}
        self.assertEqual(self.changes(PARTS, nets), ["U4.3: P_PHI2 -> (none)"])

    def test_rename_is_one_line(self):
        parts = [("R7", "10k", "R_0603"), PARTS[1]]
        nets = {"/P_PHI2": [("U4", "3"), ("R7", "1")], "GND": [("U4", "10")],
                "Net-(R7-Pad2)": [("R7", "2"), ("U4", "17")]}
        self.assertEqual(self.changes(parts, nets), ["rename R5 -> R7"])

    def test_auto_net_compared_by_members(self):
        nets = dict(NETS)
        nets["Net-(U4-B1)"] = nets.pop("Net-(R5-Pad2)")
        self.assertEqual(self.changes(PARTS, nets), [])

    def test_auto_net_gaining_a_pin_is_reported(self):
        # Only the pin that moved is reported, not the pins it joined.
        nets = {"/P_PHI2": [("U4", "3"), ("R5", "1")],
                "Net-(R5-Pad2)": [("R5", "2"), ("U4", "17"), ("U4", "10")]}
        self.assertEqual(self.changes(PARTS, nets),
                         ["U4.10: GND -> Net-(R5-Pad2)"])


SPLIT_PARTS = [("R1", "1k", "R"), ("C1", "1n", "C"), ("R2", "1k", "R"), ("C2", "1n", "C")]
JOINED = {"Net-(R1-Pad1)": [("R1", "1"), ("C1", "1"), ("R2", "1"), ("C2", "1")]}
APART = {"Net-(R1-Pad1)": [("R1", "1"), ("C1", "1")],
         "Net-(C2-Pad1)": [("R2", "1"), ("C2", "1")]}


class SplitAndMerge(unittest.TestCase):
    def changes(self, old_nets, new_nets):
        return compare(read_netlist(netlist(SPLIT_PARTS, old_nets)),
                       read_netlist(netlist(SPLIT_PARTS, new_nets)))

    def test_split_of_made_up_net_is_reported(self):
        got = self.changes(JOINED, APART)
        self.assertEqual(len(got), 2, got)
        self.assertTrue(all("-> Net-(C2-Pad1)" in line for line in got), got)

    def test_merge_of_made_up_nets_is_reported(self):
        self.assertEqual(len(self.changes(APART, JOINED)), 2)

    def test_sheet_path_made_up_names_are_matched_by_members(self):
        old = {"/sub/Net-(R1-Pad1)": APART["Net-(R1-Pad1)"],
               "/sub/Net-(C2-Pad1)": APART["Net-(C2-Pad1)"]}
        new = {"/sub/Net-(C1-Pad1)": APART["Net-(R1-Pad1)"],
               "/sub/Net-(R2-Pad1)": APART["Net-(C2-Pad1)"]}
        self.assertEqual(self.changes(old, new), [])


class Duplicates(unittest.TestCase):
    def test_duplicate_reference_refuses(self):
        text = netlist([("R?", "1k", "R"), ("R?", "2k", "R")], {"GND": [("R?", "1")]})
        with self.assertRaises(DuplicateReference):
            read_netlist(text)

    def test_duplicate_pin_refuses(self):
        text = netlist([("R?", "1k", "R")],
                       {"GND": [("R?", "1")], "VCC": [("R?", "1")]})
        with self.assertRaises(DuplicateReference):
            read_netlist(text)


if __name__ == "__main__":
    unittest.main()
