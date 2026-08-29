"""Turn parsed kicad-cli DRC JSON into a Verdict.

Pure: no filesystem, no subprocess. That is what makes the policy testable
without KiCad installed.
"""
from dataclasses import replace

from gate.model import Finding, Parity, Verdict

# Parity descriptions are matched by substring because kicad-cli's `type` field
# is too coarse: footprint_symbol_mismatch covers both a genuine footprint
# mismatch and a trivial exclude-from-BOM difference.
BLOCKING_PARITY = (
    "doesn't match footprint given by symbol",
    "'Do not populate' settings differ",
    "Missing footprint",
    "doesn't match net given by schematic",
    "Pad missing net given by schematic",
    "No corresponding pin found in schematic",
    "No pad found for pin",
)
COSMETIC_PARITY = (
    "Missing symbol field",
    "'Exclude from bill of materials' settings differ",
    "doesn't match symbol value",
    "differs (PCB:",
)


def _items(entry):
    return tuple(i.get("description", "") for i in entry.get("items", []))


def _judge_severity(severity: str):
    """An unrecognised severity blocks.

    Treating anything-but-"error" as cosmetic made an absent or future severity
    purely decorative, while the parity path deliberately fails closed on an
    unfamiliar message. The two policies now agree: what the gate does not
    understand, it does not wave through.
    """
    if severity == "error":
        return True, "DRC severity is error"
    if severity == "warning":
        return False, "DRC severity is warning"
    return True, ("unrecognised DRC severity "
                  f"{severity!r}, blocking by default")


def parity_not_run(parity: Parity) -> Finding:
    """Parity that could not run is a finding, never a silent skip.

    Blocking by default, exactly like an unrecognised parity description: the
    gate cannot tell an unchecked board from a clean one. Cosmetic only when
    the user waived it with --no-parity — a PCB-only design is legitimate, but
    it may not pass quietly.
    """
    return Finding(
        kind="parity", type="parity_not_run",
        description="Schematic parity did not run",
        severity="warning" if parity.waived else "error",
        items=(), blocking=not parity.waived, reason=parity.reason)


def classify(drc: dict, strict: bool = False, parity: Parity = None) -> Verdict:
    parity = Parity(ran=True) if parity is None else parity
    # Recorded, not judged: rules the project file sets to "ignore" never
    # appear as findings at all, so a clean verdict on a board with five
    # checks switched off would otherwise say nothing about them.
    verdict = Verdict(ignored_checks=list(drc.get("ignored_checks", []) or []),
                      parity=parity)

    def place(finding):
        if finding.blocking:
            verdict.blocking.append(finding)
        elif strict:
            verdict.blocking.append(replace(
                finding, blocking=True,
                reason=finding.reason + " (promoted by --strict)"))
        else:
            verdict.cosmetic.append(finding)

    for v in drc.get("violations", []):
        severity = v.get("severity", "")
        if severity == "exclusion":
            # Excluded in the GUI: counted, not judged. The count is the point —
            # it is the difference between "nothing was wrong" and "you told me
            # not to look".
            verdict.excluded += 1
            continue
        blocking, reason = _judge_severity(severity)
        place(Finding(kind="violation", type=v.get("type", ""),
                      description=v.get("description", ""), severity=severity,
                      items=_items(v), blocking=blocking, reason=reason))

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

    if not parity.ran:
        place(parity_not_run(parity))

    return verdict
