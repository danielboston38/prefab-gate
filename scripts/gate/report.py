"""Human and machine renderings of a verdict."""
import json
from dataclasses import asdict


def _line(finding):
    where = f"  [{', '.join(finding.items)}]" if finding.items else ""
    return (f"  {finding.type or finding.kind:32} {finding.description}{where}\n"
            f"      {finding.reason}")


def render_text(verdict) -> str:
    out = []
    if verdict.passed:
        out.append(f"PASSED — nothing blocking. {len(verdict.cosmetic)} cosmetic "
                   f"finding(s) waved through.")
    else:
        out.append(f"BLOCKED — {len(verdict.blocking)} blocking finding(s). "
                   "No files were produced.")
        out.append("")
        out.append("Blocking:")
        out.extend(_line(f) for f in verdict.blocking)
    if verdict.cosmetic:
        out.append("")
        out.append(f"Cosmetic ({len(verdict.cosmetic)}):")
        out.extend(_line(f) for f in verdict.cosmetic)
    return "\n".join(out)


def render_json(verdict) -> str:
    return json.dumps({
        "passed": verdict.passed,
        "blocking": [asdict(f) for f in verdict.blocking],
        "cosmetic": [asdict(f) for f in verdict.cosmetic],
    }, indent=2)
