"""Turn a runner Result into the text the dialog shows.

Kept apart from action.py, which imports wx and pcbnew and so cannot be
imported outside KiCad. The wording here is the part with obligations attached
— the spec requires two specific statements — so it lives where tests can
reach it.
"""
import datetime
import os

WROTE_NOTHING = ("This check wrote nothing. Packaging stays on the command "
                 "line, where the board is not being edited.")

STALE_ZONES = ("Your zone fills are stale. This check refilled them on a copy "
               "and did not touch your board — refill and save before "
               "exporting a fab package.")


def _last_saved(board_path):
    if not board_path or not os.path.isfile(board_path):
        return "unknown"
    stamp = datetime.datetime.fromtimestamp(os.path.getmtime(board_path))
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def summarise(result, board_path):
    """The dialog text for a finished run.

    Two things are stated whatever the verdict, because a quiet plugin would
    mislead in both cases.

    Which file was read, and when it was last saved: unsaved editor changes
    cannot be detected reliably from a plugin, so rather than guess, the facts
    are shown and the user resolves the ambiguity.

    And that stale zone fills were reported rather than repaired: the CLI fixes
    them as a side effect of saving, this cannot, and a clean pass on a board
    whose on-disk fills are stale is the exact fault the gate exists to catch.
    """
    lines = [f"Checked: {board_path or '(unsaved board)'}",
             f"Last saved: {_last_saved(board_path)}",
             ""]

    if result.verdict is None:
        lines.append("The gate could not run, so this board is unverified.")
        if result.messages:
            lines += ["", result.messages]
        return "\n".join(lines)

    blocking = result.verdict.get("blocking") or []
    cosmetic = result.verdict.get("cosmetic") or []

    if result.verdict.get("passed"):
        lines.append("PASSED — nothing blocking.")
    else:
        lines.append(f"BLOCKED — {len(blocking)} blocking finding(s).")
    for finding in blocking:
        lines.append(f"  x {finding.get('type')}: {finding.get('description')}")

    if cosmetic:
        lines.append("")
        lines.append(f"{len(cosmetic)} cosmetic finding(s), waived:")
        for finding in cosmetic:
            lines.append(
                f"  . {finding.get('type')}: {finding.get('description')}")

    if result.zones_were_stale:
        lines += ["", STALE_ZONES]

    lines += ["", WROTE_NOTHING]
    return "\n".join(lines)
