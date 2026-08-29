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


def run_drc(cli: str, board: str, runner=subprocess.run, parity: bool = True):
    """One DRC pass: violations, unconnected items and parity together.

    Returns (drc, parity_error). parity_error is "" on a normal run and
    kicad-cli's stderr when it could not run the parity tests — which it does
    while still exiting 0 and emitting "schematic_parity": [], so neither its
    exit code nor its output can distinguish "parity found nothing" from
    "parity never ran". The caller turns a non-empty parity_error into a
    blocking finding; the violations in the same report are still valid, so
    this is not an environment failure.

    --refill-zones --save-board is intentional. A stale zone fill is the fault
    this gate exists to catch, and refilling without saving would leave the
    board on disk disagreeing with the package just exported from it.

    --exit-code-violations is deliberately not passed: the gate applies its
    own policy on the parsed JSON, so a non-zero exit here would only obscure
    a successful run that merely found problems.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "drc.json")
        cmd = [cli, "pcb", "drc", "--format", "json", "--severity-all"]
        if parity:
            cmd.append("--schematic-parity")
        cmd += ["--refill-zones", "--save-board", "-o", out, board]
        result = runner(cmd, capture_output=True, text=True)
        stderr = (getattr(result, "stderr", "") or "").strip()
        if getattr(result, "returncode", 0) != 0:
            raise KicadUnavailable(
                f"kicad-cli DRC failed (exit {result.returncode}): {stderr}")
        parity_error = (stderr if parity and
                        any(m in stderr for m in PARITY_FAILED_MARKERS) else "")
        with open(out) as fh:
            return json.load(fh), parity_error
