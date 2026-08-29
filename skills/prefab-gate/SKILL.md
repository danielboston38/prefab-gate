---
name: prefab-gate
description: Use before ordering any KiCad PCB - verifies a board with DRC, zone refill and schematic parity, and refuses to export a fab package if anything blocking is found. Triggers on "order this board", "generate gerbers", "fab package", "is this ready to fab", "send to JLCPCB/PCBWay".
---

# Pre-fab gate

Never hand-generate gerbers. Run:

    python3 scripts/prefab_gate.py package <board.kicad_pcb>

Exit codes: `0` clean and packaged · `2` blocked, no files written · `3` kicad-cli missing or too old.

Use `check` instead of `package` to verify without producing files.

## Reading a verdict

Blocking findings stop the export. Cosmetic ones are listed, waved through, and
recorded in the package manifest so you can see later what shipped despite them.

An **unrecognised parity description always blocks** — if you see one, it means
KiCad reworded a message and the classifier needs the new string added. Do not
work around it by exporting by hand.

## What it does not do

It does not replace design review. It checks that the board you have is
internally consistent and manufacturable, not that it is the board you meant.
