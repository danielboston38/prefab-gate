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


class GateArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; here 2 means "blocked by findings".

    A CI job cannot tell a typo'd flag from a board that failed verification if
    both exit 2. Usage errors are an environment problem — the gate could not
    run — so they take exit 3 along with everything else in that class. The
    spec fixes the contract at 0/2/3; a fourth code is not ours to invent.
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(3)


def _build_parser():
    parser = GateArgumentParser(prog="prefab_gate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True,
                                parser_class=GateArgumentParser)
    for name in ("check", "package"):
        p = sub.add_parser(name)
        p.add_argument("board")
        if name == "package":
            # `check` produces no package, so an --out it silently ignored was
            # a promise it could not keep.
            p.add_argument("--out", default="fab")
        p.add_argument("--json", action="store_true")
        p.add_argument("--strict", action="store_true")
    return parser


def _gate(args, d) -> int:
    cli = d["locate_cli"]()
    d["probe_capability"](cli)
    # --refill-zones --save-board can rewrite the board. Hash it either side so
    # the resulting git diff is expected rather than mysterious.
    before = d["board_hash"](args.board)
    drc = d["run_drc"](cli, args.board)
    if d["board_hash"](args.board) != before:
        print(f"Note: refilling updated the zone fills in {args.board} — "
              "the board file has been modified and should be committed.\n")

    verdict = classify(drc, strict=args.strict)
    print(render_text(verdict))

    code = 0 if verdict.passed else 2
    if verdict.passed and args.command == "package":
        package = d["export_package"](cli, args.board, args.out)
        files = [os.path.join(root, f) for root, _, fs in os.walk(package) for f in fs]
        manifest = build_manifest(args.board, d["cli_version"](cli), verdict, files,
                                  package)
        with open(os.path.join(package, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        print(f"\nPackage written to {package}")

    if args.json:
        print()
        print(render_json(verdict))
    return code


def main(argv=None, deps=None) -> int:
    d = dict(DEFAULT_DEPS)
    d.update(deps or {})

    args = _build_parser().parse_args(argv)

    if not os.path.isfile(args.board):
        print(f"board not found: {args.board}\n"
              "Pass the path to a .kicad_pcb file. The gate cannot verify a board "
              "it cannot read.")
        return 3

    try:
        return _gate(args, d)
    except KicadUnavailable as exc:
        print(str(exc))
        return 3
    except json.JSONDecodeError as exc:
        # kicad-cli wrote something that is not the DRC JSON the gate parses.
        print(f"kicad-cli's DRC output could not be parsed as JSON: {exc}\n"
              "The gate cannot judge a board it cannot read a report for.")
        return 3
    except OSError as exc:
        # Unreadable board, unwritable output directory, a manifest that could
        # not be written. All "the gate could not run", never a silent pass.
        print(f"the gate could not complete: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
