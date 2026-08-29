# prefab-gate

A pre-fabrication gate for KiCad PCBs. It refuses to produce a fab package
from a board that has not passed verification.

It runs `kicad-cli` DRC with zone refill and schematic parity checking,
classifies every finding as blocking or cosmetic, and — only when nothing
blocks — exports gerbers, drill files, CPL and BOM into a manifested package.

## Subcommands

    python3 scripts/prefab_gate.py check <board.kicad_pcb>
    python3 scripts/prefab_gate.py package <board.kicad_pcb> [--out fab]

`check` runs DRC and parity, prints a verdict, and exits — no files written.
`package` does the same, and if the verdict passes, exports the fab package
and writes a `manifest.json` alongside it recording the board hash, the
kicad-cli version, and every finding (including waived cosmetic ones).

Both accept `--json` to also print the verdict as JSON, and `--strict` to
treat findings that are normally cosmetic more conservatively.

## Exit codes

- `0` — clean (and, for `package`, packaged)
- `2` — blocked; at least one blocking finding, no files written
- `3` — kicad-cli missing, unreachable, or too old

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
