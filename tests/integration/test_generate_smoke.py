"""US1 end to end: a corpus is produced and every record conforms (SC-002)."""

import json
from pathlib import Path

import pytest

from ticket_dataset_generator.config.defaults import DEFAULT_PROMPT_DOCUMENT
from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.model.client import ModelRole
from ticket_dataset_generator.model.fake import FakeModelClient, Script
from ticket_dataset_generator.run.enums import DiscardReason, RunOutcome
from ticket_dataset_generator.run.run import GenerationRun
from ticket_dataset_generator.schema.record import TicketRecord

RECORDS = 40


def make_config(tmp_path: Path, **overrides) -> GenerationConfig:
    # The tolerance tracks the corpus size: assigning whole records bounds per-member error at
    # 100/n, so a small fixture corpus would otherwise be refused before generating (FR-031b).
    count = overrides.get("record_count", RECORDS)
    base = {
        "record_count": RECORDS,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "composition_tolerance_pp": max(10.0, 100.0 / count),
        "max_concurrency": 4,
        "composition": {
            "category": {"billing": 0.5, "technical": 0.5},
            "priority": {"normal": 0.5, "high": 0.5},
            "channel": {"email": 0.5, "chat": 0.5},
            "resolution_status": {"resolved": 0.75, "escalated": 0.25},
        },
    }
    return GenerationConfig(**{**base, **overrides})


def _output(result) -> Path:
    """Where the corpus ended up: the published artifact on success, staging otherwise."""
    return result.artifact_path or result.staging_path


