"""The gate blocks, and nothing unscanned reaches the release path (SC-004, FR-020, FR-021a)."""

import json
from pathlib import Path

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.model.client import ModelResponse, ModelRole
from ticket_dataset_generator.model.fake import FakeModelClient
from ticket_dataset_generator.run.enums import DiscardReason, FindingStatus, RunOutcome
from ticket_dataset_generator.run.run import GenerationRun

REAL_LOOKING_EMAIL = "jane.roe@acme-corp.co.uk"
FICTION_EMAIL = "j.doe@example.com"


def _config(tmp_path: Path, **overrides) -> GenerationConfig:
    base = {
        "record_count": 8,
        "output_path": tmp_path / "release" / "corpus.jsonl",
        "composition_tolerance_pp": 20.0,
        "max_attempts_per_slot": 1,
        # These tests count blocked records against a known number of planned slots. Top-up
        # would add replacement rounds — which the gate blocks just the same — and the counts
        # would then measure the ceiling rather than the gate (FR-040).
        "top_up": False,
        "composition": {
            "category": {"account": 0.5, "technical": 0.5},
            "priority": {"normal": 1.0},
            "channel": {"email": 1.0},
            "resolution_status": {"resolved": 1.0},
        },
    }
    return GenerationConfig(**{**base, **overrides})


def _client_emitting(text: str) -> FakeModelClient:
    """A generator that plants ``text`` in the first turn of every conversation."""

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            criteria = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]
            return ModelResponse(
                text=json.dumps({"criteria": dict.fromkeys(criteria, 0.95), "justification": "ok"}),
                model_id="fake-model-1",
            )
        count = int(user.split("turn_count=")[1].split("\n")[0])
        turns = [
            {
                "role": "customer" if i % 2 == 0 else "agent",
                "content": text if i == 0 else f"turn {i} of the exchange",
            }
            for i in range(count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "contact details", "turns": turns}),
            model_id="fake-model-1",
        )

    return FakeModelClient(responder=responder)


async def _run(config: GenerationConfig, client: FakeModelClient):
    return await GenerationRun(config=config, seed=42, model_client=client).execute()


async def test_a_planted_identifier_blocks_the_run(tmp_path: Path, staging_root: Path) -> None:
    config = _config(tmp_path)
    result = await _run(config, _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}"))

    assert result.outcome is RunOutcome.FAILED
    assert result.records_written == 0
    assert result.stats.discards[DiscardReason.PRIVACY_FINDING] == 8
    assert result.failures and "privacy discard rate" in result.failures[0]


async def test_nothing_reaches_the_release_path(tmp_path: Path, staging_root: Path) -> None:
    # SC-004: an end-to-end attempt that is blocked.
    config = _config(tmp_path)
    result = await _run(config, _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}"))
    assert result.artifact_path is None
    assert not Path(config.output_path).exists()


async def test_findings_name_the_record_without_the_value(
    tmp_path: Path, staging_root: Path
) -> None:
    result = await _run(_config(tmp_path), _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}"))
    blocking = [f for f in result.findings if f.blocks]
    assert blocking
    for finding in blocking:
        assert finding.record_id
        assert finding.field == "turns[0].content"
        assert finding.category.value == "EMAIL"
        assert finding.detector == "datafog-regex"
        # FR-020: the matched value is never reproduced, but the mask carries enough to judge.
        assert "jane.roe" not in finding.masked
        assert finding.masked.endswith("@acme-corp.co.uk")


async def test_blocked_records_are_quarantined(tmp_path: Path, staging_root: Path) -> None:
    # Without quarantine, FR-022's approval has no input: the record is gone and FR-020 withholds
    # the value (FR-021b).
    result = await _run(_config(tmp_path), _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}"))
    assert result.quarantine_count == 8
    assert result.quarantine_path is not None
    entries = [
        json.loads(line) for line in result.quarantine_path.read_text().splitlines() if line.strip()
    ]
    assert len(entries) == 8
    assert REAL_LOOKING_EMAIL in entries[0]["record"]["turns"][0]["content"]
    # Quarantine lives outside the release path and is never dataset output.
    assert "release" not in str(result.quarantine_path)


