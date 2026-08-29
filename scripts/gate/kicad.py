"""Locating and driving kicad-cli."""
import glob
import re
import json
import os
import shutil
import subprocess
import tempfile

# Every flag run_drc passes unconditionally. Probing a subset would let the gate
# start on a kicad-cli that then fails on the first real invocation.
REQUIRED_FLAGS = ("--format", "--schematic-parity", "--refill-zones",
                  "--save-board", "--severity-all")

# kicad-cli prints these to stderr and *still exits 0* when it cannot load the
# schematic, emitting "schematic_parity": []. A board whose schematic is
# missing, renamed or unannotated would otherwise sail through with a clean
# parity result and no record that parity never ran — the exact fault class
# this gate exists to catch. Its exit code cannot be trusted here.
PARITY_FAILED_MARKERS = (
    "Failed to fetch schematic netlist",
    "require a fully annotated schematic",
)

# Checked in order, after $KICAD_CLI and $PATH.
FALLBACK_PATHS = (
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
)

# KiCad on Windows installs under a version-numbered directory, so no single
# path is right across releases. Globbed and newest-first rather than pinned.
WINDOWS_GLOBS = (
    r"C:\Program Files\KiCad\*\bin\kicad-cli.exe",
    r"C:\Program Files (x86)\KiCad\*\bin\kicad-cli.exe",
)


def _windows_version_key(path: str):
    """Sort globbed Windows installs newest-first, numerically not lexically.

    Plain string sorting puts KiCad 9.0 above 10.0, which is exactly backwards.
    """
    match = re.search(r"[\\/]KiCad[\\/]([0-9][0-9.]*)[\\/]", path)
    return tuple(int(n) for n in match.group(1).split(".") if n.isdigit()) if match else ()


class KicadUnavailable(Exception):
    """kicad-cli is missing, too old, or unable to do what the gate needs."""


def schematic_for(board: str) -> str:
    """The schematic KiCad pairs with this board: same stem, .kicad_sch."""
    return os.path.splitext(board)[0] + ".kicad_sch"


def locate_cli(env=None, which=shutil.which, exists=os.path.exists,
               globber=glob.glob) -> str:
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
    for pattern in WINDOWS_GLOBS:
        for candidate in sorted(globber(pattern), key=_windows_version_key,
                                reverse=True):
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


def run_drc(cli: str, board: str, runner=subprocess.run, exists=os.path.exists) -> dict:
    """One DRC pass: violations, unconnected items and parity together.

    --refill-zones --save-board is intentional. A stale zone fill is the fault
    this gate exists to catch, and refilling without saving would leave the
    board on disk disagreeing with the package just exported from it.

    --exit-code-violations is deliberately not passed: the gate applies its
    own policy on the parsed JSON, so a non-zero exit here would only obscure
    a successful run that merely found problems.

    Schematic parity fails *closed*, both before and after the run: kicad-cli
    reports an empty parity list and exit 0 when it cannot load the schematic,
    so neither its exit code nor its output can be used to tell "parity found
    nothing" from "parity never ran".
    """
    schematic = schematic_for(board)
    if not exists(schematic):
        raise KicadUnavailable(
            f"schematic not found at {schematic}.\n"
            "Schematic parity is a core check of this gate and cannot run without "
            "it, and kicad-cli reports an empty parity result with exit 0 rather "
            "than an error — so a missing schematic would look like a clean board. "
            "Keep the schematic beside the board under the same base name.")

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "drc.json")
        result = runner([cli, "pcb", "drc", "--format", "json", "--severity-all",
                         "--schematic-parity", "--refill-zones", "--save-board",
                         "-o", out, board],
                        capture_output=True, text=True)
        stderr = (getattr(result, "stderr", "") or "").strip()
        if getattr(result, "returncode", 0) != 0:
            raise KicadUnavailable(
                f"kicad-cli DRC failed (exit {result.returncode}): {stderr}")
        if any(marker in stderr for marker in PARITY_FAILED_MARKERS):
            raise KicadUnavailable(
                "kicad-cli could not run the schematic parity tests, yet exited "
                f"{getattr(result, 'returncode', 0)} and reported no parity issues. "
                "The gate will not treat that as a pass. kicad-cli said:\n"
                f"{stderr}")
        with open(out) as fh:
            return json.load(fh)
