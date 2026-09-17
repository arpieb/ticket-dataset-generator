# Phase 1 Data Model: Ticket Generation Pipeline

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-19

Entities are drawn from the spec's Key Entities section; every validation rule traces to the requirement
that mandates it. All models are Pydantic v2. The record model is authoritative and exports
[contracts/record.schema.json](./contracts/record.schema.json) (Principle I).

Three families live here and should not be confused:

| Family | Purpose | Persisted as |
|--------|---------|--------------|
| **Record contract** | What the generator writes and downstream consumers read | JSONL under `data/release/` |
| **Run state** | Config, manifest, checkpoint, report — how one run happened | JSON beside the artifact and under `data/interim/` |
| **Wire models** | What the model is asked to return, before it is a record | never persisted |

---

## Enumerations

| Enum | Values | Source |
|------|--------|--------|
| `Role` | `customer`, `agent` | FR-005. Two-party by default (spec Assumptions); adding a member is an additive MINOR change |
| `Category` | `billing`, `technical`, `account`, `shipping`, `product`, `other` | FR-006 |
| `Priority` | `low`, `normal`, `high`, `urgent` | FR-006 |
| `Channel` | `email`, `chat`, `phone`, `web_form` | FR-006 |
| `ResolutionStatus` | `resolved`, `unresolved`, `escalated`, `abandoned` | FR-006 |
| `PIICategory` | Blocking floor: `EMAIL`, `PHONE`, `CREDIT_CARD`, `US_SSN`. Advisory (reported, never blocking): `IP_ADDRESS` | FR-018 floor at identifier-type level; advisory tier per FR-018b; R8. Postal code is excluded from both tiers — it matches ordinary order and account numbers, and joins the declared gaps |
| `DiscardReason` | `structural_invalid`, `turn_count_out_of_range`, `schema_invalid`, `coherence_below_threshold`, `unjudgeable`, `privacy_finding`, `detector_error`, `model_refusal`, `attempts_exhausted` | **FR-026b** enumerates this closed set normatively; each member maps to exactly one requirement. `detector_error` is deliberately distinct from `privacy_finding`: a malfunctioning detector is neither a clean result nor a real identifier (FR-017a) |
| `Verdict` | `pass`, `fail` | FR-036 |
| `RunOutcome` | `completed`, `refused`, `failed`, `stopped` | FR-036b. Four states because they call for different responses: nothing spent, output that did not qualify, and resumable work are not the same fact |

`Role`, `Category`, `Priority`, `Channel`, and `ResolutionStatus` are **closed sets** — any other value is a
validation failure (FR-005, FR-006). Removing a member or tightening a constraint is a breaking change
requiring a MAJOR bump (Principle I).

`DiscardReason` is closed on purpose and closed **by requirement** (FR-026b), not by design preference:
FR-026 requires records generated − discards = records written, and an open-ended reason string makes that
reconciliation a sum over free text. Adding a reason is a MINOR change to the manifest contract.

---

## Record contract

### TicketRecord

`SCHEMA_VERSION = "1.0.0"`. One record is one complete multi-turn support interaction.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `schema_version` | `str` | yes | `MAJOR.MINOR.PATCH` (FR-002). Every record declares the version it was written against |
| `record_id` | `str` | yes | UUIDv5 over `f"{run_id}/{record_index}"` in a project namespace (FR-003b). Unique within a run structurally; unique across runs because `run_id` is fresh per run instance (FR-003a). A resumed run regenerating a position yields the identifier that position always had, so FR-015b holds by construction |
| `run_id` | `str` | yes | UUIDv4 generated once per run instance and carried in the checkpoint, so a resume keeps it and a rerun gets a new one (FR-003a). Names the manifest file, so a record locates its own provenance (FR-029a) |
| `record_index` | `int` | yes | ≥ 0. The slot this record occupies in the run. Ascending and distinct within a corpus, but **not dense**: discarded positions leave gaps and FR-040b's replacements sit past `record_count`, so a complete corpus of N records has a maximum index ≥ `N - 1`. Makes SC-013's per-position comparison possible |
| `source_id` | `str` | yes | The domain prompt document identity: `f"{name}@{sha256[:12]}"` (FR-003, FR-008a) |
| `subdomain` | `str` | yes | The subdomain assigned to this slot by a seeded choice from the prompt document's declared list (FR-008d, FR-012b). Reproducible from `(seed, position)` — this is what makes deterministic stratification possible |
| `scenario` | `str` | yes | The specific situation the model elaborated within that subdomain, non-empty (FR-008b). Model text, not reproducible. `source_id` is common to every record and cannot serve either purpose |
| `metadata` | `TicketMetadata` | yes | See below (FR-006) |
| `turns` | `list[ConversationTurn]` | yes | Length within the configured range; ordering, alternation, and non-emptiness enforced (FR-009, FR-009d) |
| `quality` | `RecordQuality` | yes | See below (FR-009i) |
| `generation` | `GenerationInfo` | yes | See below (FR-027) |

