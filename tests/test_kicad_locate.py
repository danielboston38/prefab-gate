import unittest
from gate.kicad import locate_cli, probe_capability, KicadUnavailable

HELP = ("Usage: pcb drc [--help] [--output OUTPUT_FILE] [--format FORMAT] "
        "[--schematic-parity] [--severity-all] [--refill-zones] INPUT_FILE")


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
            locate_cli(env={}, which=lambda n: None, exists=lambda p: False)
        self.assertIn("kicad-cli", str(ctx.exception))

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
