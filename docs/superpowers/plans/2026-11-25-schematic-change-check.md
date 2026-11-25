# Schematic Change Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any tool (Konnect MCP, a script, a person) rewrites a KiCad schematic, print exactly what changed electrically: parts added or removed, field changes, and pins that moved to another net.

**Architecture:** `snapshot` copies the schematic files of a project folder into a store. `diff` exports a kicad-cli netlist from the snapshot copy and from the live files, compares the two, and prints the changes. A Claude Code hook calls `snapshot` before each `mcp__konnect__*` call and `diff` after it, so every Konnect schematic write is reported to Claude and to the user. Report only, no rollback.

**Tech Stack:** Python 3 stdlib (`unittest`, no third-party packages), `kicad-cli sch export netlist`, Claude Code plugin hooks.

**Spec:** this plan (agreed with Mark in an Osgood Debug session on 2026-11-25). Why: Konnect has no KiCad IPC for schematics; it rewrites `.kicad_sch` with its own S-expression code, so its schematic edits do not show in KiCad's undo or history. KiCad 11 is expected to add a diff command to kicad-cli (Mark, 2026-11-25: then this can become a simple script around it); `diff` is the one place to swap it in, so keep the CLI and hook interface independent of how the comparison is done.

## Global Constraints

- Stdlib only; tests are `unittest` (README: "Stdlib `unittest` only — no pytest, no third-party dependencies").
- Test command: `cd scripts && PYTHONPATH=. python3 -m unittest discover -s ../tests -p 'test_*.py' -v`
- Exit codes follow prefab_gate: `0` = no change, `2` = changes found (report printed), `3` = could not run (kicad-cli missing, no snapshot, netlist export failed). Usage errors also exit 3.
- Find kicad-cli with the existing `gate.kicad.locate_cli()`; parse S-expressions with the existing `gate.facing.parse()`.
- Compare by connectivity, not by text: KiCad's auto-names (`Net-(R1-Pad2)`, `unconnected-(…)`) change when parts are renamed, so a pin's net is identified by the set of pins it shares a net with, plus its name only when the name is user-given (not starting with `Net-(` or `unconnected-(`).
- Never write inside the project folder. Default store: `~/.cache/prefab-gate/snapshots/<sha256 of the absolute folder path>/`; `--store DIR` overrides.
- The hook must never block or fail a tool call: it always exits 0 and only adds output.

## Review Focus

1. Hierarchical project (several `.kicad_sch` in the folder): the snapshot must hold all of them, or the old netlist is incomplete. Test in Task 2.
2. File rewritten but nothing electrical changed (Konnect reorders, moves a label, edits a text): must say `connectivity unchanged` and exit 0, not report noise. Test in Task 2.
3. A part renamed (R5 → R7) makes KiCad auto-names change for every net it touches: must report one rename, not a list of net changes. Test in Task 1.
4. `diff` with no snapshot for that folder: exit 3 with a clear message, never report "no change". Test in Task 2.
5. A Konnect read-only call (most calls): the hook must cost almost nothing; post-hook compares sha256s first and runs kicad-cli only when a file changed. Test in Task 2.

---

### Task 1: Netlist model and comparison

**Files:**
- Create: `scripts/gate/schdiff.py`
- Test: `tests/test_schdiff.py`

**Interfaces:**
- Produces:
  - `read_netlist(text: str) -> Netlist` — parses kicad-cli netlist text.
  - `Netlist` (frozen dataclass): `parts: dict[str, dict[str, str]]` (ref → `{"value", "footprint", "lib"}`), `pin_net: dict[tuple[str, str], str]` ((ref, pin) → net name).
  - `compare(old: Netlist, new: Netlist) -> list[str]` — human-readable change lines, sorted, empty when electrically equal.

