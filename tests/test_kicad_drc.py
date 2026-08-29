import json
import unittest
from gate.kicad import run_drc, KicadUnavailable

# kicad-cli's real wording when it cannot load the schematic. It prints this to
# stderr and still exits 0, emitting an empty schematic_parity list.
PARITY_FAILED_STDERR = (
    "Failed to fetch schematic netlist for parity tests.\n"
    "Schematic parity tests require a fully annotated schematic.\n")


def fake_runner(calls, payload=None, returncode=0, stderr=""):
    def _run(cmd, **kwargs):
        calls.append(cmd)
        out = cmd[cmd.index("-o") + 1]
        with open(out, "w") as fh:
            json.dump(payload if payload is not None
                      else {"violations": [], "unconnected_items": [],
                            "schematic_parity": []}, fh)

        class R:
            pass
        r = R()
        r.returncode, r.stdout, r.stderr = returncode, "", stderr
        return r
    return _run


class TestRunDrc(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def test_returns_parsed_json_and_no_parity_error(self):
        drc, parity_error = run_drc("kicad-cli", "board.kicad_pcb",
                                    runner=fake_runner(self.calls))
        self.assertEqual(drc["violations"], [])
        self.assertEqual(parity_error, "")

    def test_passes_the_flags_the_gate_depends_on(self):
        run_drc("kicad-cli", "board.kicad_pcb", runner=fake_runner(self.calls))
        cmd = " ".join(self.calls[0])
        for flag in ("--format json", "--severity-all", "--schematic-parity",
                     "--refill-zones", "--save-board"):
            self.assertIn(flag, cmd)

    def test_parity_false_drops_the_parity_flag_but_keeps_the_rest(self):
        run_drc("kicad-cli", "board.kicad_pcb", runner=fake_runner(self.calls),
                parity=False)
        cmd = " ".join(self.calls[0])
        self.assertNotIn("--schematic-parity", cmd)
        for flag in ("--severity-all", "--refill-zones", "--save-board"):
            self.assertIn(flag, cmd)

    def test_raises_when_kicad_cli_fails(self):
        def failing(cmd, **kwargs):
            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = 1, "", "boom"
            return r
        with self.assertRaises(KicadUnavailable):
            run_drc("kicad-cli", "board.kicad_pcb", runner=failing)


class TestParityFailureIsReported(unittest.TestCase):
    """kicad-cli exits 0 with an empty parity list; that is not a pass.

    run_drc reports it rather than raising: the violations in the same report
    are valid, it is only the parity half that did not run.
    """

    def test_the_marker_is_returned_even_on_exit_zero(self):
        drc, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stderr=PARITY_FAILED_STDERR))
        self.assertEqual(drc["schematic_parity"], [])
        self.assertIn("Failed to fetch schematic netlist", parity_error)

    def test_the_annotation_marker_alone_is_reported_too(self):
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stderr=(
                "Schematic parity tests require a fully annotated schematic.")))
        self.assertTrue(parity_error)

    def test_the_marker_is_ignored_when_parity_was_not_requested(self):
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb", parity=False,
            runner=fake_runner([], stderr=PARITY_FAILED_STDERR))
        self.assertEqual(parity_error, "")