**Relationships**: 1→N `ConversationTurn` (ordered); 1→1 `TicketMetadata`; N→1 `RunManifest` via `run_id`.

**Traceability (FR-029, FR-029a)**: `run_id` + `record_index` + `source_id` + `schema_version` are
sufficient to locate the manifest, the slot, the prompt document version, and the contract — using only the
record's own fields and no external index. The manifest is *findable* because it is named `<run_id>.manifest.json`
beside the artifact; without that naming rule the claim would be unachievable, since a record carries an
identifier rather than a path.

### ConversationTurn

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `index` | `int` | yes | ≥ 0; ascends contiguously from 0 within a record (FR-004, FR-009) |
| `role` | `Role` | yes | Closed set (FR-005). Turn 0 is `customer` — the party raising the issue opens, by requirement rather than convention — and roles alternate strictly (FR-009) |
| `content` | `str` | yes | Not empty and not whitespace-only (FR-009). Any Unicode — non-Latin, emoji, RTL — is valid (spec Edge Cases); no maximum length is assumed |

There is no per-turn timestamp: FR-004 requires role, position, and content, and a fabricated per-turn clock
would be provenance-shaped noise. Adding one later is an additive MINOR change.

### TicketMetadata

Every field here is **assigned by the pipeline before the model is called** (research R3), not chosen by the
model — timestamps included (FR-006a). That is what makes FR-031's tolerance achievable by construction and
what makes FR-012b's list of seeded choices exhaustive rather than merely illustrative.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `category` | `Category` | yes | Closed set; assigned by apportionment (FR-006, FR-030) |
| `priority` | `Priority` | yes | Closed set; assigned by apportionment |
| `channel` | `Channel` | yes | Closed set; assigned by apportionment |
| `resolution_status` | `ResolutionStatus` | yes | Closed set; assigned by apportionment |
| `created_at` | `datetime` | yes | Timezone-aware. A **seeded draw** from the configured date window, made with the slot's own generator — never model output, never wall-clock (FR-006a) |
| `resolved_at` | `datetime \| None` | no | `created_at` plus a seeded duration. Present when — and only when — `resolution_status` is `resolved`, by requirement rather than convention (FR-006b) |

### RecordQuality

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `coherence_score` | `float` | yes | `0.0 ≤ score ≤ 1.0`, and `≥` the run's configured threshold — a record below it never reaches the corpus (FR-009h, FR-009i, SC-009) |
| `rubric_id` | `str` | yes | Identifies the rubric version that produced the score (FR-009g, FR-009p); a score is meaningless without it, because the criteria and weights that produced it live in the rubric |

### GenerationInfo

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `model_id` | `str` | yes | The model that **actually** produced the text, which a refusal fallback can change mid-run. Required per record by FR-027a: a single run-level identity would be false for part of the corpus, and provenance false for an unidentifiable subset is worse than none |
| `judge_model_id` | `str` | yes | The model that actually scored the record, for the same reason |

---

## Run state

### GenerationConfig

