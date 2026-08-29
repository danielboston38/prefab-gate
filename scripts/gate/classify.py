"""Turn parsed kicad-cli DRC JSON into a Verdict.

Pure: no filesystem, no subprocess. That is what makes the policy testable
without KiCad installed.
"""
from gate.model import Finding, Verdict

# Parity descriptions are matched by substring because kicad-cli's `type` field
# is too coarse: footprint_symbol_mismatch covers both a genuine footprint
# mismatch and a trivial exclude-from-BOM difference.
BLOCKING_PARITY = (
    "doesn't match footprint given by symbol",
    "'Do not populate' settings differ",
    "not found in schematic",
    "not found on PCB",
    "net mismatch",
)
COSMETIC_PARITY = (
    "Missing symbol field",
    "'Exclude from bill of materials' settings differ",
)


def _items(entry):
    return tuple(i.get("description", "") for i in entry.get("items", []))


def classify(drc: dict, strict: bool = False) -> Verdict:
    verdict = Verdict()

    def place(finding):
        if finding.blocking or strict:
            verdict.blocking.append(
                finding if finding.blocking
                else Finding(**{**finding.__dict__, "blocking": True,
                                "reason": finding.reason + " (promoted by --strict)"}))
        else:
            verdict.cosmetic.append(finding)

    for v in drc.get("violations", []):
        severity = v.get("severity", "")
        if severity == "exclusion":
            continue          # user excluded it in the GUI; counted, not judged
        place(Finding(kind="violation", type=v.get("type", ""),
                      description=v.get("description", ""), severity=severity,
                      items=_items(v), blocking=(severity == "error"),
                      reason=f"DRC severity is {severity or 'unset'}"))

    for u in drc.get("unconnected_items", []):
        place(Finding(kind="unconnected", type=u.get("type", "unconnected"),
                      description=u.get("description", ""), severity="error",
                      items=_items(u), blocking=True,
                      reason="unconnected items always block"))

    for p in drc.get("schematic_parity", []):
        description = p.get("description", "")
        if any(s in description for s in BLOCKING_PARITY):
            blocking, reason = True, "structural parity mismatch"
        elif any(s in description for s in COSMETIC_PARITY):
            blocking, reason = False, "metadata-only parity mismatch"
        else:
            blocking = True
            reason = ("unrecognised parity description, blocking by default: "
                      f"{description!r}")
        place(Finding(kind="parity", type=p.get("type", ""), description=description,
                      severity=p.get("severity", "warning"), items=_items(p),
                      blocking=blocking, reason=reason))

    return verdict
