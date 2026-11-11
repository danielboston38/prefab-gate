"""Connector facing: does each right-angle connector point out the right edge?

A footprint can match its datasheet, pass DRC and parity, and still put the
jack's opening on the wrong side of the board. Nothing in the board file says
which edge faces the case opening, so the gate cannot infer this; the project
has to state it. The rules live in ``prefab-gate.json`` beside the board::

    {"connector_facing": {"J2": "left", "J3": "left"}}

Edges are named as the board appears in the KiCad editor: ``left``, ``right``,
``top`` and ``bottom``.

A connector faces the edge its courtyard runs out past the furthest. One that
ends just inside the edge (within ``FLUSH_MM``) still counts, so a jack mounted
flush with a front panel is not reported. The edges are taken from the
bounding box of the board outline, which is exact for a rectangular board.

Written after a built board had both RCA jacks facing into the console instead
of out through the case. The footprint matched the datasheet and the barrels did
cross a board edge, only the wrong one.
"""
import json
import math
import re

from gate.model import Finding

RULES_FILE = "prefab-gate.json"
EDGES = ("left", "right", "top", "bottom")

# How far inside the board edge a courtyard may end and still count as facing
# that edge. A front-panel-flush jack's courtyard often stops just short.
FLUSH_MM = 1.0


def _tokens(text):
    for m in re.finditer(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', text):
        yield m.group(0)


def parse(text):
    """The board's S-expression as nested lists. Strings lose their quotes."""
    stack = [[]]
    for tok in _tokens(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"'))
        else:
            stack[-1].append(tok)
    return stack[0][0] if stack[0] else []


def _children(node, head):
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _child(node, head):
    found = _children(node, head)
    return found[0] if found else None


def _layer(node):
    layer = _child(node, "layer")
    return layer[1] if layer and len(layer) > 1 else ""


def _xy(node, head):
    found = _child(node, head)
    return (float(found[1]), float(found[2])) if found else None


def _shape_points(shape):
    """Points that bound a graphic: corners, ends, and a circle's extremes."""
    if shape[0].endswith("circle"):
        cx, cy = _xy(shape, "center")
        ex, ey = _xy(shape, "end")
        r = math.hypot(ex - cx, ey - cy)
        return [(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r)]
    if shape[0].endswith("poly"):
        pts = _child(shape, "pts") or []
        return [(float(p[1]), float(p[2])) for p in _children(pts, "xy")]
    points = [_xy(shape, k) for k in ("start", "mid", "end")]
    points = [p for p in points if p]
    if shape[0].endswith("rect") and len(points) == 2:
        (x1, y1), (x2, y2) = points
        points = [(x1, y1), (x2, y2), (x1, y2), (x2, y1)]
    return points


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _outline(tree):
    points = []
    for node in tree:
        if (isinstance(node, list) and node and str(node[0]).startswith("gr_")
                and _layer(node) == "Edge.Cuts"):
            points.extend(_shape_points(node))
    return _bbox(points) if points else None


def _reference(fp):
    for prop in _children(fp, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            return prop[2]
    text = [t for t in _children(fp, "fp_text") if len(t) > 2 and t[1] == "reference"]
    return text[0][2] if text else None


def _footprints(tree):
    return {_reference(fp): fp for fp in _children(tree, "footprint")}


def _courtyard(fp):
    """The courtyard's corners in board coordinates.

    KiCad stores a back-side footprint's graphics already mirrored, so placing
    either side is the same rotate-then-translate. Its rotation is
    counter-clockwise on screen, with y pointing down.
    """
    at = _child(fp, "at")
    x, y = float(at[1]), float(at[2])
    theta = math.radians(float(at[3])) if len(at) > 3 else 0.0
    c, s = math.cos(theta), math.sin(theta)
    points = []
    for shape in fp:
        if (isinstance(shape, list) and shape and str(shape[0]).startswith("fp_")
                and _layer(shape).endswith(".CrtYd")):
            for lx, ly in _shape_points(shape):
                points.append((x + lx * c + ly * s, y - lx * s + ly * c))
    return points


def _edge_of(points, outline):
    """The edge a set of points runs out past the furthest, or None."""
    left, top, right, bottom = outline
    x0, y0, x1, y1 = _bbox(points)
    overhang = {"left": left - x0, "right": x1 - right,
                "top": top - y0, "bottom": y1 - bottom}
    edge = max(EDGES, key=lambda e: overhang[e])
    return edge if overhang[edge] >= -FLUSH_MM else None


def facing_edge(board_text, reference):
    """The edge the named footprint faces, or None when it reaches no edge."""
    tree = parse(board_text)
    return _edge_of(_courtyard(_footprints(tree)[reference]), _outline(tree))


def _config_problem(description, items=()):
    return Finding(kind="facing", type="connector_facing_config",
                   description=description, severity="error",
                   items=tuple(items), blocking=True,
                   reason="a facing rule that cannot be checked is not a pass")


def _load_rules(rules_path):
    with open(rules_path, encoding="utf-8") as f:
        rules = json.load(f)
    if not isinstance(rules, dict):
        raise ValueError("the file must hold a JSON object")
    section = rules.get("connector_facing", {})
    if not isinstance(section, dict):
        raise ValueError('"connector_facing" must map references to edges')
    return section


def check(board_path, rules_path=None):
    """Findings for every connector whose facing rule does not hold."""
    if not rules_path:
        return []
    try:
        wanted = _load_rules(rules_path)
    except (OSError, ValueError) as exc:
        return [_config_problem(f"Cannot read the facing rules in {rules_path}: {exc}")]
    if not wanted:
        return []

    with open(board_path, encoding="utf-8") as f:
        tree = parse(f.read())
    outline = _outline(tree)
    if outline is None:
        return [_config_problem(
            "The board has no Edge.Cuts outline, so no connector can be checked "
            "against an edge.")]
    footprints = _footprints(tree)

    findings = []
    for ref, edge in sorted(wanted.items()):
        want = str(edge).lower()
        if want not in EDGES:
            findings.append(_config_problem(
                f'{ref}: "{edge}" is not an edge. Use one of: {", ".join(EDGES)}.',
                [ref]))
            continue
        if ref not in footprints:
            findings.append(_config_problem(
                f"{ref} has a facing rule but is not on the board.", [ref]))
            continue
        points = _courtyard(footprints[ref])
        if not points:
            findings.append(_config_problem(
                f"{ref} has no courtyard, so the gate cannot tell which way it "
                "faces.", [ref]))
            continue
        got = _edge_of(points, outline)
        if got != want:
            where = (f"faces the {got} edge" if got
                     else "does not reach any board edge")
            findings.append(Finding(
                kind="facing", type="connector_facing",
                description=f"{ref} {where}, but the rules say it must face "
                            f"the {want} edge.",
                severity="error", items=(ref,), blocking=True,
                reason="a connector facing the wrong way cannot be plugged in "
                       "once the board is in its case"))
    return findings
