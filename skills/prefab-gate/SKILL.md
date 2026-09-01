---
name: prefab-gate
description: Use before ordering any KiCad PCB - verifies a board with DRC, zone refill and schematic parity, and refuses to export a fab package if anything blocking is found. Triggers on "order this board", "generate gerbers", "fab package", "is this ready to fab", "send to JLCPCB/PCBWay".
---

# Pre-fab gate

Never hand-generate gerbers. Run:

    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/prefab_gate.py package <board.kicad_pcb>

`${CLAUDE_PLUGIN_ROOT}` is required: the gate ships with the plugin, not with
the user's project, so a relative `scripts/...` path will not resolve from the
directory the board lives in.

Exit codes: `0` clean and packaged · `2` blocked by findings, no files written ·
`3` the gate could not run, or could not vouch for what it checked (kicad-cli
missing, too old or failing its own `--help`; board path wrong; `--schematic`
pointing at nothing; a DRC report missing sections; an input that changed after
it was verified; or a usage error). Only `2` is a verdict about the board — including a board kicad-cli cannot load at all, which is a
`board_unreadable` finding rather than an environment failure.

`--json` puts the verdict document on stdout and nothing else; the zone-refill
note and the package path go to stderr, so stdout can be piped to a parser.

Use `check` instead of `package` to verify without producing a package. `check`
still runs with `--refill-zones --save-board`, so it may rewrite the board's
zone fills — that is the point, and it says so when it happens.

## Reading a verdict

Blocking findings stop the export. Cosmetic ones are listed, waved through, and
recorded in the package manifest so you can see later what shipped despite them.

An **unrecognised parity description always blocks** — if you see one, it means
KiCad reworded a message and the classifier needs the new string added. Do not
work around it by exporting by hand. An unrecognised DRC *severity* blocks for
the same reason.

A `Not checked:` line reports findings excluded in the project file and check
categories the project disables. Read it: a PASSED verdict only covers what was
switched on.

## When parity cannot run

kicad-cli reports an empty parity result **and exits 0** whether the parity
tests ran and found nothing or never ran at all, so those look identical in the
report. They differ on stdout: `Found <n> schematic parity issues` appears
whenever the tests ran, `n = 0` included, and is missing when they did not. The
gate requires that line — parity is proven to have run, not assumed from the
absence of an error — and anything else is a blocking `parity_not_run` finding.

Parity can only run against `<board>.kicad_sch` beside the board, because
`kicad-cli pcb drc` derives the name from the board and takes no override. A
schematic under any other name has to be renamed. `--schematic` chooses the
schematic the **BOM** comes from; it cannot redirect parity, and the gate
reports `parity_not_run` rather than naming a file kicad-cli never opened.

For the BOM the gate is less strict: it takes the schematic beside the board
under the board's own name, else a single `*.kicad_sch` in that directory. When
that is not the conventional name you get a BOM but no parity, said plainly.
Several candidates and it will not guess at all.

- `--schematic PATH` chooses the BOM's schematic. Refused when a conventional
  sibling exists and differs — that would ship a BOM from one design with a
  parity result from another.
- `--no-parity` accepts a PCB-only check. The same finding is still recorded, as
  **cosmetic**, so the report and the manifest both show that parity was
  skipped. `--strict` overrides the waiver.

## The package is what was checked

The board and schematic are hashed after the DRC and refill are done with them,
and must still hash the same before the exports run and before the package is
published. Editing either mid-run gets you exit `3` and no package, rather than
a package describing a board nothing verified. The manifest carries
`checked_sha256` beside `sha256` for both so a reader can confirm it.

## What it does not do

It does not replace design review. It checks that the board you have is
internally consistent and manufacturable, not that it is the board you meant.
