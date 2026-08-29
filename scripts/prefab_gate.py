#!/usr/bin/env python3
"""Pre-fab gate: no fab package without a passing check."""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate.classify import classify                      # noqa: E402
from gate.export import export_package                  # noqa: E402
from gate.kicad import KicadUnavailable, locate_cli, probe_capability, run_drc  # noqa: E402
from gate.manifest import build_manifest, sha256        # noqa: E402
from gate.report import render_json, render_text        # noqa: E402


def _cli_version(cli):
    result = subprocess.run([cli, "version"], capture_output=True, text=True)
    return (result.stdout or "").strip()


DEFAULT_DEPS = {"locate_cli": locate_cli, "probe_capability": probe_capability,
                "run_drc": run_drc, "export_package": export_package,
                "cli_version": _cli_version, "board_hash": sha256}


def main(argv=None, deps=None) -> int:
    d = dict(DEFAULT_DEPS)
    d.update(deps or {})

    parser = argparse.ArgumentParser(prog="prefab_gate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "package"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--out", default="fab")
        p.add_argument("--json", action="store_true")
        p.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    try:
        cli = d["locate_cli"]()
        d["probe_capability"](cli)
        # --refill-zones --save-board can rewrite the board. Hash it either side so
        # the resulting git diff is expected rather than mysterious.
        before = d["board_hash"](args.board)
        drc = d["run_drc"](cli, args.board)
        if d["board_hash"](args.board) != before:
            print(f"Note: refilling updated the zone fills in {args.board} — "
                  "the board file has been modified and should be committed.\n")
    except KicadUnavailable as exc:
        print(str(exc))
        return 3

    verdict = classify(drc, strict=args.strict)
    print(render_text(verdict))

    code = 0 if verdict.passed else 2
    if verdict.passed and args.command == "package":
        try:
            package = d["export_package"](cli, args.board, args.out)
        except KicadUnavailable as exc:
            print(str(exc))
            return 3
        # export_package guarantees this directory exists on success; a test
        # double for it may not touch the real filesystem at all, so guard
        # rather than assume.
        if os.path.isdir(package):
            files = [os.path.join(root, f) for root, _, fs in os.walk(package) for f in fs]
            manifest = build_manifest(args.board, d["cli_version"](cli), verdict, files, package)
            with open(os.path.join(package, "manifest.json"), "w") as fh:
                json.dump(manifest, fh, indent=2)
        print(f"\nPackage written to {package}")

    if args.json:
        print()
        print(render_json(verdict))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