- [ ] **Step 1: Write the failing tests** (build netlist text with a small helper `netlist(parts, nets)` in the test file, same layout as kicad-cli: `(export (components (comp (ref "R1") (value "10k") (footprint "R_0603") (libsource (lib "Device") (part "R")))) (nets (net (code "1") (name "/VCC") (node (ref "R1") (pin "1")))))`)
  - `test_identical_netlists_have_no_changes`: `compare(a, a) == []`
  - `test_leading_slash_is_dropped`: net `/VCC` is read as `VCC`.
  - `test_part_added_and_removed`: lines `+ C9 100n (C_0603)` and `- R3 10k (R_0603)`.
  - `test_value_and_footprint_change`: line `R5 value 10k -> 4k7`, line `R5 footprint R_0603 -> R_0805`.
  - `test_pin_moves_to_other_named_net`: `U4.3: P_PHI2 -> GND`.
  - `test_pin_disconnected`: `U4.3: P_PHI2 -> (none)` (pin missing from new nets, or alone in an `unconnected-(…)` net).
  - `test_rename_is_one_line`: R5 renamed R7 with the same pins; auto-named nets `Net-(R5-Pad2)` → `Net-(R7-Pad2)`; result is exactly `["rename R5 -> R7"]`.
  - `test_auto_net_compared_by_members`: two auto-named nets whose names differ but whose pin sets are equal give no change.

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError: gate.schdiff`.

- [ ] **Step 3: Implement `read_netlist` and `compare` in `scripts/gate/schdiff.py`**
  Rename detection: a removed ref and an added ref with equal value, footprint, lib and the same pin-to-net mapping (after mapping auto-names by members) is a rename. A pin's "net identity" is its user name if it has one, else the frozenset of the other (ref, pin) in its net, with renamed refs mapped old → new before comparing.

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Commit** — `feat(schdiff): compare two schematic netlists by connectivity`

### Task 2: snapshot and diff commands

**Files:**
- Create: `scripts/schematic_change_check.py`
- Test: `tests/test_schematic_change_check.py`

**Interfaces:**
- Consumes: `read_netlist`, `compare` (Task 1); `gate.kicad.locate_cli`.
- Produces:
  - `snapshot(schematic: str, store: str | None = None) -> str` — copies every `*.kicad_sch`, `*.kicad_pro`, `sym-lib-table` in the schematic's folder into the store folder (replacing the old snapshot), writes `hashes.json` ({filename: sha256}), returns the store folder.
  - `changed_files(schematic: str, store: str | None = None) -> list[str]` — names whose sha256 differs from `hashes.json`, plus added/removed `.kicad_sch`. Raises `NoSnapshot` if none exists.
  - `diff(schematic: str, store: str | None = None, export=<kicad-cli netlist exporter>) -> tuple[int, list[str]]` — `(0, ["no change"])`, `(0, ["file changed, connectivity unchanged: <names>"])`, or `(2, change lines)`.
  - CLI: `schematic_change_check.py snapshot|diff <file.kicad_sch> [--store DIR]`; prints the lines; exits 0/2/3.

- [ ] **Step 1: Write the failing tests** (inject a fake `export(cli, sch_path) -> str` that returns canned netlist text keyed by file content, so no kicad-cli is needed; use `tempfile.TemporaryDirectory` for project and store)
  - `test_snapshot_copies_all_sheets`: folder with `top.kicad_sch` + `sub.kicad_sch` → both in the store and in `hashes.json`.
  - `test_diff_without_snapshot_exits_3`: CLI exit code 3, stderr contains `no snapshot`.
  - `test_unchanged_files_skip_kicad_cli`: export fake records calls; after snapshot + diff with no edits, it was called 0 times and result is `(0, ["no change"])`.
  - `test_cosmetic_change`: file bytes changed, fake returns the same netlist → `(0, ["file changed, connectivity unchanged: top.kicad_sch"])`.
  - `test_electrical_change_exits_2`: fake returns a netlist with one value change → `(2, ["R5 value 10k -> 4k7"])`.
  - `test_store_outside_project`: default store path does not start with the project folder.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement** — the real exporter runs `kicad-cli sch export netlist -o <tmp> <sch>` and returns the file text; non-zero exit → exit 3 with kicad-cli's stderr. The snapshot's netlist is exported from the store copy of the same filename (all sheets are there, so hierarchy resolves).

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Real check against kicad-cli** — on a scratch copy of a real project (Osgood `hardware/adapter/`): `snapshot`, then change one resistor value with Konnect's `edit_schematic_component` on the copy, then `diff`. Expected: exit 2 and exactly one `value` line. Then `diff` again after restoring the file: exit 0, `no change`.

- [ ] **Step 6: Commit** — `feat: snapshot and diff a schematic's netlist`

### Task 3: Konnect hook

**Files:**
- Create: `scripts/konnect_hook.py`, `hooks/hooks.json`
- Test: `tests/test_konnect_hook.py`

**Interfaces:**
- Consumes: `snapshot`, `changed_files`, `diff` (Task 2).
- Produces: `main(phase: str, stdin_json: dict) -> dict | None` — `phase` is `pre` or `post`. Returns the hook output JSON or `None` (print nothing).

Hook contract (Claude Code): input JSON on stdin has `tool_name` and `tool_input`. The schematic path is `tool_input["schematic"]` (Konnect's parameter name; also accept `path` when it ends in `.kicad_sch`). No such key → do nothing.

- [ ] **Step 1: Write the failing tests**
  - `test_no_schematic_key_does_nothing`: `main("pre", {"tool_name": "mcp__konnect__list_toolboxes", "tool_input": {}})` is `None` and no store folder is created.
  - `test_pre_takes_snapshot`: store folder holds the file afterwards.
  - `test_post_without_change_is_silent`: returns `None`.
  - `test_post_with_change_reports`: returns `{"systemMessage": "<lines>", "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "Schematic changes from <tool_name>:\n<lines>"}}`.
  - `test_errors_never_raise`: a missing kicad-cli or unreadable file returns a `systemMessage` starting `schematic change check could not run:`, never raises.

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `main`, plus a `__main__` that reads stdin, prints the JSON, and always exits 0.** `hooks/hooks.json`: `PreToolUse` and `PostToolUse`, matcher `mcp__konnect__.*`, command `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/konnect_hook.py" pre|post`.

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Commit** — `feat: report every Konnect schematic change through a hook`

### Task 4: Docs and live trial

**Files:**
- Modify: `README.md` (new section "Schematic change check": what it does, the CLI, the hook, exit codes, why: Konnect schematic edits skip KiCad history; KiCad 11 kicad-cli diff note)
- Modify: `skills/prefab-gate/SKILL.md` (one paragraph: when the hook reports changes, compare them with what was asked; say any extra change to the user)

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Full test suite** — Expected: all OK, including the old tests.
- [ ] **Step 3: Live trial in Osgood** — Mark uses the local clone, so add the same two hooks to `osgood-debug/.claude/settings.json` with the absolute path `/Users/mark/build/prefab-gate/scripts/konnect_hook.py` (ask Mark before changing settings). Restart Claude Code. On a scratch copy of `adapter/`: a Konnect read (`list_schematic_nets`) shows nothing; a Konnect write that changes one value shows one line in the transcript.
- [ ] **Step 4: Commit** on branch `schematic-change-check`; push and open a PR only when Mark asks.
