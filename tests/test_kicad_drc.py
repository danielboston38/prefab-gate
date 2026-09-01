import json
import unittest
from gate.kicad import run_drc, KicadUnavailable

# kicad-cli's real wording when it cannot load the schematic. It prints this to
# stderr and still exits 0, emitting an empty schematic_parity list.
PARITY_FAILED_STDERR = (
    "Failed to fetch schematic netlist for parity tests.\n"
    "Schematic parity tests require a fully annotated schematic.\n")

# kicad-cli's real stdout. Verified against KiCad 10.0.6: the parity line is
# printed whenever the parity tests ran — including when they ran and found
# nothing — and is absent entirely when they could not run. The default here is
# the "parity ran" case, because that is what a plain successful DRC looks like;
# a double that omitted it was claiming kicad-cli says nothing about parity.
STDOUT_PARITY_RAN = ("Found 0 violations\n"
                     "Found 0 unconnected items\n"
                     "Found 0 schematic parity issues\n"
                     "Saved DRC Report to drc.json\n")
STDOUT_PARITY_DID_NOT_RUN = ("Found 0 violations\n"
                             "Found 0 unconnected items\n"
                             "Saved DRC Report to drc.json\n")


def fake_runner(calls, payload=None, returncode=0, stderr="",
                stdout=STDOUT_PARITY_RAN):
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
        r.returncode, r.stdout, r.stderr = returncode, stdout, stderr
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

    def test_raises_board_unreadable_when_kicad_cli_fails(self):
        # Was KicadUnavailable, which routed a board kicad-cli merely refused
        # to the exit-3 "your KiCad install is broken" path. A corpus sweep
        # found four such boards: two 2-byte stubs and two with items on
        # undefined layers.
        from gate.kicad import BoardUnreadable

        def failing(cmd, **kwargs):
            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = 1, "", "boom"
            return r
        with self.assertRaises(BoardUnreadable):
            run_drc("kicad-cli", "board.kicad_pcb", runner=failing)


class TestParityFailureIsReported(unittest.TestCase):
    """kicad-cli exits 0 with an empty parity list; that is not a pass.

    run_drc reports it rather than raising: the violations in the same report
    are valid, it is only the parity half that did not run.
    """

    def test_the_marker_is_returned_even_on_exit_zero(self):
        drc, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stderr=PARITY_FAILED_STDERR,
                               stdout=STDOUT_PARITY_DID_NOT_RUN))
        self.assertEqual(drc["schematic_parity"], [])
        self.assertIn("Failed to fetch schematic netlist", parity_error)

    def test_the_annotation_marker_alone_is_reported_too(self):
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stdout=STDOUT_PARITY_DID_NOT_RUN, stderr=(
                "Schematic parity tests require a fully annotated schematic.")))
        self.assertTrue(parity_error)

    def test_the_marker_is_ignored_when_parity_was_not_requested(self):
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb", parity=False,
            runner=fake_runner([], stderr=PARITY_FAILED_STDERR,
                               stdout=STDOUT_PARITY_DID_NOT_RUN))
        self.assertEqual(parity_error, "")


class TestBoardKicadCliRejects(unittest.TestCase):
    """kicad-cli running and refusing the board is bad input, not a bad environment.

    locate_cli and probe_capability have already established that kicad-cli
    exists and supports every flag by the time run_drc is called, so a non-zero
    exit here means it ran and rejected this board.
    """

    def test_non_zero_exit_raises_board_unreadable(self):
        from gate.kicad import BoardUnreadable
        calls = []
        runner = fake_runner(calls, returncode=3, stderr=(
            "Failed to load board: One or more items were found on undefined "
            "layers (Rescue). Open the board in the PCB Editor to resolve."))
        with self.assertRaises(BoardUnreadable) as caught:
            run_drc("kicad-cli", "b.kicad_pcb", runner=runner)
        self.assertIn("undefined layers", str(caught.exception))

    def test_board_unreadable_is_not_an_environment_error(self):
        from gate.kicad import BoardUnreadable
        self.assertFalse(issubclass(BoardUnreadable, KicadUnavailable))


class TestParityMustBeProvenToHaveRun(unittest.TestCase):
    """Absence of a failure message is not evidence that parity ran.

    kicad-cli exits 0 and writes "schematic_parity": [] both when parity ran
    and found nothing and when it could not run at all, so the JSON alone
    cannot tell them apart. The one signal that does is on stdout: verified
    against KiCad 10.0.6, "Found <n> schematic parity issues" is printed
    whenever the tests ran, including for n = 0, and is absent when they did
    not. Keying on that inverts the invariant — parity has to be affirmed,
    rather than its failure being recognised from wording that is not an API.
    """

    def test_unrecognised_failure_wording_still_fails_closed(self):
        # The regression the marker list could not survive: KiCad rewords its
        # diagnostic, keeps exiting 0, and keeps emitting an empty list.
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stdout=STDOUT_PARITY_DID_NOT_RUN,
                               stderr="Unable to obtain schematic netlist.\n"))
        self.assertTrue(parity_error)
        self.assertIn("Unable to obtain schematic netlist", parity_error)

    def test_silence_fails_closed_with_an_explanation(self):
        # No parity line and nothing on stderr either. The gate still may not
        # call that a clean parity result, and the reason it reports cannot be
        # an empty string.
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stdout=STDOUT_PARITY_DID_NOT_RUN, stderr=""))
        self.assertTrue(parity_error)

    def test_parity_that_ran_and_found_nothing_is_a_pass(self):
        # The case that decides the design: a genuinely clean board must not
        # be reported as unverified.
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stdout=STDOUT_PARITY_RAN))
        self.assertEqual(parity_error, "")

    def test_parity_that_ran_and_found_issues_is_a_pass(self):
        _, parity_error = run_drc(
            "kicad-cli", "board.kicad_pcb",
            runner=fake_runner([], stdout=(
                "Found 8 violations\n"
                "Found 0 unconnected items\n"
                "Found 27 schematic parity issues\n")))
        self.assertEqual(parity_error, "")