The single serialized object that is the run's only configuration input (FR-008). Recorded verbatim in the
manifest and hashed into the checkpoint's input fingerprint set.

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| `record_count` | `int` | — | ≥ 1. Zero is a configuration error, not an empty corpus (spec Edge Cases) |
| `output_path` | `path` | — | Must be under `data/release/`; must not already exist (FR-013, FR-014) |
| `prompt_document` | `path` | `prompts/samples/consumer-electronics-support.md` | Must exist; hashed as a run input (FR-008a) |
| `rubric` | `path` | `prompts/coherence-rubric.md` | Must exist; hashed as a run input (FR-009g) |
| `composition` | `Composition \| None` | `None` | When absent, the documented default distribution applies (FR-033) |
| `turns.min` / `turns.max` | `int` | `4` / `12` | `2 ≤ min ≤ max` (FR-009e); each conversation's length is drawn **uniformly** from the range with the slot's own generator (FR-009d, FR-033) |
| `language` | `str` | `en` | The language conversations are generated in; recorded in the manifest so a corpus states its language rather than inheriting it from the prompt (FR-009r) |
| `time_window.from` / `.to` | `date` | last 180 days | The window ticket creation times are drawn from (FR-006a). `from` must precede `to` |
| `resolution_duration.min` / `.max` | `duration` | `1h` / `14d` | Bounds on the seeded gap between creation and resolution (FR-006a) |
| `coherence.threshold` | `float` | `0.8` | `0.0–1.0` (FR-009h) |
| `coherence.max_discard_rate` | `float` | `0.10` | `coherence_below_threshold` discards ÷ `records_generated` (FR-026a). Exceeding it fails the run (FR-009k) |
| `privacy.max_discard_rate` | `float` | `0.005` | `privacy_finding` discards ÷ `records_generated` (FR-026a). Exceeding it fails the run (FR-021a) |
| `composition_tolerance_pp` | `float` | `2.0` | Percentage points, evaluated **per member** of each dimension; the worst member decides (FR-031). Must be ≥ `100 / record_count`, or the run refuses before generating (FR-031b) |
| `models.generator` / `models.judge` | `ModelSpec` | `anthropic/claude-opus-4-5` | A litellm model string, `max_tokens`, optional `fallback_models`, and a pass-through `extra` for provider-specific settings. All recorded in the manifest, because anything that shapes output is provenance (FR-027) |
| `max_concurrency` | `int` | `8` | ≥ 1 (FR-012a) |
| `requests_per_minute` | `int` | `1000` | ≥ 1; the run's self-imposed bound (FR-012e) |
| `max_attempts_per_slot` | `int` | `3` | ≥ 1. The **single** knob for every retryable per-record failure — refusal, unparseable or invalid response, unscorable record alike (FR-009o). Distinct from transport retries, which the SDK owns and FR-012d reports separately. Exhausting it discards the slot as `attempts_exhausted` |
| `consecutive_failure_limit` | `int` | `50` | Stops and checkpoints rather than burning the corpus (spec Edge Cases) |
| `checkpoint_interval` | `int` | `100` | Records between checkpoints (FR-015a) |
| `top_up` | `bool` | `true` | Generate replacement slots until the corpus holds `record_count` records (FR-040). Off, the run attempts exactly `record_count` slots and keeps what survives |
| `max_top_up_ratio` | `float` | `0.5` | ≥ 0. Ceiling on replacement slots as a fraction of `record_count`, across every round and every resume. Reaching it with the corpus still short fails the run (FR-040c) |
| `budget.max_runtime` | `duration \| None` | `None` | Wall-clock ceiling; exhausting it stops and checkpoints rather than failing (FR-012f) |
| `budget.max_model_calls` | `int \| None` | `None` | Call ceiling, counting generation and judging alike (FR-012f) |

**Validation is total and up front (FR-011)**: an invalid or internally contradictory configuration — an
unsatisfiable composition, an inverted turn range, a threshold outside `[0,1]`, an existing output path —
refuses the run before any model call, naming the specific problem.

### Composition

