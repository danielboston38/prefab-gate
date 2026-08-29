"""The package receipt.

Answers, months later: what was sent, from which board state, and what did the
gate knowingly allow past?
"""
import hashlib
import os
from dataclasses import asdict
from datetime import datetime, timezone


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(board: str, cli_version: str, verdict, files) -> dict:
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "kicad_cli_version": cli_version,
        "board": {"path": os.path.basename(board), "sha256": sha256(board)},
        "verdict": {
            "passed": verdict.passed,
            "blocking": [asdict(f) for f in verdict.blocking],
            "cosmetic": [asdict(f) for f in verdict.cosmetic],
        },
        "files": [{"name": os.path.basename(p), "sha256": sha256(p)} for p in sorted(files)],
    }
