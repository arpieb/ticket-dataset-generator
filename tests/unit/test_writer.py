"""Output order and the destination claim (FR-012, FR-012c, FR-014, FR-014a)."""

import json
from pathlib import Path

import pytest

from ticket_dataset_generator.errors import OutputPathExistsError
from ticket_dataset_generator.run.writer import (
    OrderedWriter,
    claim_destination,
    serialize,
    verify_claim,
)


def _record(position: int) -> dict:
    return {"record_index": position, "content": f"record {position}"}


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_records_are_written_in_position_order(tmp_path: Path) -> None:
    # The property that makes two runs comparable record by record: completion order is not
    # write order (FR-012c).
    path = tmp_path / "out.jsonl"
    writer = OrderedWriter(path=path)
    writer.open()
    for position in (3, 1, 4, 0, 2):
        writer.submit(position, _record(position))
    writer.close()
    assert [line["record_index"] for line in _lines(path)] == [0, 1, 2, 3, 4]


def test_completion_order_does_not_change_the_bytes(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    for path, order in ((first, range(5)), (second, [4, 2, 0, 3, 1])):
        writer = OrderedWriter(path=path)
        writer.open()
        for position in order:
            writer.submit(position, _record(position))
        writer.close()
    assert first.read_bytes() == second.read_bytes()


def test_the_buffer_stays_bounded_by_the_gap(tmp_path: Path) -> None:
    # Memory must not grow with corpus size (FR-012): at most the in-flight window is held.
    writer = OrderedWriter(path=tmp_path / "out.jsonl")
    writer.open()
    for position in range(1, 9):
        writer.submit(position, _record(position))
        assert writer.buffered <= 8
    assert writer.records_written == 0  # everything waits on position 0
    writer.submit(0, _record(0))
    assert writer.buffered == 0
    assert writer.records_written == 9
    writer.close()


def test_a_skipped_position_does_not_block_the_rest(tmp_path: Path) -> None:
    # A discarded slot must not stall every later record behind it.
    path = tmp_path / "out.jsonl"
    writer = OrderedWriter(path=path)
    writer.open()
    writer.submit(1, _record(1))
    writer.skip(0)
    writer.close()
    assert [line["record_index"] for line in _lines(path)] == [1]


def test_a_submit_drains_past_a_buffered_skip(tmp_path: Path) -> None:
    # The other direction of the same interleaving: the discard arrives first and parks itself,
    # and it is the earlier success that walks past it. Serializing that sentinel put literal
    # `null` lines into the corpus, which every later reader of the file then choked on.
    path = tmp_path / "out.jsonl"
    writer = OrderedWriter(path=path)
    writer.open()
    writer.skip(1)
    writer.submit(2, _record(2))
    assert writer.submit(0, _record(0)) == 2
    writer.close()
    assert [line["record_index"] for line in _lines(path)] == [0, 2]
    assert "null" not in path.read_text()
    assert writer.records_written == 2
    assert writer.bytes_written == path.stat().st_size
    assert writer.resume_position == 3  # position 2 was the last one to produce a record


def test_rewriting_an_earlier_position_is_an_error(tmp_path: Path) -> None:
    writer = OrderedWriter(path=tmp_path / "out.jsonl")
    writer.open()
    writer.submit(0, _record(0))
    with pytest.raises(ValueError, match="already written"):
        writer.submit(0, _record(0))
    writer.close()


def test_bytes_written_tracks_the_file(tmp_path: Path) -> None:
    # The checkpoint points at this number, so it must match the file exactly (research R6).
    path = tmp_path / "out.jsonl"
    writer = OrderedWriter(path=path)
    writer.open()
    for position in range(5):
        writer.submit(position, _record(position))
    writer.close()
    assert writer.bytes_written == path.stat().st_size


def test_reopening_truncates_to_the_checkpointed_length(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    writer = OrderedWriter(path=path)
    writer.open()
    for position in range(3):
        writer.submit(position, _record(position))
    checkpoint = writer.bytes_written
    writer.submit(3, _record(3))  # written after the checkpoint, so it must not survive
    writer.close()

    resumed = OrderedWriter(path=path)
    resumed.open(start_position=3, truncate_to=checkpoint)
    resumed.submit(3, _record(3))
    resumed.close()
    assert [line["record_index"] for line in _lines(path)] == [0, 1, 2, 3]


def test_serialization_is_deterministic() -> None:
    assert serialize({"b": 1, "a": 2}) == serialize({"a": 2, "b": 1})


def test_serialization_keeps_non_latin_content_readable() -> None:
    assert "注文" in serialize({"content": "注文が届きません"})


# --- the destination claim (FR-014, FR-014a) -----------------------------------------------


def test_claiming_a_free_path_succeeds(tmp_path: Path) -> None:
    claim_destination(tmp_path / "free.jsonl")


def test_claiming_an_occupied_path_is_refused(tmp_path: Path) -> None:
    occupied = tmp_path / "taken.jsonl"
    occupied.write_text("")
    with pytest.raises(OutputPathExistsError, match="no overwrite flag"):
        claim_destination(occupied)


def test_a_destination_taken_mid_run_is_caught_before_the_move(tmp_path: Path) -> None:
    # Checking only at the start lets two concurrent runs both pass and the second replace the
    # first's output at the end (FR-014a).
    path = tmp_path / "contested.jsonl"
    claim_destination(path)
    path.write_text("another run got here first")
    with pytest.raises(OutputPathExistsError, match="another run"):
        verify_claim(path)
