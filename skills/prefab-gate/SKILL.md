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
`3` the gate could not run (kicad-cli missing or too old, schematic missing,
board path wrong, or a usage error). Only `2` is a verdict about the board.

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

The gate refuses to run at all if the board's `.kicad_sch` is missing, because
kicad-cli reports an empty parity result with exit 0 in that case — a clean
verdict that means nothing.

## What it does not do

It does not replace design review. It checks that the board you have is
internally consistent and manufacturable, not that it is the board you meant.
