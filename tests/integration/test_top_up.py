"""Making the corpus hold the number that was asked for (FR-040).

A discard used to come straight off the top of the corpus: a run asked for N records, attempted
N slots, and published whatever survived. These tests pin the replacement behaviour that makes
`record_count` a statement about the corpus rather than about how many slots were attempted.
"""

import collections
import json
from collections.abc import Callable
from pathlib import Path

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.model.client import ModelResponse, ModelRole
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.run.checkpoint import CHECKPOINT_NAME, Checkpoint
from ticket_dataset_generator.run.enums import RunOutcome
from ticket_dataset_generator.run.manifest import validate_manifest_file
from ticket_dataset_generator.run.run import GenerationRun

CRITERIA = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    base = {
        "record_count": 200,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "max_concurrency": 8,
        "max_attempts_per_slot": 1,
        # These tests are about the shortfall, not about the discard-rate gates; let the rates
        # run high without the run being stopped for them.
        "coherence": {"max_discard_rate": 1.0},
        "privacy": {"max_discard_rate": 1.0},
    }
    return GenerationConfig(**{**base, **overrides})


def _judge_rejecting(reject: Callable[[str, int], bool]) -> FakeModelClient:
    """A fake whose judge rejects the candidates ``reject`` selects.

    ``reject`` is handed the judge's prompt — which names the slot's assigned category,
    priority, channel, resolution status and subdomain — and the index of this judging call.
    Selecting on the assignment is what lets a test make one category systematically harder
    than the rest, which is the case the deficit-driven top-up exists for.
    """
    judged = collections.Counter[str]()

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            judged["n"] += 1
            score = 0.1 if reject(user, judged["n"]) else 0.95
            return ModelResponse(
                text=json.dumps(
                    {"criteria": dict.fromkeys(CRITERIA, score), "justification": "scripted"}
                ),
                model_id="fake-model-1",
            )
        count = int(user.split("turn_count=")[1].split("\n")[0])
        return ModelResponse(
            text=json.dumps(
                {
                    "scenario": "a situation",
                    "turns": [
                        {"role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
                        for i in range(count)
                    ],
                }
            ),
            model_id="fake-model-1",
        )

    return FakeModelClient(responder=responder)


def _every_fifth(_prompt: str, call: int) -> bool:
    return call % 5 == 0


async def _run(config: GenerationConfig, client: FakeModelClient | None = None):
    return await GenerationRun(
        config=config, seed=7, model_client=client or FakeModelClient()
    ).execute()


async def test_discarded_records_are_replaced_up_to_the_requested_count(
    tmp_path: Path, staging_root: Path
) -> None:
    # A fifth of the candidates are rejected. Without top-up the corpus lands ~20% short.
    result = await _run(_config(tmp_path), _judge_rejecting(_every_fifth))

    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 200
    assert len(result.artifact_path.read_text().splitlines()) == 200
    # The discards really happened — otherwise this test proves nothing.
    assert sum(result.stats.discards.values()) > 0


async def test_replacements_take_positions_past_the_requested_count(
    tmp_path: Path, staging_root: Path
) -> None:
    # Replacements get fresh positions rather than reusing discarded ones, so writes stay
    # strictly ascending and the staging file stays a prefix of the corpus (research R6).
    result = await _run(_config(tmp_path), _judge_rejecting(_every_fifth))

    indices = [
        json.loads(line)["record_index"] for line in result.artifact_path.read_text().splitlines()
    ]
    assert indices == sorted(indices), "records must stay in ascending position order"
    assert len(set(indices)) == len(indices), "a position was used twice"
    assert max(indices) >= 200, "no replacement was planned past the requested count"


async def test_record_identifiers_stay_unique_across_the_replacements(
    tmp_path: Path, staging_root: Path
) -> None:
    # Identifiers derive from (run_id, record_index), so fresh positions are what keeps
    # FR-015b true once a corpus contains replacements.
    result = await _run(_config(tmp_path), _judge_rejecting(_every_fifth))

    ids = [json.loads(line)["record_id"] for line in result.artifact_path.read_text().splitlines()]
    assert len(set(ids)) == len(ids) == 200


async def test_the_replacements_repair_composition_rather_than_diluting_it(
    tmp_path: Path, staging_root: Path
) -> None:
    # The records lost to discards are not a random sample: here one category is rejected far
    # more often than the rest. Replacing proportionally would leave that category short, so
    # the top-up draws from the deficit instead (FR-031, FR-040).
    def reject(prompt: str, _call: int) -> bool:
        return "category=billing" in prompt and _seen(prompt) % 2 != 0

    seen = collections.Counter[str]()

    def _seen(prompt: str) -> int:
        seen["billing"] += 1
        return seen["billing"]

    config = _config(tmp_path)
    result = await _run(config, _judge_rejecting(reject))

    assert result.outcome is RunOutcome.COMPLETED
    records = [json.loads(line) for line in result.artifact_path.read_text().splitlines()]
    assert len(records) == 200
    counts = collections.Counter(record["metadata"]["category"] for record in records)
    requested = config.effective_composition.as_dict()["category"]
    for member, want in requested.items():
        achieved = counts[member] / len(records)
        assert abs(achieved - want) <= 0.02, f"category.{member}: {achieved:.3f} vs {want}"


async def test_the_report_accounts_for_the_extra_generation(
    tmp_path: Path, staging_root: Path
) -> None:
    # Silently adding work would be as opaque as silently dropping records.
    result = await _run(_config(tmp_path), _judge_rejecting(_every_fifth))

    report = json.loads(result.report_path.read_text())
    assert report["records_requested"] == 200
    assert report["records_written"] == 200
    assert report["top_up"]["slots"] > 0
    assert report["top_up"]["rounds"] >= 1


async def test_a_run_that_cannot_fill_the_corpus_fails_rather_than_publishing_short(
    tmp_path: Path, staging_root: Path
) -> None:
    # One category is unproducible, so no number of replacement rounds will fill the corpus.
    # That is a failure with the output left in staging, not an artifact in the release path.
    def reject(prompt: str, _call: int) -> bool:
        return "category=billing" in prompt

    result = await _run(_config(tmp_path), _judge_rejecting(reject))

    assert result.outcome is RunOutcome.FAILED
    assert result.artifact_path is None
    assert any("records_written" in failure for failure in result.failures)
    assert any("200 requested" in failure for failure in result.failures)


async def test_the_ceiling_bounds_the_extra_generation(tmp_path: Path, staging_root: Path) -> None:
    # A generator that discards everything must not loop forever. The ratio is the ceiling on
    # replacement slots across every round.
    def reject(_prompt: str, _call: int) -> bool:
        return True

    run = GenerationRun(
        # The consecutive-failure breaker is held off so the main wave finishes and the top-up
        # is actually reached; the ceiling, not the breaker, is what this test is about.
        config=_config(tmp_path, max_top_up_ratio=0.25, consecutive_failure_limit=1000),
        seed=7,
        model_client=_judge_rejecting(reject),
    )
    result = await run.execute()

    assert result.outcome is RunOutcome.FAILED
    assert result.records_written == 0
    assert run.top_up_slots <= 50  # 0.25 of 200
    assert run.top_up_rounds == 1  # a round that produced nothing is not repeated


async def test_top_up_can_be_turned_off(tmp_path: Path, staging_root: Path) -> None:
    # Off, the old behaviour returns — but the shortfall is now a failure rather than silence.
    result = await _run(_config(tmp_path, top_up=False), _judge_rejecting(_every_fifth))

    assert result.records_written < 200
    assert result.outcome is RunOutcome.FAILED
    assert any("set top_up = true" in failure for failure in result.failures)


async def test_a_clean_run_does_no_extra_work(tmp_path: Path, staging_root: Path) -> None:
    # Nothing is discarded, so the top-up must not plan a single replacement slot.
    run = GenerationRun(config=_config(tmp_path), seed=7, model_client=FakeModelClient())
    result = await run.execute()

    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 200
    assert run.top_up_slots == 0
    assert run.top_up_rounds == 0


def _dying_client(fail_after: int) -> FakeModelClient:
    """A client that stops answering after ``fail_after`` generation calls, as a kill would."""
    generated = collections.Counter[str]()

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            return ModelResponse(
                text=json.dumps({"criteria": dict.fromkeys(CRITERIA, 0.95), "justification": "ok"}),
                model_id="fake-model-1",
            )
        generated["n"] += 1
        if generated["n"] > fail_after:
            from ticket_dataset_generator.model.client import ModelUnavailable

            raise ModelUnavailable("provider went away")
        count = int(user.split("turn_count=")[1].split("\n")[0])
        return ModelResponse(
            text=json.dumps(
                {
                    "scenario": "a situation",
                    "turns": [
                        {"role": "customer" if i % 2 == 0 else "agent", "content": f"turn {i}"}
                        for i in range(count)
                    ],
                }
            ),
            model_id="fake-model-1",
        )

    return FakeModelClient(responder=responder)


async def test_a_resumed_run_tops_up_from_what_is_on_disk(
    tmp_path: Path, staging_root: Path
) -> None:
    # The resumed process never saw which slots were discarded. It recomputes the deficit by
    # reading the corpus it inherited, which is what keeps the top-up correct across a restart
    # without carrying per-slot state in the checkpoint.
    config = _config(
        tmp_path,
        record_count=100,
        composition_tolerance_pp=10.0,
        consecutive_failure_limit=3,
        checkpoint_interval=5,
        max_concurrency=1,
    )

    first = await GenerationRun(
        config=config, seed=11, model_client=_dying_client(fail_after=30)
    ).execute()
    assert first.outcome is RunOutcome.STOPPED
    assert first.records_written < 100

    resumed = GenerationRun(config=config, seed=11, model_client=_judge_rejecting(_every_fifth))
    result = await resumed.resume()

    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 100
    records = [json.loads(line) for line in result.artifact_path.read_text().splitlines()]
    assert len(records) == 100
    indices = [record["record_index"] for record in records]
    assert indices == sorted(indices)
    assert len(set(indices)) == 100
    assert len({record["record_id"] for record in records}) == 100


async def test_the_top_up_ceiling_is_carried_across_a_resume(
    tmp_path: Path, staging_root: Path
) -> None:
    # Spent budget lives in the checkpoint. Resetting it per resume would make the ceiling no
    # ceiling at all: resume often enough and the run generates without bound.
    def reject(prompt: str, _call: int) -> bool:
        return "category=billing" in prompt

    def config() -> GenerationConfig:
        return _config(
            tmp_path,
            record_count=100,
            composition_tolerance_pp=10.0,
            max_top_up_ratio=0.25,
            # Held off so the main wave finishes and the top-up is reached.
            consecutive_failure_limit=1000,
        )

    first = GenerationRun(config=config(), seed=11, model_client=_judge_rejecting(reject))
    assert (await first.execute()).outcome is RunOutcome.FAILED
    # A failed run keeps its staging directory, which is where the checkpoint lives.
    checkpoint = Checkpoint.read(first.staging_dir / CHECKPOINT_NAME)
    assert checkpoint.top_up_slots == first.top_up_slots > 0

    second = GenerationRun(config=config(), seed=11, model_client=_judge_rejecting(reject))
    await second.resume()
    assert second.top_up_slots >= checkpoint.top_up_slots, "the ceiling reset on resume"


async def test_the_manifest_still_reconciles_with_replacements_in_the_corpus(
    tmp_path: Path, staging_root: Path
) -> None:
    # FR-026's balance is what the manifest validator enforces. Top-up adds both responses and
    # outcomes, so it has to hold across the replacement rounds too.
    result = await _run(_config(tmp_path), _judge_rejecting(_every_fifth))

    assert validate_manifest_file(result.manifest_path) == []
    manifest = json.loads(result.manifest_path.read_text())
    discarded = sum(entry["count"] for entry in manifest["discards"])
    assert manifest["records_generated"] - discarded == manifest["records_written"] == 200
