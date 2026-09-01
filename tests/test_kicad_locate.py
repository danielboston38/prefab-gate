import unittest
from gate.kicad import locate_cli, probe_capability, KicadUnavailable

# Trimmed from the real `kicad-cli pcb drc --help` on KiCad 10.
HELP = ("Usage: pcb drc [--help] [--output OUTPUT_FILE] [--format FORMAT] "
        "[--schematic-parity] [--severity-all] [--exit-code-violations] "
        "[--refill-zones] [--save-board] INPUT_FILE")


class Result:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode = stdout, returncode
        self.stderr = stderr


class TestLocate(unittest.TestCase):
    def test_env_var_wins(self):
        found = locate_cli(env={"KICAD_CLI": "/custom/kicad-cli"},
                           which=lambda n: None, exists=lambda p: True)
        self.assertEqual(found, "/custom/kicad-cli")

    def test_falls_back_to_path(self):
        found = locate_cli(env={}, which=lambda n: "/usr/bin/kicad-cli",
                           exists=lambda p: False)
        self.assertEqual(found, "/usr/bin/kicad-cli")

    def test_raises_when_absent_everywhere(self):
        with self.assertRaises(KicadUnavailable) as ctx:
            locate_cli(env={}, which=lambda n: None, exists=lambda p: False,
                       globber=lambda pattern: [])
        self.assertIn("kicad-cli", str(ctx.exception))

    def test_windows_install_is_globbed_not_pinned_to_one_version(self):
        """KiCad installs under a version directory; 9.0 must not be hard-coded."""
        installs = [r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                    r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"]
        found = locate_cli(env={}, which=lambda n: None,
                           exists=lambda p: p in installs,
                           globber=lambda pattern: (
                               installs if "Program Files\\KiCad" in pattern else []))
        # 10.0, not 9.0: a lexical sort would get this backwards.
        self.assertEqual(found, r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

    def test_env_var_pointing_at_nothing_is_an_error(self):
        with self.assertRaises(KicadUnavailable):
            locate_cli(env={"KICAD_CLI": "/nope"}, which=lambda n: None,
                       exists=lambda p: False)


class TestProbe(unittest.TestCase):
    def test_accepts_a_capable_cli(self):
        probe_capability("kicad-cli", runner=lambda *a, **k: Result(HELP))

    def test_rejects_and_names_the_missing_flag(self):
        stripped = HELP.replace("[--schematic-parity] ", "")
        with self.assertRaises(KicadUnavailable) as ctx:
            probe_capability("kicad-cli", runner=lambda *a, **k: Result(stripped))
        self.assertIn("--schematic-parity", str(ctx.exception))


class TestProbeRequiresTheHelpCommandToSucceed(unittest.TestCase):
    """Text printed by a failed command is not evidence of a capability.

    The probe searched --help output for the flags it needs and never looked
    at the exit status, so a wrapper or a broken executable that fails while
    still printing usage was accepted. Everything after that point assumes
    kicad-cli works, which is why a non-zero DRC exit is treated as a bad
    board rather than a bad install — an assumption the probe has to earn.
    """

    def test_a_failed_probe_is_rejected_even_with_every_flag_present(self):
        with self.assertRaises(KicadUnavailable):
            probe_capability("kicad-cli",
                             runner=lambda *a, **k: Result(HELP, returncode=1))

    def test_the_rejection_reports_the_exit_status(self):
        with self.assertRaises(KicadUnavailable) as ctx:
            probe_capability("kicad-cli",
                             runner=lambda *a, **k: Result(HELP, returncode=127))
        self.assertIn("127", str(ctx.exception))

    def test_help_printed_on_stderr_is_still_help(self):
        # argparse-style tools print usage to stderr. The return code is the
        # requirement; which stream carried the text is not.
        probe_capability("kicad-cli",
                         runner=lambda *a, **k: Result("", stderr=HELP))

    def test_a_successful_probe_missing_a_flag_is_still_rejected(self):
        stripped = HELP.replace("[--refill-zones] ", "")
        with self.assertRaises(KicadUnavailable) as ctx:
            probe_capability("kicad-cli",
                             runner=lambda *a, **k: Result(stripped))
        self.assertIn("--refill-zones", str(ctx.exception))