Four **independent** distributions, one per controlled dimension. Each maps enum member → proportion; each
must sum to `1.0` within a small epsilon, and may name only members of its enum (FR-030, FR-032).
Apportionment to integer slot counts uses the largest-remainder method (research R3), which bounds
per-member error below `1 / record_count` before any discard occurs — the basis for FR-031b's up-front
refusal.

Dimensions are apportioned separately, so any combination of the four may occur and no joint distribution
is expressible (spec Assumptions). An implausible pairing is the model's problem to render coherently and
the judge's to catch, not a composition concern.

**Documented default** — used when `composition` is absent. These values are **normative in the spec**
(FR-033), not chosen here; this table restates them:

| Dimension | Default distribution |
|-----------|----------------------|
| `category` | `billing` 0.25, `technical` 0.25, `account` 0.20, `shipping` 0.15, `product` 0.10, `other` 0.05 |
| `priority` | `low` 0.20, `normal` 0.50, `high` 0.20, `urgent` 0.10 |
| `channel` | `email` 0.40, `chat` 0.35, `phone` 0.15, `web_form` 0.10 |
| `resolution_status` | `resolved` 0.70, `unresolved` 0.10, `escalated` 0.15, `abandoned` 0.05 |

### Slot

Not persisted in the corpus; the unit of work the pipeline schedules. Every field is a pure function of
`(seed, position)` — computed before dispatch, never drawn from a shared stream (FR-012b).

| Field | Type | Rules |
|-------|------|-------|
| `position` | `int` | ≥ 0; the slot's position in the run, which becomes the record's `record_index`. Originally planned slots occupy `[0, record_count)`; FR-040b's replacement slots continue past it. "Slot position" is planning vocabulary; `record_index` is the contract field |
| `assignment` | `TicketMetadata` fields | The four apportioned dimensions plus derived timestamps |
| `turn_count` | `int` | Drawn **uniformly** from the configured range with the slot's own generator (FR-009d) |
| `created_at` / `resolved_at` | `datetime` | Seeded draws from the configured window and duration bounds (FR-006a) — assigned before dispatch like every other seeded choice |
| `subdomain` | `str` | Chosen from the prompt document's declared list with the slot's own generator (FR-008d); the elaborated scenario comes back on the record |
| `attempt` | `int` | 0-based; part of the derivation key, so a retry re-rolls rather than repeating |

### RunManifest

The record of how one run produced its output. Validatable; validation names any missing element (FR-028).

| Field | Type | Rules |
|-------|------|-------|
| `run_id` | `str` | Referenced by every record the run produced (FR-003), and **the manifest's own filename**: `<run_id>.manifest.json`, written beside the artifact (FR-029a) |
| `schema_version` | `str` | The contract version records were written against (FR-025) |
| `seed` | `int` | The explicit seed (FR-025, Principle II) |
| `config` | `object` | The full serialized configuration, verbatim (FR-025) |
| `code_revision` | `CodeRevision` | See below (FR-025, research R10) |
| `input_hashes` | `map[str, str]` | Path → `sha256`: prompt document, rubric, config file (FR-025, FR-008a, FR-009g) |
| `models` | `ModelRecord` | Generator and judge identity, parameters, and any sampling seed (FR-027, FR-009j) |
| `fallbacks_used` | `map[str, int]` | Model ID → count of records it served after a refusal fallback; empty when none (research R1) |
| `environment_overrides` | `map[str, str]` | Environment settings that could change model selection, routing, or parameters — endpoint, profile, inference region (FR-008c). **Credentials are never recorded**, here or anywhere (FR-008) |
| `budget` | `Budget \| None` | Declared ceilings and actual spend, with `exhausted` set when a ceiling stopped the run (FR-012f) |
| `started_at` / `completed_at` | `datetime` | Timezone-aware wall clock — required by FR-025, and a captured non-deterministic input (Principle II) |
| `records_generated` | `int` | Every response received from the generating model, counted once per attempt (FR-026a). The shared denominator for every rate expressed as a proportion of records generated |
| `records_written` | `int` | Records in the artifact |
| `discards` | `list[DiscardAccount]` | Every discarded record by count and reason (FR-026) |
| `retry_counts` | `map[str, int]` | Transport retries by class — distinct from discards (FR-012d) |
| `resumed_count` | `int` | How many times the run was resumed; `0` for an uninterrupted run (FR-015d) |
| `segments` | `list[Segment]` | One per run or resume: `code_revision`, `started_at`, `completed_at`, and the record range it produced (FR-015f). A changed revision does not refuse a resume; it is described instead |
| `duplicate_count` | `int` | Exact duplicate conversations produced within this run (FR-034, FR-039); never compared against earlier corpora |
| `composition_requested` / `composition_assigned` / `composition_achieved` | `Composition` | All three, always (FR-031a). Requested → assigned is apportionment error; assigned → achieved is discard-induced drift. Without the middle term a tolerance failure has no attributable cause |
| `coherence_score_distribution` | `Histogram` | Counts in fixed 0.05 buckets plus count, min, max, mean, median (FR-038, SC-009) |
| `output_filename` | `str` | The artifact this manifest describes (FR-025b) |
| `output_sha256` | `str` | Checksum of that artifact, so a manifest cannot be read beside a file it does not describe and post-hoc alteration is detectable (FR-025b) |

