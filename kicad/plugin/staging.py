"""Assemble the smallest project copy kicad-cli DRC needs.

DRC runs with --refill-zones --save-board, which rewrites the board in place.
Run from a plugin that would be the file open in the editor, so the gate is
pointed at a copy instead. This module decides what goes into that copy.

It is a whitelist, not a directory copy. 3D models are excluded because DRC
never loads them, and they are what makes a KiCad project large — a real
project measured well under a megabyte staged against a 79 MB directory.

Everything on the list is here because leaving it out changes the verdict:

  .kicad_pro     DRC severities, which decide blocking versus cosmetic
  .kicad_dru     custom rules
  *.kicad_sch    schematic parity, every sheet of it
  fp-lib-table   without it the footprint-vs-library checks cannot run, and
  sym-lib-table  kicad-cli reports the missing library as a finding of its own

and project-local libraries the tables point at with ${KIPRJMOD}. Dropping the
tables was measured: it invented two lib_footprint_issues findings that do not
exist in the real project. They were cosmetic there, but a project that raises
that check to error would have had a good board blocked by its own staging.
"""
import glob
import os
import re
import shutil

LIB_TABLES = ("fp-lib-table", "sym-lib-table")

# Library entries are project-local when their URI is ${KIPRJMOD}-relative.
# Anything else points outside the project and is left to resolve normally.
_PROJECT_URI = re.compile(r'\(uri\s+"\$\{KIPRJMOD\}/([^"]+)"')


class StagingError(Exception):
    """There is no board file to stage."""


def _local_library_paths(project):
    """Project-local paths named by the library tables, as absolute paths."""
    paths = []
    for table in LIB_TABLES:
        table_path = os.path.join(project, table)
        if not os.path.isfile(table_path):
            continue
        with open(table_path, errors="replace") as handle:
            text = handle.read()
        for relative in _PROJECT_URI.findall(text):
            candidate = os.path.normpath(os.path.join(project, relative))
            # A table may name anything; only copy what is inside the project.
            if os.path.commonpath([candidate, project]) != project:
                continue
            if os.path.exists(candidate):
                paths.append(candidate)
    return paths


def _expand(path):
    """A file yields itself; a directory yields the files beneath it."""
    if os.path.isfile(path):
        return [path]
    return [os.path.join(base, name)
            for base, _, names in os.walk(path)
            for name in sorted(names)]


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
    for table in LIB_TABLES:
        table_path = os.path.join(project, table)
        if os.path.isfile(table_path):
            files.append(table_path)
    for library in _local_library_paths(project):
        files.extend(_expand(library))

    seen = set()
    unique = []
    for path in files:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def stage(board_path, dest):
    """Copy the collected files into dest; return the staged board's path.

    Layout is preserved relative to the project directory, not flattened: the
    board and its sidecars land at the top, and a project-local library keeps
    its own folder so the copied fp-lib-table still resolves. kicad-cli also
    derives the schematic from the board's basename and has no flag to
    override it, so the names cannot change either.
    """
    files = collect(board_path)
    project = os.path.dirname(files[0])
    for source in files:
        relative = os.path.relpath(source, project)
        target = os.path.join(dest, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    return os.path.join(dest, os.path.basename(files[0]))
