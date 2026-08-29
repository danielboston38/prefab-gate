"""The package receipt.

Answers, months later: what was sent, from which board state, under which
policy, and what did the gate knowingly allow past?
"""
import hashlib
import os
from datetime import datetime, timezone

from gate.report import verdict_json


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(board: str, cli_version: str, verdict, files, package_root: str,
                   *, strict: bool, out_dir: str) -> dict:
    """Build the receipt. Every argument is required on purpose.

    package_root is not optional: without it file names fall back to bare
    basenames, so two gerbers from different subdirectories collide and the
    receipt stops identifying what it hashed.

    strict and out_dir are not optional either: two runs under different
    policies would otherwise produce indistinguishable manifests, and "was
    --strict on?" is exactly the question a receipt exists to answer.
    """
    def name_for(p: str) -> str:
        return os.path.relpath(p, package_root)

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "kicad_cli_version": cli_version,
        "policy": {"strict": bool(strict), "out_dir": out_dir},
        "board": {"path": os.path.basename(board), "sha256": sha256(board)},
        # Includes what was excluded and which checks the project file
        # disables: "PASSED" is only meaningful alongside its own coverage.
        "verdict": verdict_json(verdict),
        "files": [{"name": name_for(p), "sha256": sha256(p)} for p in sorted(files)],
    }
