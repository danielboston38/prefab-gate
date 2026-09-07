"""Assemble the smallest project copy kicad-cli DRC needs.

DRC runs with --refill-zones --save-board, which rewrites the board in place.
Run from a plugin that would be the file open in the editor, so the gate is
pointed at a copy instead. This module decides what goes into that copy.

It is a whitelist, not a directory copy. 3D models and footprint or symbol
libraries are excluded because footprints are embedded in the .kicad_pcb and
symbols in the .kicad_sch — DRC never reads the libraries, and they are what
makes a KiCad project large. A real project measured 0.41 MB staged against a
79 MB directory.

.kicad_pro and .kicad_dru are not optional extras. DRC severities live in the
first and custom rules in the second; a copy without them falls back to
defaults and returns a verdict about a design the user does not have — a
failure that looks exactly like success.
"""
import glob
import os
import shutil


class StagingError(Exception):
    """There is no board file to stage."""


def collect(board_path):
    """Absolute paths of every file DRC needs. The board is always first.

    A missing schematic is deliberately not an error here. The gate treats it
    as a blocking parity_not_run finding with a better explanation than this
    module could give, and duplicating the check would put the same policy in
    two places.
    """
    if not board_path:
        raise StagingError(
            "This board has not been saved yet, so there is no file to check. "
            "Save it and run the gate again.")
    board = os.path.abspath(board_path)
    if not os.path.isfile(board):
        raise StagingError(f"No board file at {board}.")

    project = os.path.dirname(board)
    stem = os.path.splitext(os.path.basename(board))[0]

    files = [board]
    files.extend(sorted(glob.glob(os.path.join(project, "*.kicad_sch"))))
    for extension in (".kicad_pro", ".kicad_dru"):
        sidecar = os.path.join(project, stem + extension)
        if os.path.isfile(sidecar):
            files.append(sidecar)
    return files


def stage(board_path, dest):
    """Copy the collected files into dest; return the staged board's path.

    Basenames are preserved because kicad-cli derives the schematic from the
    board's basename and has no flag to override it.
    """
    files = collect(board_path)
    for source in files:
        shutil.copy2(source, os.path.join(dest, os.path.basename(source)))
    return os.path.join(dest, os.path.basename(files[0]))
