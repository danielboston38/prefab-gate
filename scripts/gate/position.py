"""Pad position: is each part's every pad where the mating board needs it?

A board that plugs onto another board's header has to put each pad over the
pin that will go into it. Pad direction catches a part turned round, but not
one shifted by a pitch, and a part can be placed exactly right for DRC and
parity and still miss the mating header. The board file cannot know where that
header is, so the project states it in ``prefab-gate.json`` beside the board:
the position each pad must have, and how far it may be off::

    {"pad_position": {"J1": {"tolerance": 0.1,
                             "pads": {"1": [48.26, 31.75], "2": [48.26, 29.21]}}}}

Positions are in millimetres, in the board file's own coordinates: what the
KiCad editor shows with the page origin, x to the right and y down. Bottom-side
parts are described as KiCad draws them, from the top. Pads that share a number
count as one, at their centre. Pads the rule does not name are not checked.
"""
import math
from numbers import Real

from gate.facing import footprints, load_section, parse
from gate.model import Finding
from gate.orientation import _pad_centres

SECTION = "pad_position"

# The pads named in a finding; the count says how many more there are.
SHOWN = 3


def _config_problem(description, items=()):
    return Finding(kind="placement", type="pad_position_config",
                   description=description, severity="error",
                   items=tuple(items), blocking=True,
                   reason="a pad position rule that cannot be checked is not a pass")


def _number(value):
    return isinstance(value, Real) and not isinstance(value, bool)


def _read_rule(ref, rule):
    """(tolerance, {pad: (x, y)}) from one rule. Raises ValueError saying what is wrong."""
    example = '{"tolerance": 0.1, "pads": {"1": [48.26, 31.75]}}'
    if not isinstance(rule, dict) or "tolerance" not in rule or "pads" not in rule:
        raise ValueError(f'{ref}: a rule needs "tolerance" and "pads", e.g. {example}.')
    tolerance = rule["tolerance"]
    if not _number(tolerance) or tolerance < 0:
        raise ValueError(f'{ref}: "tolerance" must be a number of millimetres, '
                         f'0 or more, not {_as_written(tolerance)}.')
    pads = rule["pads"]
    if not isinstance(pads, dict) or not pads:
        raise ValueError(f'{ref}: "pads" must name at least one pad, e.g. {example}.')
    wanted = {}
    for number, at in pads.items():
        if not (isinstance(at, list) and len(at) == 2 and all(map(_number, at))):
            raise ValueError(f'{ref}: pad {number} must be at [x, y] in millimetres, '
                             f'not {_as_written(at)}.')
        wanted[str(number)] = (float(at[0]), float(at[1]))
    return float(tolerance), wanted


def _as_written(value):
    """A rule value as the user would recognise it in the JSON."""
    return repr(value) if not isinstance(value, str) else f'"{value}"'


def _misplaced(ref, tolerance, off, total):
    shown = "; ".join(
        f"pad {number} is at ({got[0]:.3f}, {got[1]:.3f}), must be at "
        f"({want[0]:.3f}, {want[1]:.3f}): {distance:.3f} mm away"
        for number, got, want, distance in off[:SHOWN])
    more = f"; and {len(off) - SHOWN} more" if len(off) > SHOWN else ""
    return Finding(
        kind="placement", type="pad_position",
        description=f"{ref}: {len(off)} of {total} pads are more than "
                    f"{tolerance:g} mm from where the rules put them: "
                    f"{shown}{more}. The part is moved, turned or flipped, or "
                    "its footprint places the pins differently.",
        severity="error", items=(ref,), blocking=True,
        reason="a pad that misses the pin of the mating board does not connect")


def check(board_path, rules_path=None):
    """Findings for every part whose pads are not where its rule puts them."""
    if not rules_path:
        return []
    try:
        wanted = load_section(rules_path, SECTION)
    except (OSError, ValueError) as exc:
        return [_config_problem(
            f"Cannot read the pad position rules in {rules_path}: {exc}")]
    if not wanted:
        return []

    with open(board_path, encoding="utf-8") as f:
        placed = footprints(parse(f.read()))

    findings = []
    for ref, rule in sorted(wanted.items()):
        try:
            tolerance, pads = _read_rule(ref, rule)
        except ValueError as exc:
            findings.append(_config_problem(str(exc), [ref]))
            continue
        if ref not in placed:
            findings.append(_config_problem(
                f"{ref} has a pad position rule but is not on the board.", [ref]))
            continue
        centres = _pad_centres(placed[ref])
        missing = [p for p in pads if p not in centres]
        if missing:
            findings.append(_config_problem(
                f"{ref} has no pad {', '.join(missing)}.", [ref]))
            continue
        off = []
        for number, want in pads.items():
            got = centres[number]
            distance = math.dist(got, want)
            if distance > tolerance:
                off.append((number, got, want, distance))
        if off:
            findings.append(_misplaced(ref, tolerance, off, len(pads)))
    return findings
