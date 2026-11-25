#!/usr/bin/env python3
"""Claude Code hook: report what a Konnect MCP call changed in a schematic.

    PreToolUse:  konnect_hook.py pre    (snapshots the schematic's folder)
    PostToolUse: konnect_hook.py post   (prints the electrical changes)

Konnect has no KiCad IPC for schematics: it rewrites the .kicad_sch file with
its own code, so its edits do not show in KiCad's undo or history. This hook
is that history. It only reports; it never blocks a call, and always exits 0.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schematic_change_check import diff, kicad_export, snapshot   # noqa: E402

SHEET = ".kicad_sch"


def _schematic(tool_input: dict) -> str | None:
    for key in ("schematic", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.endswith(SHEET):
            return value
    return None


def _could_not_run(error: Exception) -> dict:
    return {"systemMessage": f"schematic change check could not run: {error}"}


def main(phase: str, data: dict, store: str | None = None, export=kicad_export) -> dict | None:
    schematic = _schematic(data.get("tool_input") or {})
    if schematic is None:
        return None
    try:
        if phase == "pre":
            snapshot(schematic, store)
            return None
        _, lines = diff(schematic, store, export)
    except Exception as e:   # a hook must never break the tool call
        return _could_not_run(e)
    if lines == ["no change"]:
        return None
    name = os.path.basename(schematic)
    text = "\n".join(lines)
    return {"systemMessage": f"Schematic changes ({name}):\n{text}",
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"Schematic changes from {data.get('tool_name')} "
                                     f"({name}):\n{text}"}}


if __name__ == "__main__":
    try:
        phase = sys.argv[1] if len(sys.argv) > 1 else ""
        out = main(phase, json.load(sys.stdin))
    except Exception as e:
        out = _could_not_run(e)
    if out:
        print(json.dumps(out))
    sys.exit(0)