**Reconciliation rule (FR-026, FR-026a, SC-005)**:
`records_generated - sum(d.count for d in discards) == records_written`. It closes because every counted
response either becomes a written record or is discarded under exactly one reason — a slot retried three
times contributes three to `records_generated` and, if it never succeeds, three to the discard tallies.
A manifest failing this is invalid and validation names the discrepancy. This holds **across a resume**
because the tallies are carried in the checkpoint and merged into one manifest (FR-015c).

#### CodeRevision

| Field | Type | Rules |
|-------|------|-------|
| `commit` | `str \| None` | Git SHA, or `None` when unavailable |
| `dirty` | `bool` | True when the working tree had uncommitted changes (research R10) |
| `unavailable_reason` | `str \| None` | Set when `commit` is `None` |

A dirty or unavailable revision fails neither manifest validation nor the run (FR-025a): it records the
caveat truthfully rather than misrepresenting provenance. Weighing that caveat belongs to the separate act
of deciding to release.

#### ModelRecord / ModelSpec

| Field | Type | Rules |
|-------|------|-------|
| `model_id` | `str` | A litellm model string, e.g. `anthropic/claude-opus-4-5`. No vendor is pinned; the provider is a configuration choice (research R1) |
| `max_tokens` | `int` | Request ceiling |
| `fallback_models` | `list[str]` | Models tried when the configured one declines or fails (FR-009n). Empty by default: a corpus spanning several models is a fact a datasheet has to report, so rescue is opt-in |
| `extra` | `map[str, any]` | Provider-specific settings — reasoning effort, thinking budgets, safety settings. Untyped on purpose: typing them would put one vendor's vocabulary into a contract the requirements deliberately leave open |
| `sampling_seed` | `int \| None` | Recorded when the provider accepts one; `None` states plainly that none was used (FR-010) |

#### DiscardAccount

| Field | Type | Rules |
|-------|------|-------|
| `reason` | `DiscardReason` | Closed set — see Enumerations |
| `count` | `int` | ≥ 0 |

### Checkpoint

Persisted at `data/interim/<run_id>/checkpoint.json` (research R6). Removed on success along with the
staging file; retained in full when a run fails or is interrupted (FR-015i). An unreadable checkpoint
refuses the resume and preserves the partial output — restarting is an explicit operator action, never an
inference the tool makes on its own (FR-015g).