async def test_a_reserved_for_fiction_value_does_not_block(
    tmp_path: Path, staging_root: Path
) -> None:
    # The finding that would otherwise fail every realistic run: a synthetic address is reported
    # but exempt by range, so the corpus is produced (FR-021c).
    config = _config(tmp_path)
    result = await _run(config, _client_emitting(f"reach me at {FICTION_EMAIL}"))

    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 8
    assert Path(config.output_path).exists()
    assert result.findings
    assert all(f.status is FindingStatus.EXEMPT_BY_RANGE for f in result.findings)
    assert not any(f.blocks for f in result.findings)


async def test_the_scan_reports_what_it_examined(tmp_path: Path, staging_root: Path) -> None:
    result = await _run(_config(tmp_path), _client_emitting(f"reach me at {FICTION_EMAIL}"))
    report = result.scan_report()
    assert report.records_examined == 8
    assert report.fields_examined > 8  # turns plus a scenario per record
    assert report.detectors_run == ("datafog-regex",)
    assert "US_SSN" in report.covered_types
    assert any("postal" in gap for gap in report.declared_gaps)


async def test_the_scan_runs_before_the_judge(tmp_path: Path, staging_root: Path) -> None:
    # Scanning early measures PII emission across all usable output and spends no judging call
    # on a record about to be discarded for privacy (FR-016a).
    client = _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}")
    await _run(_config(tmp_path), client)
    judge_calls = [role for role, _ in client.calls if role is ModelRole.JUDGE]
    assert judge_calls == [], "a blocked record must not reach the judge"


async def test_an_attempt_a_retry_rescued_is_still_quarantined(
    tmp_path: Path, staging_root: Path
) -> None:
    """The count and the quarantine must not diverge (FR-021b, FR-026a).

    A slot that trips a privacy finding and then succeeds on retry records the discard either
    way — FR-026's arithmetic depends on it, and FR-021a's rate is the signal that a generator is
    emitting identifiers whether or not retries rescue the corpus. Quarantining only the slots
    that *also* failed would leave the report claiming findings nothing can show, and the
    rescued attempts are precisely the ones no other artifact records.
    """
    calls = {"n": 0}

    def responder(role: ModelRole, system: str, user: str) -> ModelResponse:
        if role is ModelRole.JUDGE:
            criteria = ["single_issue", "role_consistency", "conversational_flow", "metadata_fit"]
            return ModelResponse(
                text=json.dumps({"criteria": dict.fromkeys(criteria, 0.95), "justification": "ok"}),
                model_id="fake-model-1",
            )
        calls["n"] += 1
        count = int(user.split("turn_count=")[1].split("\n")[0])
        # Every first attempt trips; every retry is clean.
        planted = REAL_LOOKING_EMAIL if calls["n"] % 2 == 1 else "no identifiers here"
        turns = [
            {
                "role": "customer" if i % 2 == 0 else "agent",
                "content": f"reach me at {planted}" if i == 0 else f"turn {i}",
            }
            for i in range(count)
        ]
        return ModelResponse(
            text=json.dumps({"scenario": "contact details", "turns": turns}),
            model_id="fake-model-1",
        )

    config = _config(
        tmp_path,
        record_count=4,
        max_attempts_per_slot=2,
        max_concurrency=1,
        composition_tolerance_pp=50.0,
        privacy={"max_discard_rate": 1.0},
    )
    result = await _run(config, FakeModelClient(responder=responder))

    # Every slot succeeded on its retry, so the corpus is clean and complete...
    assert result.outcome is RunOutcome.COMPLETED
    assert result.records_written == 4
    # ...while the discards and the quarantine both record the blocked attempts.
    assert result.stats.discards[DiscardReason.PRIVACY_FINDING] == 4
    assert result.quarantine_count == 4, "a rescued attempt must still be retained"

    entries = [
        json.loads(line) for line in result.quarantine_path.read_text().splitlines() if line.strip()
    ]
    assert len(entries) == 4
    assert all(REAL_LOOKING_EMAIL in e["record"]["turns"][0]["content"] for e in entries)


async def test_the_report_and_the_quarantine_agree(tmp_path: Path, staging_root: Path) -> None:
    # The symptom that exposed the defect on a live run: three blocking findings reported against
    # zero quarantined records.
    result = await _run(_config(tmp_path), _client_emitting(f"reach me at {REAL_LOOKING_EMAIL}"))
    blocking = [f for f in result.findings if f.blocks]
    assert len(blocking) == result.quarantine_count
