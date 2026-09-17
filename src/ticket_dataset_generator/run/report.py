"""The run report: one object behind every surface (FR-035, FR-036, FR-036a, FR-036b, R9).

The JSON output, the human rendering, the outcome, and the exit status all derive from this one
object. That makes disagreement between them structurally impossible rather than a thing to test
for — FR-036 requires the machine verdict and the human text to agree, and the cheapest way to
guarantee that is to have only one source.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ticket_dataset_generator.privacy.registry import Finding, ScanReport
from ticket_dataset_generator.run.enums import FindingStatus, RunOutcome, Verdict

#: Exit statuses, mapped from outcomes. Four rather than a binary, because "nothing was spent",
#: "output exists but did not qualify", and "work is preserved and resumable" call for different
#: responses (FR-036b, contracts/cli.md).
EXIT_STATUS = {
    RunOutcome.COMPLETED: 0,
    RunOutcome.FAILED: 1,
    RunOutcome.REFUSED: 2,
    RunOutcome.STOPPED: 3,
}


@dataclass(slots=True)
class RunReport:
    run_id: str
    schema_version: str
    outcome: RunOutcome
    records_generated: int
    records_written: int
    discards: dict[str, int]
    retry_counts: dict[str, int]
    duplicate_count: int
    coherence_score_distribution: dict[str, Any]
    composition_requested: dict[str, dict[str, float]]
    composition_assigned: dict[str, dict[str, float]]
    composition_achieved: dict[str, dict[str, float]]
    scan: ScanReport | None = None
    quarantine_path: str | None = None
    quarantine_count: int = 0
    artifact_path: str | None = None
    manifest_path: str | None = None
    failures: list[str] = field(default_factory=list)
    composition_drift_pp: dict[str, dict[str, float]] = field(default_factory=dict)
    resumed_count: int = 0
    budget: dict[str, Any] | None = None
    #: What was asked for, beside what was written, so a short corpus is visible without
    #: cross-referencing the config (FR-040).
    records_requested: int = 0
    #: Replacement slots spent making the corpus reach that number, and the rounds it took.
    top_up_slots: int = 0
    top_up_rounds: int = 0

    @property
    def verdict(self) -> Verdict:
        return Verdict.PASS if self.outcome is RunOutcome.COMPLETED else Verdict.FAIL

    @property
    def exit_status(self) -> int:
        return EXIT_STATUS[self.outcome]

    def _findings(self) -> list[dict[str, str]]:
        if self.scan is None:
            return []
        return [
            {
                "record_id": finding.record_id,
                "field": finding.field,
                "category": finding.category.value,
                "detector": finding.detector,
                "status": finding.status.value,
                # Never the matched value (FR-020).
                "masked": finding.masked,
            }
            for finding in self.scan.findings
        ]

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
            "outcome": self.outcome.value,
            "records_generated": self.records_generated,
            "records_written": self.records_written,
            "records_requested": self.records_requested,
            # Generation beyond the requested count, spent replacing discarded records. Reported
            # because it is the run's variable cost: silently adding work would be as opaque as
            # silently dropping records (Constitution Principle III).
            "top_up": {"slots": self.top_up_slots, "rounds": self.top_up_rounds},
            "discards": dict(sorted(self.discards.items())),
            "retry_counts": self.retry_counts,
            "duplicate_count": self.duplicate_count,
            "coherence_score_distribution": self.coherence_score_distribution,
            "composition_requested": self.composition_requested,
            "composition_assigned": self.composition_assigned,
            "composition_achieved": self.composition_achieved,
            # Requested to assigned is apportionment error; assigned to achieved is discard-
            # induced drift. Without the split a tolerance failure has no attributable cause,
            # and the two call for entirely different responses (FR-031a).
            "composition_drift_pp": self.composition_drift_pp,
            "resumed_count": self.resumed_count,
            "failures": self.failures,
            "artifact_path": self.artifact_path,
            "manifest_path": self.manifest_path,
        }
        if self.scan is not None:
            payload["privacy"] = {
                "records_examined": self.scan.records_examined,
                "fields_examined": self.scan.fields_examined,
                "scanned_fields": list(self.scan.scanned_fields),
                "detectors_run": list(self.scan.detectors_run),
                # Covered *and* uncovered, so a clean result is never mistaken for coverage the
                # scan does not provide (FR-019).
                "covered_types": list(self.scan.covered_types),
                "declared_gaps": list(self.scan.declared_gaps),
                "findings": self._findings(),
                "findings_by_status": dict(
                    Counter(finding.status.value for finding in self.scan.findings)
                ),
                "blocking": len(self.scan.blocking),
                "quarantine_path": self.quarantine_path,
                "quarantine_count": self.quarantine_count,
            }
        if self.budget is not None:
            payload["budget"] = self.budget
        return payload

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)

    def render(self) -> str:
        """The human rendering, derived from the same object as the JSON."""
        lines = [
            f"run {self.run_id}: {self.outcome.value} ({self.verdict.value})",
            f"  records: {self.records_written} written of {self.records_generated} generated"
            + (
                f", {self.records_requested} requested"
                if self.records_requested and self.records_requested != self.records_written
                else ""
            ),
        ]
        if self.discards:
            listed = ", ".join(
                f"{reason} {count}" for reason, count in sorted(self.discards.items())
            )
            lines.append(f"  discards: {listed}")
        if self.duplicate_count:
            lines.append(f"  duplicate conversations: {self.duplicate_count}")
        if self.scan is not None:
            by_status = Counter(finding.status.value for finding in self.scan.findings)
            lines.append(
                f"  privacy: {self.scan.records_examined} records, "
                f"{self.scan.fields_examined} fields examined by "
                f"{', '.join(self.scan.detectors_run) or 'no detectors'}"
            )
            lines.append(
                f"    findings: {dict(by_status) or 'none'}; "
                f"not covered: {', '.join(self.scan.declared_gaps)}"
            )
            if self.quarantine_count:
                lines.append(f"    quarantined: {self.quarantine_count} in {self.quarantine_path}")
        if self.composition_achieved:
            worst = _worst_drift(self.composition_requested, self.composition_achieved)
            if worst is not None:
                dimension, member, drift = worst
                lines.append(
                    f"  composition: worst member {dimension}.{member} at {drift:.2f}pp drift"
                )
        for failure in self.failures:
            lines.append(f"  FAILED: {failure}")
        if self.artifact_path:
            lines.append(f"  artifact: {self.artifact_path}")
        return "\n".join(lines)

    def write(self, directory: Path, *, published: bool) -> Path:
        """Write the report where a run identifier can find it (FR-036a).

        Beside the artifact on success, in the run's intermediate directory otherwise — a report
        findable only if you already know how the run ended would be hardest to reach exactly
        when it is most needed.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{self.run_id}.report.json" if published else "report.json"
        path = directory / name
        path.write_text(self.to_json() + "\n")
        return path


def _worst_drift(
    requested: dict[str, dict[str, float]], achieved: dict[str, dict[str, float]]
) -> tuple[str, str, float] | None:
    """The single member furthest from its request, which is what the tolerance judges."""
    worst: tuple[str, str, float] | None = None
    for dimension in sorted(requested):
        wanted = requested[dimension]
        got = achieved.get(dimension, {})
        # Sorted, and ties broken by name: two members equally far from their request must not
        # produce a different report on different runs.
        for member in sorted(set(wanted) | set(got)):
            drift = abs(got.get(member, 0.0) - wanted.get(member, 0.0)) * 100
            if worst is None or drift > worst[2]:
                worst = (dimension, member, drift)
    return worst


def build_scan_report(findings: list[Finding], **kwargs: Any) -> ScanReport:
    return ScanReport(findings=findings, **kwargs)


def status_counts(findings: list[Finding]) -> dict[FindingStatus, int]:
    return dict(Counter(finding.status for finding in findings))
