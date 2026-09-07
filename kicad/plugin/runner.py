"""Run the gate against a staged copy and return something a dialog can render.

The gate is invoked through prefab_gate.main so that the plugin and the command
line share one implementation of the policy. Under --json the gate puts only
the verdict on stdout and every other message on stderr, which makes parsing
stdout a supported contract rather than screen-scraping.
"""
import collections
import hashlib
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

# Relative: PCM installs this package under a directory of its own choosing, so
# the package name is not "plugin" once installed. An absolute import works in
# the repo and breaks in the field.
from . import staging

Result = collections.namedtuple(
    "Result", "code verdict messages zones_were_stale")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _gate_main():
    """Import the gate lazily, so this module imports without it on the path.

    Two layouts have to work. Installed, PCM flattens everything into one
    directory, so prefab_gate.py is a sibling. In the repo it lives at
    ../../scripts. Nearest first, and neither is assumed.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here,
                      os.path.normpath(os.path.join(here, "..", "..", "scripts"))):
        if os.path.isfile(os.path.join(candidate, "prefab_gate.py")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            break
    import prefab_gate
    return prefab_gate.main


def run_check(board_path, main=None, hasher=None):
    """Stage the project, check the copy, and report what happened.

    Stale zone fills are detected by hashing the staged board either side of
    the run rather than by reading the gate's note. The gate declines to key on
    message wording and so does this; its note also says the file "should be
    committed" while naming a path inside a temporary directory, which is true
    for the CLI and meaningless in a dialog.
    """
    main = main or _gate_main()
    hasher = hasher or _sha256

    with tempfile.TemporaryDirectory(prefix="prefab-gate-") as staged_dir:
        board = staging.stage(board_path, staged_dir)
        before = hasher(board)

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["check", board, "--json"])

        stale = hasher(board) != before

    raw = out.getvalue().strip()
    verdict = None
    if raw:
        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError:
            verdict = None
    return Result(code=code, verdict=verdict,
                  messages=err.getvalue().strip(), zones_were_stale=stale)
