import os
import unittest

import konnect_hook
from test_schematic_change_check import FakeExport, Project


def call(tool, **tool_input):
    return {"tool_name": f"mcp__konnect__{tool}", "tool_input": tool_input}


class Hook(unittest.TestCase):
    def setUp(self):
        self.p = Project(self)
        self.export = FakeExport()

    def run_hook(self, phase, data):
        return konnect_hook.main(phase, data, store=self.p.store, export=self.export)

    def test_no_schematic_key_does_nothing(self):
        self.assertIsNone(self.run_hook("pre", call("list_toolboxes")))
        self.assertFalse(os.path.exists(self.p.store))

    def test_other_file_types_are_ignored(self):
        board = os.path.join(self.p.dir, "top.kicad_pcb")
        self.assertIsNone(self.run_hook("pre", call("open_project", path=board)))
        self.assertFalse(os.path.exists(self.p.store))

    def test_pre_takes_snapshot(self):
        self.assertIsNone(self.run_hook("pre", call("list_schematic_nets", schematic=self.p.top)))
        self.assertTrue(os.path.exists(os.path.join(self.p.store, "top.kicad_sch")))

    def test_path_key_is_accepted_for_schematics(self):
        self.run_hook("pre", call("get_schematic_view", path=self.p.top))
        self.assertTrue(os.path.exists(os.path.join(self.p.store, "top.kicad_sch")))

    def test_post_without_change_is_silent(self):
        data = call("list_schematic_nets", schematic=self.p.top)
        self.run_hook("pre", data)
        self.assertIsNone(self.run_hook("post", data))
        self.assertEqual(self.export.calls, [])

    def test_post_with_change_reports(self):
        data = call("edit_schematic_component", schematic=self.p.top, reference="R5")
        self.run_hook("pre", data)
        self.p.write("top.kicad_sch", "(kicad_sch R5 4k7)")
        out = self.run_hook("post", data)
        self.assertEqual(out["systemMessage"],
                         "Schematic changes (top.kicad_sch):\nR5 value 10k -> 4k7")
        self.assertEqual(out["hookSpecificOutput"], {
            "hookEventName": "PostToolUse",
            "additionalContext": "Schematic changes from "
                                 "mcp__konnect__edit_schematic_component "
                                 "(top.kicad_sch):\nR5 value 10k -> 4k7"})

    def test_cosmetic_change_is_reported_once(self):
        data = call("move_schematic_component", schematic=self.p.top, reference="R5")
        self.run_hook("pre", data)
        self.p.write("top.kicad_sch", "(kicad_sch R5 10k moved)")
        out = self.run_hook("post", data)
        self.assertIn("connectivity unchanged", out["systemMessage"])

    def test_errors_never_raise(self):
        def broken(_):
            raise RuntimeError("kicad-cli exploded")
        data = call("edit_schematic_component", schematic=self.p.top, reference="R5")
        self.run_hook("pre", data)
        self.p.write("top.kicad_sch", "(kicad_sch R5 4k7)")
        out = konnect_hook.main("post", data, store=self.p.store, export=broken)
        self.assertTrue(out["systemMessage"].startswith("schematic change check could not run:"))

    def test_calls_in_parallel_keep_their_own_snapshots(self):
        a = dict(call("edit_schematic_component", schematic=self.p.top), tool_use_id="a")
        b = dict(call("list_schematic_nets", schematic=self.p.top), tool_use_id="b")
        konnect_hook.main("pre", a, export=self.export, base=self.p.store)
        self.p.write("top.kicad_sch", "(kicad_sch R5 4k7)")   # call A writes
        konnect_hook.main("pre", b, export=self.export, base=self.p.store)
        out_a = konnect_hook.main("post", a, export=self.export, base=self.p.store)
        out_b = konnect_hook.main("post", b, export=self.export, base=self.p.store)
        self.assertIn("R5 value 10k -> 4k7", out_a["systemMessage"])
        self.assertIsNone(out_b)

    def test_post_removes_its_snapshot(self):
        a = dict(call("list_schematic_nets", schematic=self.p.top), tool_use_id="a")
        konnect_hook.main("pre", a, export=self.export, base=self.p.store)
        konnect_hook.main("post", a, export=self.export, base=self.p.store)
        self.assertEqual(os.listdir(self.p.store), [])

    def test_failed_call_reports_under_its_own_event(self):
        data = dict(call("edit_schematic_component", schematic=self.p.top),
                    hook_event_name="PostToolUseFailure")
        self.run_hook("pre", data)
        self.p.write("top.kicad_sch", "(kicad_sch R5 4k7)")
        out = self.run_hook("post", data)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure")

    def test_post_without_snapshot_says_so(self):
        out = self.run_hook("post", call("edit_schematic_component", schematic=self.p.top))
        self.assertTrue(out["systemMessage"].startswith("schematic change check could not run:"))


if __name__ == "__main__":
    unittest.main()
