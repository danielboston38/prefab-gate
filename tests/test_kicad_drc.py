import json
import unittest
from gate.kicad import run_drc, KicadUnavailable

# kicad-cli's real wording when it cannot load the schematic. It prints this to
# stderr and still exits 0, emitting an empty schematic_parity list.
PARITY_FAILED_STDERR = (
    "Failed to fetch schematic netlist for parity tests.\n"
    "Schematic parity tests require a fully annotated schematic.\n")


class TestRunDrc(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def runner(self, payload=None, returncode=0, stderr=""):
        def _run(cmd, **kwargs):
            self.calls.append(cmd)
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

    def run_drc(self, **kwargs):
        kwargs.setdefault("exists", lambda p: True)
        return run_drc("kicad-cli", "board.kicad_pcb", **kwargs)

    def test_returns_parsed_json(self):
        drc = self.run_drc(runner=self.runner())
        self.assertEqual(drc["violations"], [])

    def test_passes_the_flags_the_gate_depends_on(self):
        self.run_drc(runner=self.runner())
        cmd = " ".join(self.calls[0])
        for flag in ("--format json", "--severity-all", "--schematic-parity",
                     "--refill-zones", "--save-board"):
            self.assertIn(flag, cmd)

    def test_raises_when_kicad_cli_fails(self):
        def failing(cmd, **kwargs):
            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = 1, "", "boom"
            return r
        with self.assertRaises(KicadUnavailable):
            self.run_drc(runner=failing)


class TestParityFailsClosed(unittest.TestCase):
    """Parity is the check the gate cannot afford to silently skip."""

    def test_a_missing_schematic_raises_before_kicad_cli_is_invoked(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            raise AssertionError("kicad-cli must not run without a schematic")

        with self.assertRaises(KicadUnavailable) as ctx:
            run_drc("kicad-cli", "/p/board.kicad_pcb", runner=runner,
                    exists=lambda p: False)
        self.assertIn("/p/board.kicad_sch", str(ctx.exception))
        self.assertEqual(calls, [])

    def test_the_parity_failure_marker_raises_even_on_exit_zero(self):
        """kicad-cli exits 0 with an empty parity list; that is not a pass."""
        def runner(cmd, **kwargs):
            out = cmd[cmd.index("-o") + 1]
            with open(out, "w") as fh:
                json.dump({"violations": [], "unconnected_items": [],
                           "schematic_parity": []}, fh)

            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = 0, "", PARITY_FAILED_STDERR
            return r

        with self.assertRaises(KicadUnavailable) as ctx:
            run_drc("kicad-cli", "board.kicad_pcb", runner=runner,
                    exists=lambda p: True)
        self.assertIn("Failed to fetch schematic netlist", str(ctx.exception))

    def test_the_annotation_marker_alone_also_raises(self):
        def runner(cmd, **kwargs):
            out = cmd[cmd.index("-o") + 1]
            with open(out, "w") as fh:
                json.dump({"violations": [], "unconnected_items": [],
                           "schematic_parity": []}, fh)

            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = (
                0, "", "Schematic parity tests require a fully annotated schematic.")
            return r

        with self.assertRaises(KicadUnavailable):
            run_drc("kicad-cli", "board.kicad_pcb", runner=runner,
                    exists=lambda p: True)
