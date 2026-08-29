"""Locating and driving kicad-cli."""
import os
import shutil
import subprocess

REQUIRED_FLAGS = ("--format", "--schematic-parity", "--refill-zones")

# Checked in order, after $KICAD_CLI and $PATH.
FALLBACK_PATHS = (
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
)


class KicadUnavailable(Exception):
    """kicad-cli is missing, or too old to do what the gate needs."""


def locate_cli(env=None, which=shutil.which, exists=os.path.exists) -> str:
    env = os.environ if env is None else env
    override = env.get("KICAD_CLI")
    if override:
        if exists(override):
            return override
        raise KicadUnavailable(f"KICAD_CLI is set to {override!r}, which does not exist")
    found = which("kicad-cli")
    if found:
        return found
    for candidate in FALLBACK_PATHS:
        if exists(candidate):
            return candidate
    raise KicadUnavailable(
        "kicad-cli not found. Install KiCad 8 or newer, then either put kicad-cli on "
        "your PATH or set KICAD_CLI to its full path.\n"
        "  macOS:   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli\n"
        "  Linux:   apt install kicad  (or the KiCad AppImage)\n"
        "  Windows: C:\\Program Files\\KiCad\\<version>\\bin\\kicad-cli.exe")


def probe_capability(cli: str, runner=subprocess.run) -> None:
    result = runner([cli, "pcb", "drc", "--help"], capture_output=True, text=True)
    help_text = getattr(result, "stdout", "") or ""
    missing = [f for f in REQUIRED_FLAGS if f not in help_text]
    if missing:
        raise KicadUnavailable(
            f"{cli} does not support {', '.join(missing)}. The gate needs KiCad 8 or "
            "newer; upgrade KiCad or point KICAD_CLI at a newer install.")
