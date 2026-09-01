# prefab-gate

A pre-fabrication gate for KiCad PCBs. It refuses to produce a fab package
from a board that has not passed verification.

It runs `kicad-cli` DRC with zone refill and schematic parity checking,
classifies every finding as blocking or cosmetic, and — only when nothing
blocks — exports gerbers, drill files, CPL and BOM into a manifested package.

## Subcommands

    python3 scripts/prefab_gate.py check <board.kicad_pcb>
    python3 scripts/prefab_gate.py package <board.kicad_pcb> [--out fab]

Installed as a Claude Code plugin, use `${CLAUDE_PLUGIN_ROOT}/scripts/prefab_gate.py`.

`check` runs DRC and parity, prints a verdict, and exits — no package is
written. It still runs with `--refill-zones --save-board`, so it can rewrite
the board's zone fills; it says so when it does.
`package` does the same, and if the verdict passes, exports the fab package
and writes a `manifest.json` inside it recording the board and schematic
hashes, the kicad-cli version, and every finding (including waived cosmetic
ones).

Both accept `--json` to also print the verdict as JSON, and `--strict` to
treat findings that are normally cosmetic more conservatively.

## Schematic parity

`kicad-cli` exits 0 and writes an empty parity result both when the parity
tests ran and found nothing and when they could not run at all, so the report
alone cannot tell those apart. Its stdout can: `Found <n> schematic parity
issues` is printed whenever the tests ran — including for `n = 0` — and is
absent when they did not. The gate requires that line. Parity has to be
affirmed to have run; it is not inferred from the absence of a failure
message, because a diagnostic's wording is not an API and rewording one would
otherwise turn an unchecked board into a clean pass. Anything else is a
`parity_not_run` finding, which **blocks**.

`kicad-cli pcb drc` derives the schematic from the board's basename and has no
flag to override it, so parity can only ever run against `<board>.kicad_sch`
sitting beside the board. A schematic under any other name must be renamed;
the gate says so rather than reporting a parity result against a file
kicad-cli never opened.

- `--schematic PATH` — the schematic the **BOM** is exported from, for a
  project whose schematic is not named after the board. It cannot redirect
  parity. Refused when a conventional sibling exists and differs, which would
  pair a BOM from one design with a parity result from another.
- `--no-parity` — accept a PCB-only check. The finding is still recorded, as
  cosmetic, in both the report and the manifest. `--strict` overrides it.

The manifest records whether parity ran, against which schematic, or why it
did not.

## What was checked is what gets packaged

The board and the schematic are hashed once the DRC is done with them — after
the zone refill, which is the last thing entitled to rewrite the board — and
required to still hash the same before the exports run and again before the
package is published. An edit landing in that window would otherwise produce
a package that looked reproducible while describing a board no check had seen.

The manifest carries `checked_sha256` beside `sha256` for both files. They are
equal in anything published, by construction; recording the pair is what lets
a reader confirm it rather than take it on faith. A mismatch is exit `3` and
nothing is published — the board may well be fine, but the gate can no longer
say so.

The report is required to be complete before it is judged, too. A missing
section is not a section that found nothing, so an absent `violations`,
`unconnected_items` or (when parity was requested) `schematic_parity` is exit
`3`, never a clean verdict.

## Exit codes

- `0` — clean (and, for `package`, packaged)
- `2` — blocked; at least one blocking finding, no files written. This includes
  a board kicad-cli runs but cannot load (a truncated file, items on undefined
  layers): that is a `board_unreadable` finding about the board, not a broken
  install, so it belongs here rather than in `3`.
- `3` — the gate could not run, or could not vouch for what it checked:
  kicad-cli missing, unreachable, failing its own `--help`, or too old; the
  board missing; `--schematic` pointing at nothing; DRC output that is
  unreadable or missing sections; an input that changed after it was verified;
  or a usage error.
  Usage errors take `3` rather than argparse's default `2` so CI can tell a
  mistyped flag from a board that failed verification.

## Installing as a plugin

    /plugin marketplace add danielboston38/linktovideo
    /plugin install prefab-gate@prefab-gate

Plugin metadata lives here in `prefab-gate/.claude-plugin/plugin.json`. The
marketplace manifest is at the **repository root**, in
`.claude-plugin/marketplace.json`, pointing back at this directory with
`"source": "./prefab-gate"` — a marketplace is added by bare repo reference,
so the loader looks only at the root and finds nothing in a subdirectory.

## Licence

The plugin is MIT — see `LICENSE` in this directory. The hardware in the rest
of the repository is CERN-OHL-S-2.0 under the root `LICENSE.txt`. Separate
works, separate terms.

## kicad-cli

Requires `kicad-cli` on `PATH`, or point `KICAD_CLI` at its full path, e.g.
on macOS:

    export KICAD_CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli

DRC runs with `--refill-zones --save-board`, which can rewrite zone fills in
the board file in place; the gate hashes the board before and after and
notes it when this happens.

## Tests

Stdlib `unittest` only — no pytest, no third-party dependencies.

    cd scripts && PYTHONPATH=. python3 -m unittest discover -s ../tests -p 'test_*.py' -v
