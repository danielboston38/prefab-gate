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
and writes a `manifest.json` alongside it recording the board hash, the
kicad-cli version, and every finding (including waived cosmetic ones).

Both accept `--json` to also print the verdict as JSON, and `--strict` to
treat findings that are normally cosmetic more conservatively.

## Schematic parity

`kicad-cli` exits 0 and reports an empty parity result when it cannot load the
schematic, so "clean" and "never ran" are indistinguishable from its output
alone. The gate closes that hole with a `parity_not_run` finding.

It locates the schematic beside the board under the board's own name, else a
sole `*.kicad_sch` in that directory. Failing that — including when several
candidates make the choice ambiguous — `parity_not_run` **blocks**, naming what
was tried.

- `--schematic PATH` — say where the schematic is.
- `--no-parity` — accept a PCB-only check. The finding is still recorded, as
  cosmetic, in both the report and the manifest. `--strict` overrides it.

`kicad-cli pcb drc` derives the schematic from the board's basename with no way
to override it, so a differently-named schematic must be renamed for parity to
actually run. The manifest records whether parity ran, against which schematic,
or why it did not.

## Exit codes

- `0` — clean (and, for `package`, packaged)
- `2` — blocked; at least one blocking finding, no files written. This includes
  a board kicad-cli runs but cannot load (a truncated file, items on undefined
  layers): that is a `board_unreadable` finding about the board, not a broken
  install, so it belongs here rather than in `3`.
- `3` — the gate could not run: kicad-cli missing, unreachable or too old, the
  board missing, `--schematic` pointing at nothing, unreadable DRC output, or a
  usage error.
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
