"""Turn parsed kicad-cli DRC JSON into a Verdict.

Pure: no filesystem, no subprocess. That is what makes the policy testable
without KiCad installed.
"""
from gate.model import Finding, Verdict


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

    return verdict
