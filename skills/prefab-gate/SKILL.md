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
`3` the gate could not run (kicad-cli missing or too old, board path wrong,
`--schematic` pointing at nothing, or a usage error). Only `2` is a verdict
about the board — including a board kicad-cli cannot load at all, which is a
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

kicad-cli reports an empty parity result **and exits 0** when it cannot load the
schematic. So "no parity issues" and "parity never ran" look identical, and the
gate treats the second as a blocking `parity_not_run` finding.

The gate looks for the schematic beside the board under the board's own name,
then for a single `*.kicad_sch` in that directory. If it finds neither — or
finds several and will not guess — you get `parity_not_run`, blocking, naming
what it looked for.

- `--schematic PATH` says where the schematic is.
- `--no-parity` accepts a PCB-only check. The same finding is still recorded, as
  **cosmetic**, so the report and the manifest both show that parity was
  skipped. `--strict` overrides the waiver.

One caveat worth knowing: `kicad-cli pcb drc` derives the schematic from the
board's basename and has no flag to override it. A schematic under a different
name must be **renamed** to match the board for parity to actually run;
`--schematic` will get you past the gate's own search, but kicad-cli will then
fail to load it and you will get `parity_not_run` anyway — correctly.

## What it does not do

It does not replace design review. It checks that the board you have is
internally consistent and manufacturable, not that it is the board you meant.