| Field | Type | Rules |
|-------|------|-------|
| `run_id` | `str` | Matches the staging directory |
| `next_position` | `int` | The first slot not yet written |
| `bytes_written` | `int` | Staging file length at the last durable point; resume truncates to it |
| `input_fingerprints` | `map[str, str]` | Config hash, seed, prompt document hash, rubric hash, schema version. A mismatch refuses the resume (FR-015e), and the same fingerprints are what `--resume` matches on to find its candidate run (FR-015h). The code revision is deliberately **not** among them (FR-015f) |
| `discards` | `list[DiscardAccount]` | Tallies so far (FR-015c) |
| `retry_counts` | `map[str, int]` | Retries so far |
| `duplicate_count` | `int` | Duplicates so far |
| `fingerprints_path` | `path` | Sidecar holding the duplicate-detection digests, so resume does not re-scan the corpus |
| `resumes` | `int` | Incremented on each resume (FR-015d) |
| `top_up_slots` | `int` | Replacement slots spent so far against `max_top_up_ratio`. Carried across resumes, because a ceiling that reset on each one would be no ceiling at all (FR-040c) |

### PrivacyFinding / ApprovedException

| Entity | Fields | Rules |
|--------|--------|-------|
| `PrivacyFinding` | `record_id`, `field`, `category`, `detector`, `status`, `masked` | **Never** carries the matched value (FR-020). `masked` is a deterministic, irreversible rendering preserving at most the non-identifying remainder — domain for an email, issuer range for a card, shape and length otherwise (FR-020a). `status` is `blocking`, `exempt_by_range` (FR-021c), or `approved` (FR-022) |
| `ApprovedException` | `fingerprint`, `category`, `reason`, `approved_by`, `approved_on` | `sha256(category + ":" + normalized_value)`; committed at `privacy/exceptions.json`; never the raw value (FR-022, research R9). Self-approval is permitted and recorded; approvals do not expire but every active one must appear in a release datasheet (FR-022a). The `reason` is itself scanned and refused if it trips a detector (FR-022b) |

### Quarantine

Records discarded for a privacy finding are appended to `data/interim/<run_id>/quarantine.jsonl` (FR-021b).
Without it, FR-022's approval has no input: the record is gone and FR-020 withholds the value.

| Property | Rule |
|----------|------|
| Location | Under `data/interim/` — never the release path, never committed (`data/` is git-ignored) |
| Contents | The full discarded record, plus the findings that flagged it. One entry per blocked **attempt**, including attempts a retry replaced (FR-021b) |
| Visibility | The run report names the quarantine path and its record count, so its existence is never implicit |
| Status | Not dataset output. Nothing downstream may read it as a corpus |
| Retention | Survives a successful run, unlike the staging file and checkpoint (FR-015i): it is the input to FR-022's approval and cannot be reconstructed without regenerating the corpus |

A quarantined record is fabricated content that a pattern detector found identifier-shaped — not a real
identifier — which is why retaining it is compatible with Principle IV (spec Assumptions).

### RunReport

One structured object drives the JSON output, the human-readable rendering, and the exit status — so the
three cannot disagree (FR-035, FR-036).

| Field | Type | Rules |
|-------|------|-------|
| `verdict` | `Verdict` | `fail` if any threshold was exceeded or the run stopped short (FR-036) |
| `outcome` | `RunOutcome` | `completed`, `refused`, `failed`, or `stopped` (FR-036b) — the distinction a bare verdict cannot carry |
| `run_id`, `schema_version` | `str` | Ties the report to the run and the contract |
| `records_generated` / `records_written` | `int` | (FR-035) |
| `discards` | `list[DiscardAccount]` | By reason (FR-035) |
| `privacy` | `PrivacyReport` | Findings with masked renderings; `detectors_run`; `covered_types` and `declared_gaps`, each at identifier-type level; per-category blocking status; `records_examined`; `fields_examined` (turn content and scenario — FR-023a); canary probe results; approved exceptions; and the quarantine path and count (FR-018a, FR-018b, FR-019, FR-020, FR-020a, FR-021b, FR-023, FR-023a) |
| `composition_requested` / `composition_assigned` / `composition_achieved` | `Composition` | All three (FR-031a) |
| `composition_breaches` | `list[Breach]` | Dimension, member, requested, achieved, and drift for every member exceeding the tolerance — a failure names the member, not just the dimension (FR-031) |
| `coherence_score_distribution` | `Histogram` | Counts in fixed 0.05 buckets across 0–1, plus count, min, max, mean, and median (FR-038). Fixed buckets make two runs comparable without re-deriving anything |
| `duplicate_count` | `int` | Within-run duplicates only, matched on the Unicode-normalized turn sequence with metadata excluded (FR-034, FR-039) |
| `retry_counts` | `map[str, int]` | (FR-012d) |
| `failures` | `list[str]` | Which threshold or condition failed the run, named specifically |

