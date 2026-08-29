#!/usr/bin/env python3
"""Pre-fab gate: no fab package without a passing check."""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate.classify import classify                      # noqa: E402
from gate.export import (export_package, locate_schematic,  # noqa: E402
                         schematic_candidates, schematic_for)
from gate.kicad import KicadUnavailable, locate_cli, probe_capability, run_drc  # noqa: E402
from gate.manifest import build_manifest, sha256        # noqa: E402
from gate.model import Parity                           # noqa: E402
from gate.report import render_json, render_text        # noqa: E402


def _cli_version(cli):
    result = subprocess.run([cli, "version"], capture_output=True, text=True)
    return (result.stdout or "").strip()


DEFAULT_DEPS = {"locate_cli": locate_cli, "probe_capability": probe_capability,
                "run_drc": run_drc, "export_package": export_package,
                "cli_version": _cli_version, "board_hash": sha256,
                "locate_schematic": locate_schematic,
                "schematic_candidates": schematic_candidates}


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
        p.add_argument("--schematic", default=None, metavar="PATH",
                       help="schematic to check parity against, when it is not "
                            "beside the board under the board's own name")
        p.add_argument("--no-parity", action="store_true",
                       help="skip schematic parity (for a PCB-only design). "
                            "Recorded as a cosmetic finding, never silently.")
    return parser


def _resolve_parity(args, d) -> Parity:
    """Decide whether parity can run, and record why when it cannot.

    Never a silent skip: every branch that does not run parity carries a reason
    that ends up in the report and the manifest.
    """
    if args.no_parity:
        return Parity(ran=False, waived=True, reason=(
            "skipped at your request (--no-parity); the board was not compared "
            "against any schematic"))
    schematic = d["locate_schematic"](args.board, args.schematic)
    if schematic is not None:
        return Parity(ran=True, schematic=schematic)

    conventional = schematic_for(args.board)
    candidates = d["schematic_candidates"](args.board)
    if not candidates:
        where = f"no .kicad_sch beside the board (looked for {conventional})"
    else:
        names = ", ".join(os.path.basename(c) for c in candidates)
        where = (f"{len(candidates)} schematics beside the board and none named "
                 f"{os.path.basename(conventional)}, so the gate will not guess "
                 f"which one is the design: {names}")
    return Parity(ran=False, reason=(
        f"parity could not run: {where}. Point at one with --schematic, or "
        "accept a PCB-only check with --no-parity. Note that kicad-cli derives "
        "the schematic from the board's basename and cannot be told otherwise, "
        f"so a schematic under any other name must be renamed to "
        f"{os.path.basename(conventional)} for parity to actually run."))


def _gate(args, d) -> int:
    cli = d["locate_cli"]()
    d["probe_capability"](cli)
    # --refill-zones --save-board can rewrite the board. Hash it either side so
    # the resulting git diff is expected rather than mysterious.
    parity = _resolve_parity(args, d)
    before = d["board_hash"](args.board)
    drc, parity_error = d["run_drc"](cli, args.board, parity=parity.ran)
    if parity.ran and parity_error:
        # kicad-cli exits 0 and emits an empty parity list when it could not
        # load the schematic. The violations in the same report are still
        # valid; it is the parity half that did not run.
        parity = Parity(ran=False, schematic=parity.schematic, reason=(
            "kicad-cli could not run the parity tests against "
            f"{parity.schematic}, and exited 0 reporting no parity issues "
            "anyway — its exit code cannot be trusted here. It said: "
            f"{parity_error.strip()}"))
    if d["board_hash"](args.board) != before:
        print(f"Note: refilling updated the zone fills in {args.board} — "
              "the board file has been modified and should be committed.\n")

    verdict = classify(drc, strict=args.strict, parity=parity)
    print(render_text(verdict))

    code = 0 if verdict.passed else 2
    if verdict.passed and args.command == "package":
        def write_manifest(staging):
            # Written into the staging directory, so the one os.replace inside
            # export_package publishes the package and its receipt together.
            # Writing it afterwards left a window in which a complete-looking
            # fab package existed with no record of what the gate let past.
            files = [os.path.join(root, f)
                     for root, _, fs in os.walk(staging) for f in fs]
            manifest = build_manifest(args.board, d["cli_version"](cli), verdict,
                                      files, staging, strict=args.strict,
                                      out_dir=args.out)
            with open(os.path.join(staging, "manifest.json"), "w") as fh:
                json.dump(manifest, fh, indent=2)

        package = d["export_package"](cli, args.board, args.out,
                                      on_staged=write_manifest)
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