async def _run(config: GenerationConfig, client: FakeModelClient | None = None, seed: int = 42):
    run = GenerationRun(config=config, seed=seed, model_client=client or FakeModelClient())
    return await run.execute()


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_a_corpus_is_produced(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(make_config(tmp_path))
    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == RECORDS


async def test_every_record_conforms_to_the_contract(tmp_path: Path, staging_root: Path) -> None:
    # SC-002: 100% of records conform, verified by the generator's own pre-write check.
    result = await _run(make_config(tmp_path))
    for line in _output(result).read_text().splitlines():
        TicketRecord.model_validate_json(line)


async def test_positions_are_dense_and_ordered(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(make_config(tmp_path))
    indices = [record["record_index"] for record in _records(_output(result))]
    assert indices == list(range(RECORDS))


async def test_conversations_alternate_starting_with_the_customer(
    tmp_path: Path, staging_root: Path
) -> None:
    result = await _run(make_config(tmp_path))
    for record in _records(_output(result)):
        roles = [turn["role"] for turn in record["turns"]]
        assert roles[0] == "customer"
        assert all(a != b for a, b in zip(roles, roles[1:], strict=False))


async def test_turn_counts_stay_inside_the_configured_range(
    tmp_path: Path, staging_root: Path
) -> None:
    config = make_config(tmp_path, turns={"min": 4, "max": 6})
    result = await _run(config)
    lengths = {len(record["turns"]) for record in _records(_output(result))}
    assert lengths <= {4, 5, 6}


async def test_records_carry_their_provenance(tmp_path: Path, staging_root: Path) -> None:
    from ticket_dataset_generator.generation.rubric import load_rubric

    expected_rubric_id = load_rubric(Path("prompts/coherence-rubric.md")).rubric_id
    result = await _run(make_config(tmp_path))
    for record in _records(_output(result)):
        assert record["run_id"] == result.run_id
        assert record["schema_version"] == "1.0.0"
        # Derived from the committed document rather than spelled out, so renaming it is not
        # a test edit. What matters is that the record names the document it came from.
        assert record["source_id"].startswith(f"{Path(DEFAULT_PROMPT_DOCUMENT).name}@")
        assert record["subdomain"]
        assert record["generation"]["model_id"]
        # The rubric the run actually used, not a pinned version: a deliberate rubric bump is a
        # provenance change (FR-009g), while a record naming a rubric the run did not use is a bug.
        assert record["quality"]["rubric_id"] == expected_rubric_id


async def test_record_ids_are_unique(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(make_config(tmp_path))
    ids = [record["record_id"] for record in _records(_output(result))]
    assert len(set(ids)) == len(ids)


async def test_a_clean_run_publishes_to_the_release_path(
    tmp_path: Path, staging_root: Path
) -> None:
    config = make_config(tmp_path)
    result = await _run(config)
    assert result.artifact_path == Path(config.output_path)
    assert Path(config.output_path).exists()
    # The move is a rename, so the staging copy does not survive as a second copy of the corpus.
    assert not result.staging_path.exists()


async def test_publishing_refuses_without_the_gate(tmp_path: Path, staging_root: Path) -> None:
    # The structural form of the blocking-scan requirement: there is no other route to the
    # release path, and this one cannot be taken unless the floor was demonstrated
    # (Constitution IV, FR-016, FR-018a).
    from ticket_dataset_generator.errors import ReleaseGateError
    from ticket_dataset_generator.run.writer import publish

    staging = tmp_path / "staging.jsonl"
    staging.write_text("{}\n")
    with pytest.raises(ReleaseGateError, match="Constitution IV"):
        publish(staging, tmp_path / "release" / "corpus.jsonl", gate_passed=False)
    assert not (tmp_path / "release" / "corpus.jsonl").exists()


async def test_a_failed_run_leaves_the_release_path_empty(
    tmp_path: Path, staging_root: Path
) -> None:
    # Output that did not qualify stays in staging with its accounting; only a clean run
    # publishes (FR-021a).
    client = FakeModelClient(judge_score=0.1)
    config = make_config(tmp_path, record_count=8, max_attempts_per_slot=1)
    result = await _run(config, client)
    assert result.outcome is RunOutcome.FAILED
    assert result.artifact_path is None
    assert not Path(config.output_path).exists()
    assert result.failures and "coherence discard rate" in result.failures[0]


# --- failure paths, each accounted under one reason (FR-009b, FR-009m, FR-026a) -------------


async def test_malformed_responses_are_discarded_and_counted(
    tmp_path: Path, staging_root: Path
) -> None:
    client = FakeModelClient(scripts={ModelRole.GENERATOR: [Script(behavior="malformed")]})
    result = await _run(
        make_config(tmp_path, record_count=8, max_attempts_per_slot=2, top_up=False), client
    )
    assert result.records_written == 0
    assert result.stats.discards[DiscardReason.STRUCTURAL_INVALID] > 0
    # Every response is counted once per attempt, which is the denominator every rate uses.
    assert result.stats.records_generated == 8 * 2


async def test_a_refusal_has_its_own_reason(tmp_path: Path, staging_root: Path) -> None:
    client = FakeModelClient(scripts={ModelRole.GENERATOR: [Script(behavior="refusal")]})
    result = await _run(
        make_config(tmp_path, record_count=6, max_attempts_per_slot=1, top_up=False), client
    )
    assert result.stats.discards[DiscardReason.MODEL_REFUSAL] == 6
    assert DiscardReason.STRUCTURAL_INVALID not in result.stats.discards


async def test_a_low_score_is_discarded_under_coherence(tmp_path: Path, staging_root: Path) -> None:
    client = FakeModelClient(judge_score=0.1)
    result = await _run(
        make_config(tmp_path, record_count=6, max_attempts_per_slot=1, top_up=False), client
    )
    assert result.records_written == 0
    assert result.stats.discards[DiscardReason.COHERENCE_BELOW_THRESHOLD] == 6


async def test_a_wrong_turn_count_lands_under_its_own_reason(
    tmp_path: Path, staging_root: Path
) -> None:
    # A length the model would not honor is a different cause from output it could not form.
    payload = {
        "scenario": "a specific situation",
        "turns": [
            {"role": "customer", "content": "one"},
            {"role": "agent", "content": "two"},
        ],
    }
    client = FakeModelClient(
        scripts={ModelRole.GENERATOR: [Script(behavior="ok", payload=payload)]}
    )
    config = make_config(
        tmp_path, record_count=4, max_attempts_per_slot=1, turns={"min": 6, "max": 6}, top_up=False
    )
    result = await _run(config, client)
    assert result.stats.discards[DiscardReason.TURN_COUNT_OUT_OF_RANGE] == 4


async def test_a_discarded_slot_does_not_block_later_records(
    tmp_path: Path, staging_root: Path
) -> None:
    # One bad slot must not stall every record behind it in the ordered writer.
    calls = {"n": 0}

    def responder(role, system, user):
        from ticket_dataset_generator.model.client import ModelResponse

        if role is ModelRole.JUDGE:
            return ModelResponse(
                text=json.dumps(
                    {
                        "criteria": dict.fromkeys(
                            [
                                "single_issue",
                                "role_consistency",
                                "conversational_flow",
                                "metadata_fit",
                            ],
                            0.95,
                        ),
                        "justification": "ok",
                    }
                ),
                model_id="fake-model-1",
            )
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(text="{broken", model_id="fake-model-1")
        turn_count = int(user.split("turn_count=")[1].split("\n")[0])
        turns = [
            {"role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
            for i in range(turn_count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "situation", "turns": turns}), model_id="fake-model-1"
        )

    client = FakeModelClient(responder=responder)
    result = await _run(
        make_config(
            tmp_path, record_count=6, max_attempts_per_slot=1, max_concurrency=1, top_up=False
        ),
        client,
    )
    assert result.records_written == 5
    indices = [record["record_index"] for record in _records(_output(result))]
    assert indices == sorted(indices)
    assert len(indices) == 5


async def test_the_circuit_breaker_stops_a_doomed_run(tmp_path: Path, staging_root: Path) -> None:
    # Sustained failure stops and checkpoints rather than burning the remaining corpus.
    client = FakeModelClient(scripts={ModelRole.GENERATOR: [Script(behavior="unavailable")]})
    config = make_config(
        tmp_path,
        record_count=40,
        max_attempts_per_slot=1,
        consecutive_failure_limit=5,
        max_concurrency=1,
    )
    result = await _run(config, client)
    assert result.outcome is RunOutcome.STOPPED
