"""Atomic fab-package export.

Built in a staging directory inside the output directory and published with
os.replace only on success, so a failure never leaves something that looks
shippable. Staging lives inside out_dir (not the system temp dir) so the
final rename is same-filesystem and genuinely atomic.
"""
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

from gate.kicad import KicadUnavailable


def schematic_for(board: str) -> str:
    return os.path.splitext(board)[0] + ".kicad_sch"


def _run(runner, cmd):
    result = runner(cmd, capture_output=True, text=True)
    if getattr(result, "returncode", 0) != 0:
        raise KicadUnavailable(
            f"{' '.join(cmd[1:4])} failed (exit {result.returncode}): "
            f"{(getattr(result, 'stderr', '') or '').strip()}")


def export_package(cli: str, board: str, out_dir: str, runner=subprocess.run) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    final = os.path.join(out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".staging-", dir=out_dir)
    try:
        _run(runner, [cli, "pcb", "export", "gerbers", "--board-plot-params",
                      "-o", os.path.join(staging, "gerbers"), board])
        _run(runner, [cli, "pcb", "export", "drill", "--format", "excellon",
                      "--excellon-units", "mm", "--generate-map",
                      "-o", os.path.join(staging, "drill"), board])
        _run(runner, [cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                      "--side", "both", "-o", os.path.join(staging, "cpl.csv"), board])
        _run(runner, [cli, "sch", "export", "bom", "--group-by", "",
                      "--fields", "Reference,Value,Footprint,Manufacturer,MPN,LCSC,Datasheet",
                      "-o", os.path.join(staging, "bom.csv"), schematic_for(board)])
        os.replace(staging, final)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
