"""Ordered, incremental output and the claim on the destination (FR-012, FR-012c, FR-014a).

Two properties matter here and neither is free.

**Order.** Records are written in ascending ``record_index`` regardless of the order slots
complete, so two runs of the same seed are comparable record by record. A reorder buffer bounded
by the concurrency level provides that while still writing incrementally: at most that many
records are ever held, so memory does not grow with the corpus.

**The destination.** The path is claimed at run start and re-verified immediately before the
artifact is placed there. Checking only at the start lets two concurrent runs both pass and the
second silently replace the first's output at the end.

The move into the release path lives here too, and it **refuses without the privacy gate**. That
is the structural form of the constitution's blocking-scan requirement: not a rule someone has to
remember, but a function that cannot be called successfully unless the gate demonstrated its
coverage for this run.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ticket_dataset_generator.errors import OutputPathExistsError, ReleaseGateError


def serialize(record: dict[str, Any]) -> str:
    """One JSONL line, deterministically.

    Identical record content yields identical bytes, so comparing two corpora is a diff rather
    than a parse (FR-012c). ``ensure_ascii`` stays off: escaping non-Latin content would triple
    the size of a multilingual corpus and make it unreadable in a terminal.
    """
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(slots=True)
class OrderedWriter:
    """Buffers out-of-order completions and appends them in position order."""

    path: Path
    _handle: Any = None
    _next_position: int = 0
    _pending: dict[int, dict[str, Any]] = field(default_factory=dict)
    bytes_written: int = 0
    records_written: int = 0
    #: The last position that actually produced a record. A resume continues from just after it,
    #: so slots that were attempted but produced nothing — a provider outage kills the tail of an
    #: interrupted run — get another attempt rather than being lost. Discards are already counted;
    #: what is not counted is a corpus quietly ending up smaller than it was asked for (FR-009c).
    last_written_position: int = -1

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def resume_position(self) -> int:
        """Where a resume should continue: just after the last record actually written."""
        return self.last_written_position + 1

    def open(self, *, start_position: int = 0, truncate_to: int | None = None) -> None:
        """Open the staging file, optionally truncating to a checkpointed length."""
        self._next_position = start_position
        self.last_written_position = start_position - 1
        if truncate_to is not None and self.path.exists():
            # Resume: the file is always a prefix of the corpus because writes are in position
            # order, which is what makes a byte offset a sufficient recovery point (research R6).
            with self.path.open("r+b") as handle:
                handle.truncate(truncate_to)
            self.bytes_written = truncate_to
        self._handle = self.path.open("a", encoding="utf-8")

    def submit(self, position: int, record: dict[str, Any]) -> int:
        """Offer a completed record; write everything now contiguous. Returns records written."""
        if position < self._next_position:
            raise ValueError(f"position {position} was already written")
        self._pending[position] = record
        return self._drain()

    def skip(self, position: int) -> int:
        """Mark a position as producing no record, so later ones are not blocked behind it."""
        if position < self._next_position:
            return 0
        self._pending[position] = None  # type: ignore[assignment]
        return self._drain()

    def _drain(self) -> int:
        """Write the contiguous run starting at the next position. Returns records written.

        Both entry points drain through here because either one can be the call that unblocks a
        buffered ``skip``: a discard at a later position parks its ``None`` sentinel, and it is
        the *earlier* success arriving afterwards that walks past it. A drain that serialized
        whatever it popped would write that sentinel out as a literal ``null`` line.
        """
        written = 0
        while self._next_position in self._pending:
            record = self._pending.pop(self._next_position)
            if record is not None:
                line = serialize(record) + "\n"
                self._handle.write(line)
                self.bytes_written += len(line.encode("utf-8"))
                self.records_written += 1
                self.last_written_position = self._next_position
                written += 1
            self._next_position += 1
        return written

    @property
    def buffered(self) -> int:
        """How many completions are waiting on an earlier position."""
        return len(self._pending)

    def flush(self) -> None:
        """Make everything written durable, so a checkpoint can point at it."""
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())

    def close(self) -> None:
        if self._handle is not None:
            self.flush()
            self._handle.close()
            self._handle = None


def claim_destination(path: Path) -> None:
    """Refuse a destination that already holds an artifact (FR-014, FR-014a).

    There is deliberately no overwrite option to pass here: the data directory is outside
    version control, so an overwritten corpus and its manifest are unrecoverable, and removing
    a release artifact stays a deliberate manual act rather than a flag in a script.
    """
    path = Path(path)
    if path.exists():
        raise OutputPathExistsError(
            f"{path} already exists. Remove it deliberately or choose another output path; "
            "there is no overwrite flag (FR-014)."
        )


def verify_claim(path: Path) -> None:
    """Re-check immediately before placing the artifact (FR-014a)."""
    if Path(path).exists():
        raise OutputPathExistsError(
            f"{path} was created by another run while this one was generating (FR-014a)."
        )


def publish(staging: Path, destination: Path, *, gate_passed: bool) -> Path:
    """Move a finished corpus into the release path (FR-015, FR-016, FR-018a).

    ``gate_passed`` is the registry's report that it demonstrated floor coverage for this run.
    Refusing without it is what makes "no unscanned output reaches the release path" a property
    of the code rather than a discipline: there is no other way to put a file there.

    The move itself is a single rename, so the artifact appears in the release path complete or
    not at all — a partial write, a crash, or a naming mistake cannot leave something that looks
    finished (FR-015).
    """
    if not gate_passed:
        raise ReleaseGateError(
            "refusing to publish: the privacy detector floor was not demonstrated for this run. "
            "Nothing may reach the release path that the gate has not examined "
            "(Constitution IV, FR-016, FR-018a)."
        )
    staging, destination = Path(staging), Path(destination)
    if not staging.exists():
        raise FileNotFoundError(f"nothing to publish: {staging} does not exist")
    verify_claim(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, destination)
    return destination
