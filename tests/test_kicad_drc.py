import json
import os
import tempfile
import unittest
from gate.kicad import run_drc, KicadUnavailable


class TestRunDrc(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def runner(self, payload=None, returncode=0):
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
            r.returncode, r.stdout, r.stderr = returncode, "", ""
            return r
        return _run

    def test_returns_parsed_json(self):
        drc = run_drc("kicad-cli", "board.kicad_pcb", runner=self.runner())
        self.assertEqual(drc["violations"], [])

    def test_passes_the_flags_the_gate_depends_on(self):
        run_drc("kicad-cli", "board.kicad_pcb", runner=self.runner())
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
            run_drc("kicad-cli", "board.kicad_pcb", runner=failing)
