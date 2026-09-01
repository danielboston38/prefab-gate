"""Facts about real kicad-cli that the unit-test doubles encode.

Every other test in this suite drives a double. The doubles are only worth
anything while they still describe the tool: the gate's central design — that
parity is proven from a line kicad-cli prints, not inferred from a diagnostic
it might reword — rests entirely on claims about kicad-cli's behaviour that no
amount of mocking can check. So these tests skip the doubles and assert those
claims against the installed kicad-cli, and are skipped when there is none.

Verified against KiCad 10.0.6. A failure here does not mean the gate is wrong;
it means kicad-cli changed and the doubles are now fiction, which is the one
failure mode a green unit suite cannot report.
"""
import json
import os
import subprocess
import tempfile
import unittest

from gate.classify import ReportInvalid, validate_report
from gate.kicad import (PARITY_RAN, KicadUnavailable, locate_cli,
                        probe_capability, run_drc)

# Minimal but real. A fixture pinned to the project's own board would test the
# board; these tests are about the tool.
BOARD = """(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general (thickness 1.6) (legacy_teardrops no))
\t(paper "A4")
\t(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
\t(setup (pad_to_mask_clearance 0))
\t(net 0 "")
)
"""
SCHEMATIC = """(kicad_sch (version 20231120) (generator "eeschema")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
)
"""


def _cli():
    try:
        return locate_cli()
    except KicadUnavailable:
        return None


CLI = _cli()


@unittest.skipIf(CLI is None, "no kicad-cli installed")
class KicadContract(unittest.TestCase):
    """Base fixture: a board, and a schematic whose name the caller chooses."""

    schematic_name = "board.kicad_sch"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = os.path.join(self.tmp.name, "board.kicad_pcb")
        with open(self.board, "w") as fh:
            fh.write(BOARD)
        with open(os.path.join(self.tmp.name, self.schematic_name), "w") as fh:
            fh.write(SCHEMATIC)

    def drc(self, parity=True):
        """Raw kicad-cli, not run_drc: these tests are what run_drc relies on."""
        out = os.path.join(self.tmp.name, "drc.json")
        cmd = [CLI, "pcb", "drc", "--format", "json", "--severity-all"]
        if parity:
            cmd.append("--schematic-parity")
        cmd += ["-o", out, self.board]
        result = subprocess.run(cmd, capture_output=True, text=True)
        with open(out) as fh:
            return result, json.load(fh)


class TestParityRanIsAffirmedOnStdout(KicadContract):
    """The signal the whole F-04 design rests on."""

    def test_the_parity_line_is_printed_when_parity_runs_clean(self):
        # The case that decides the design. If kicad-cli only printed this line
        # when it had something to report, requiring it would fail every clean
        # board, and the gate would be unusable rather than merely wrong.
        result, report = self.drc()
        self.assertEqual(report["schematic_parity"], [])
        self.assertTrue(PARITY_RAN.search(result.stdout),
                        f"no parity affirmation in stdout: {result.stdout!r}")

    def test_the_production_pattern_is_what_matches_it(self):
        # Pins the regex in gate.kicad, not a copy of it, to real output.
        result, _ = self.drc()
        self.assertRegex(result.stdout, PARITY_RAN)

    def test_parity_is_not_claimed_when_it_was_not_requested(self):
        result, _ = self.drc(parity=False)
        self.assertIsNone(PARITY_RAN.search(result.stdout))


class TestParityFailureIsSilentInEveryOtherChannel(KicadContract):
    """Why the affirmation is needed at all.

    A schematic not named after the board cannot be read by `pcb drc`. This is
    the F-06 scenario, and it is indistinguishable from a clean parity result
    everywhere except stdout.
    """

    schematic_name = "some_other_name.kicad_sch"

    def test_kicad_cli_still_exits_zero(self):
        result, _ = self.drc()
        self.assertEqual(result.returncode, 0)

    def test_and_still_reports_an_empty_parity_list(self):
        _, report = self.drc()
        self.assertEqual(report["schematic_parity"], [])

    def test_so_only_the_missing_stdout_line_distinguishes_it(self):
        result, _ = self.drc()
        self.assertIsNone(PARITY_RAN.search(result.stdout),
                          f"parity was affirmed but cannot have run: "
                          f"{result.stdout!r}")

    def test_run_drc_turns_that_into_a_reason_rather_than_a_pass(self):
        drc, parity_error = run_drc(CLI, self.board)
        self.assertEqual(drc["schematic_parity"], [])
        self.assertTrue(parity_error)


class TestTheReportAlwaysCarriesItsSections(KicadContract):
    """What validate_report is entitled to demand.

    Requiring a section that kicad-cli omits would reject good boards, so the
    requirement is only safe while this holds.
    """

    def test_all_three_sections_are_present_with_parity(self):
        _, report = self.drc()
        for key in ("violations", "unconnected_items", "schematic_parity"):
            self.assertIn(key, report)
            self.assertIsInstance(report[key], list)

    def test_the_parity_section_is_present_even_without_the_flag(self):
        _, report = self.drc(parity=False)
        self.assertIn("schematic_parity", report)

    def test_a_real_report_satisfies_the_validator(self):
        _, report = self.drc()
        try:
            validate_report(report, parity_requested=True)
        except ReportInvalid as exc:
            self.fail(f"the validator rejects real kicad-cli output: {exc}")


@unittest.skipIf(CLI is None, "no kicad-cli installed")
class TestTheProbeAgreesWithTheInstalledCli(unittest.TestCase):
    def test_every_required_flag_really_exists(self):
        # REQUIRED_FLAGS is a claim about kicad-cli's interface. If a flag were
        # renamed the doubles would keep accepting it and only real runs would
        # break.
        probe_capability(CLI)
