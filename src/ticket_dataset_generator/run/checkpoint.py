"""Checkpointing and resume (FR-015a–FR-015i, research R6).

Because records are written in strict position order, the staging file is always a *prefix* of
the corpus. That is what makes a single byte offset a sufficient recovery point: resume truncates
to it and continues, with no scanning, no partial-line parsing, and no possibility of a duplicated
record.

The input fingerprints decide whether a checkpoint is applicable at all. A changed configuration,
seed, prompt document, or rubric makes it inapplicable, and resuming is refused rather than
producing a corpus the manifest cannot honestly describe (FR-015e). The **code revision is
deliberately excluded** from that set: a changed revision is recorded as an additional manifest
segment instead (FR-015f), because discarding hours of a release-scale run over an edit made while
it was interrupted trades away far more than it protects.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.errors import (
    AmbiguousResumeError,
    CheckpointCorruptError,
    CheckpointMismatchError,
)
from ticket_dataset_generator.run.revision import hash_file

CHECKPOINT_NAME = "checkpoint.json"


def input_fingerprints(config: GenerationConfig, seed: int, schema_version: str) -> dict[str, str]:
    """What must match for a checkpoint to be applicable (FR-015e, FR-015h).

    Note what is absent: the code revision. A run that resumes under changed code is described
    rather than refused (FR-015f).
    """
    serialized = json.dumps(config.model_dump(mode="json"), sort_keys=True)
    fingerprints = {
        "config": sha256(serialized.encode()).hexdigest(),
        "seed": sha256(str(seed).encode()).hexdigest(),
        "schema_version": schema_version,
    }
    for label, path in (
        ("prompt_document", config.prompt_document),
        ("rubric", config.rubric),
    ):
        if Path(path).exists():
            fingerprints[label] = hash_file(path)
    return fingerprints


@dataclass(slots=True)
class Checkpoint:
    run_id: str
    next_position: int
    bytes_written: int
    input_fingerprints: dict[str, str]
    discards: dict[str, int] = field(default_factory=dict)
    retry_counts: dict[str, int] = field(default_factory=dict)
    duplicate_count: int = 0
    records_generated: int = 0
    records_written: int = 0
    resumes: int = 0
    segments: list[dict[str, Any]] = field(default_factory=list)
    #: Replacement slots spent so far on making the corpus reach ``record_count`` (FR-040).
    #: Defaulted, so a checkpoint written before top-up existed still loads.
    top_up_slots: int = 0

    def write(self, directory: Path) -> Path:
        """Write durably, via a temp file and a rename, so it is never half-written."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / CHECKPOINT_NAME
        temporary = directory / f"{CHECKPOINT_NAME}.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target

    @classmethod
    def read(cls, path: Path) -> Checkpoint:
        path = Path(path)
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            # Reported as unusable, and the partial output is left alone: restarting from scratch
            # is an explicit operator action, not something the tool decides at the moment its own
            # state became untrustworthy (FR-015g).
            raise CheckpointCorruptError(
                f"{path} could not be read: {error}. The partial output has been left in place; "
                "restart deliberately if you want to discard it (FR-015g)."
            ) from error
        try:
            return cls(**payload)
        except TypeError as error:
            raise CheckpointCorruptError(f"{path} is not a checkpoint: {error}") from error

    def assert_applicable(self, fingerprints: dict[str, str]) -> None:
        """Refuse a resume whose inputs no longer match (FR-015e)."""
        differing = sorted(
            key
            for key in set(self.input_fingerprints) | set(fingerprints)
            if self.input_fingerprints.get(key) != fingerprints.get(key)
        )
        if differing:
            raise CheckpointMismatchError(
                f"cannot resume: {', '.join(differing)} changed since the checkpoint. Continuing "
                "would produce a corpus the manifest cannot honestly describe (FR-015e). "
                "The code revision is deliberately not compared — a changed revision is recorded "
                "as a manifest segment instead (FR-015f)."
            )


def find_resumable(staging_root: Path, fingerprints: dict[str, str]) -> list[Checkpoint]:
    """Checkpointed runs matching these inputs, newest first (FR-015h)."""
    root = Path(staging_root)
    if not root.exists():
        return []
    matches: list[Checkpoint] = []
    for directory in sorted(root.iterdir()):
        candidate = directory / CHECKPOINT_NAME
        if not candidate.exists():
            continue
        try:
            checkpoint = Checkpoint.read(candidate)
        except CheckpointCorruptError:
            continue
        if checkpoint.input_fingerprints == fingerprints:
            matches.append(checkpoint)
    return matches


def select_resumable(
    staging_root: Path, fingerprints: dict[str, str], run_id: str | None = None
) -> Checkpoint:
    """The run to resume: named explicitly, or the single match (FR-015h)."""
    candidates = find_resumable(staging_root, fingerprints)
    if run_id is not None:
        for candidate in candidates:
            if candidate.run_id == run_id:
                return candidate
        raise CheckpointMismatchError(
            f"no checkpointed run {run_id} matches these inputs under {staging_root}"
        )
    if not candidates:
        raise CheckpointMismatchError(
            f"nothing to resume under {staging_root} for these inputs. Starting a new run under "
            "the guise of resuming would be worse than refusing (FR-015h)."
        )
    if len(candidates) > 1:
        raise AmbiguousResumeError([candidate.run_id for candidate in candidates])
    return candidates[0]
