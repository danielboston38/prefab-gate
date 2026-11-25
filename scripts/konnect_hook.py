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
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schematic_change_check import (default_store, diff, kicad_export,  # noqa: E402
                                    snapshot)

SHEET = ".kicad_sch"


def _schematic(tool_input: dict) -> str | None:
    for key in ("schematic", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.endswith(SHEET):
            return value
    return None


def _could_not_run(error: Exception) -> dict:
    return {"systemMessage": f"schematic change check could not run: {error}"}


def _store(schematic: str, data: dict, base: str | None) -> str:
    """One snapshot per tool call, so calls running side by side do not mix."""
    root = base or default_store(schematic)
    return os.path.join(root, str(data.get("tool_use_id") or "call"))


def main(phase: str, data: dict, store: str | None = None, export=kicad_export,
         base: str | None = None) -> dict | None:
    schematic = _schematic(data.get("tool_input") or {})
    if schematic is None:
        return None
    store = store or _store(schematic, data, base)
    try:
        if phase == "pre":
            snapshot(schematic, store)
            return None
        _, lines = diff(schematic, store, export)
    except Exception as e:   # a hook must never break the tool call
        return _could_not_run(e)
    finally:
        if phase != "pre":
            shutil.rmtree(store, ignore_errors=True)
    if lines == ["no change"]:
        return None
    name = os.path.basename(schematic)
    text = "\n".join(lines)
    return {"systemMessage": f"Schematic changes ({name}):\n{text}",
            "hookSpecificOutput": {
                "hookEventName": data.get("hook_event_name") or "PostToolUse",
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
