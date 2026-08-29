"""Value types for gate verdicts."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    kind: str          # "violation" | "unconnected" | "parity"
    type: str          # kicad-cli's machine-readable type, "" when absent
    description: str
    severity: str      # "error" | "warning" | "exclusion" | ""
    items: tuple       # tuple[str, ...] of affected item descriptions
    blocking: bool
    reason: str        # why the gate placed it in this class


@dataclass
class Verdict:
    blocking: list = field(default_factory=list)
    cosmetic: list = field(default_factory=list)
    # What the gate was told not to look at. Neither of these is a finding, and
    # both belong in the receipt: "PASSED" means little without them.
    excluded: int = 0            # findings the user excluded in the GUI
    ignored_checks: list = field(default_factory=list)  # rules set to "ignore"

    @property
    def passed(self) -> bool:
        return not self.blocking
