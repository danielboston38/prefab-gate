import unittest
from gate.kicad import locate_cli, probe_capability, KicadUnavailable

# Trimmed from the real `kicad-cli pcb drc --help` on KiCad 10.
HELP = ("Usage: pcb drc [--help] [--output OUTPUT_FILE] [--format FORMAT] "
        "[--schematic-parity] [--severity-all] [--exit-code-violations] "
        "[--refill-zones] [--save-board] INPUT_FILE")


class Result:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


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