`declared_gaps` is populated on **every** report, clean or not — a clean result must never be mistaken for
coverage the scan does not provide (FR-019).

---

## Wire models — what the model returns

Never persisted. Kept deliberately separate from `TicketRecord`: the model supplies **content**, the
pipeline supplies **provenance and metadata**. A model that could write `record_id`, `run_id`, or
`coherence_score` could corrupt provenance, so those fields are not in its vocabulary.

### GeneratedConversation

| Field | Type | Rules |
|-------|------|-------|
| `scenario` | `str` | The specific situation elaborated **within the subdomain the slot assigned**; non-empty (FR-008b). The model is given the subdomain and does not choose it |
| `turns` | `list[{role, content}]` | Length must equal the slot's `turn_count`; roles must alternate starting with `customer`; content non-empty (FR-009, FR-009b, FR-009d) |

Any violation is a discard under `structural_invalid` or `turn_count_out_of_range` — never coerced into a
record (FR-009b, spec Edge Cases).

### JudgeVerdict

| Field | Type | Rules |
|-------|------|-------|
| `score` | `float` | `0.0–1.0`, normalized (FR-009f) |
| `criteria` | `map[str, float]` | One entry per criterion the rubric declares, each in `[0,1]`. The coherence score is their **weighted mean**, using the rubric's declared weights (FR-009p) — the pipeline computes it rather than trusting a score the model reports alongside its own sub-scores. Used during calibration; not persisted |
| `justification` | `str` | Short; not persisted (research R11) |

A response that cannot be parsed or validated after the configured retries is a discard under
`unjudgeable` — never an admitted unjudged record (FR-009l).

---

## State transitions

### Slot lifecycle

```text
assigned ──generate──> generated ──structural──> structured ──privacy scan──> clean
                          │                          │                │
                          │ refusal/unparseable      │ shape violation│ finding / detector failure
                          ▼                          ▼                ▼
                       retry (attempt+1) ─── exhausted ──> discarded(reason)
                                                                      │
                                            privacy_finding ──> quarantine.jsonl (FR-021b)

   clean ──judge──> scored ──schema validate──> valid ──> written
            │                    │
            │ below threshold    │ schema_invalid
            │ / unjudgeable      ▼
            ▼              discarded(schema_invalid) ──> accounted in manifest
      discarded(reason)
```

Order is load-bearing, and the scan sits **early** rather than last (FR-016a): it runs on every structurally
valid response, before the judge call. Nothing reaches the staging file — let alone the release path —
carrying an unreviewed finding (FR-016, FR-021), and two things improve by scanning before judging. PII
emission is measured across all usable output instead of only the part that survived the coherence gate,
which matters most exactly when the generator is worst; and no judging call is spent on a record about to be
discarded for privacy.

### Run lifecycle

```text
configured ──validate config──> ready ──assert detector floor──> generating ──> completed ──> released
     │                            │                                   │              │
     │ FR-011                     │ FR-018 (fails before generating)  │ interrupt or │ threshold exceeded
     │                            │                                   │ budget spent │
     ▼                            ▼                                   ▼              ▼
  refused                      refused                          checkpointed      failed (artifact not moved)
                                                                       │
                                                                       └── resume (inputs match) ──> generating
                                                                       └── inputs differ ──> refused (FR-015e)
```

A run that fails a threshold still writes its manifest and report — the accounting is the point — but the
staging artifact is **not** moved into `data/release/`. Failure is loud and the release path stays clean.
