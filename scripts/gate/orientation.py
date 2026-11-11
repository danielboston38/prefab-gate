"""Pad direction: is each polarised part the right way round?

A part rotated 180 degrees, or drawn with a footprint that numbers its pins the
other way, passes DRC and parity: the nets still land on the right pads. It is
only wrong once a cable, a mating board or a case expects pin 1 on the other
side. The board file cannot say which way is right, so the project states it in
``prefab-gate.json`` beside the board, naming two pads and the way the line
between them must point::

    {"pad_direction": {"J1": {"from": "1", "to": "2", "toward": "right"}}}

Directions are named as the board appears in the KiCad editor: ``left``,
``right``, ``top`` and ``bottom``. Pads that share a number (shield tabs, say)
count as one, at their centre.

A pair of pads too close to diagonal names no direction, and is refused rather
than rounded: rounding a diagonal is a guess, and a guess can pass a flipped
part.
"""
from gate.facing import EDGES, footprints, load_section, parse, place
from gate.model import Finding

SECTION = "pad_direction"

# The along-axis offset must be at least this many times the cross-axis one
# for the pair to name a direction: about 26.6 degrees either side of an axis.
DOMINANCE = 2.0


def _pad_centres(fp):
    """Each pad number's centre, in board coordinates."""
    local = {}
    for pad in fp:
        if not (isinstance(pad, list) and pad and pad[0] == "pad" and len(pad) > 1):
            continue
        at = next((c for c in pad if isinstance(c, list) and c and c[0] == "at"), None)
        if at:
            local.setdefault(str(pad[1]), []).append((float(at[1]), float(at[2])))
    centres = {}
    for number, points in local.items():
        placed = place(fp, points)
        centres[number] = (sum(p[0] for p in placed) / len(placed),
                           sum(p[1] for p in placed) / len(placed))
    return centres


def _direction(start, end):
    """The direction from one point to another, or None when it is not clear."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    if abs(dx) >= DOMINANCE * abs(dy) and dx:
        return "right" if dx > 0 else "left"
    if abs(dy) >= DOMINANCE * abs(dx) and dy:
        return "bottom" if dy > 0 else "top"   # KiCad's y points down
    return None


def pad_direction(board_text, reference, from_pad, to_pad):
    """The direction from one of a part's pads to another, or None."""
    centres = _pad_centres(footprints(parse(board_text))[reference])
    return _direction(centres[from_pad], centres[to_pad])


def _config_problem(description, items=()):
    return Finding(kind="orientation", type="pad_direction_config",
                   description=description, severity="error",
                   items=tuple(items), blocking=True,
                   reason="a pad direction rule that cannot be checked is not a pass")


def _read_rule(ref, rule):
    """(from, to, toward) from one rule. Raises ValueError saying what is wrong."""
    if not isinstance(rule, dict) or not all(k in rule for k in ("from", "to", "toward")):
        raise ValueError(f'{ref}: a rule needs "from", "to" and "toward", e.g. '
                         '{"from": "1", "to": "2", "toward": "right"}.')
    toward = str(rule["toward"]).lower()
    if toward not in EDGES:
        raise ValueError(f'{ref}: "{rule["toward"]}" is not a direction. '
                         f'Use one of: {", ".join(EDGES)}.')
    return str(rule["from"]), str(rule["to"]), toward


def check(board_path, rules_path=None):
    """Findings for every part whose pad direction rule does not hold."""
    if not rules_path:
        return []
    try:
        wanted = load_section(rules_path, SECTION)
    except (OSError, ValueError) as exc:
        return [_config_problem(
            f"Cannot read the pad direction rules in {rules_path}: {exc}")]
    if not wanted:
        return []

    with open(board_path, encoding="utf-8") as f:
        placed = footprints(parse(f.read()))

    findings = []
    for ref, rule in sorted(wanted.items()):
        try:
            from_pad, to_pad, want = _read_rule(ref, rule)
        except ValueError as exc:
            findings.append(_config_problem(str(exc), [ref]))
            continue
        if ref not in placed:
            findings.append(_config_problem(
                f"{ref} has a pad direction rule but is not on the board.", [ref]))
            continue
        centres = _pad_centres(placed[ref])
        missing = [p for p in (from_pad, to_pad) if p not in centres]
        if missing:
            findings.append(_config_problem(
                f"{ref} has no pad {', '.join(missing)}.", [ref]))
            continue
        got = _direction(centres[from_pad], centres[to_pad])
        if got is None:
            findings.append(_config_problem(
                f"{ref}: pads {from_pad} and {to_pad} are not lined up along "
                "either axis, so they name no direction. Pick two pads in a "
                "straight row or column.", [ref]))
            continue
        if got != want:
            findings.append(Finding(
                kind="orientation", type="pad_direction",
                description=f"{ref}: pad {from_pad} to pad {to_pad} points "
                            f"{got}, but the rules say it must point {want}. "
                            "The part is turned or flipped, or its footprint "
                            "numbers the pins the other way.",
                severity="error", items=(ref,), blocking=True,
                reason="a polarised part the wrong way round does not mate "
                       "with what plugs into it"))
    return findings
