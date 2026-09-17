# Configuration reference

Every setting a generation configuration accepts, with its type, default, and the constraint that
will refuse it.

A configuration is a TOML file passed to one command:

```
uv run ticket-dataset-generator generate --config <file> --seed <n>
```

No other subcommand reads it. `calibrate`, `privacy-scan`, `sample-for-review` and the rest are
driven entirely by flags.

Two rules govern the whole file:

- **Unknown keys are rejected.** The config model forbids extras, so a typo is a refusal naming
  the key, not a setting silently ignored.
- **Every problem is reported at once.** Validation runs before any model call, so an
  unsatisfiable request costs nothing. Shape problems — missing field, wrong type, out of range —
  come back together; semantic problems that need a built config object (an occupied output path,
  an unachievable tolerance, a missing prompt document) are reached on the next pass once the
  shape is valid.

To see a complete file with every default written out, ask a manifest for one:

```
uv run ticket-dataset-generator config-from-manifest data/release/<run_id>.manifest.json
```

---

## Required

| Key | Type | Constraint |
| --- | --- | --- |
| `record_count` | integer | ≥ 1 |
| `output_path` | string (path) | Must be under `data/release/`, and must not already exist |

`output_path` is constrained to `data/release/` so that release-path artifacts are
distinguishable from scratch work by location alone (FR-013). There is deliberately **no
overwrite flag**: `data/` is outside version control, so an overwritten corpus and its manifest
are unrecoverable (FR-014). Remove the file yourself, or choose another path.

`--out` on the command line overrides `output_path`, and is applied *before* validation rather
than after — otherwise a config recovered from a manifest would always be refused over the
destination the original run already published to.

## Inputs

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt_document` | string (path) | `prompts/samples/consumer-electronics-support.md` | Must exist |
| `rubric` | string (path) | `prompts/coherence-rubric.md` | Must exist |
| `language` | string | `"en"` | Language the conversations are written in (FR-009r) |

Both files are hashed into the manifest, and their digests are part of what `--resume` compares
before continuing a run. Editing either mid-run means the checkpoint no longer describes the same
work, and the resume is refused.

The manifest records only the **hash** of your prompt document, never its text. A domain document
that is not in version control therefore cannot be reproduced by anyone, including you.

## Composition

| Key | Type | Default |
| --- | --- | --- |
| `composition.category` | table of member → proportion | see below |
| `composition.priority` | table of member → proportion | see below |
| `composition.channel` | table of member → proportion | see below |
| `composition.resolution_status` | table of member → proportion | see below |
| `composition_tolerance_pp` | float | `2.0` (> 0, ≤ 100) |

Omit `[composition]` entirely and every dimension takes its documented default (FR-033):

| Dimension | Default distribution |
| --- | --- |
| `category` | `billing` 0.25, `technical` 0.25, `account` 0.20, `shipping` 0.15, `product` 0.10, `other` 0.05 |
| `priority` | `low` 0.20, `normal` 0.50, `high` 0.20, `urgent` 0.10 |
| `channel` | `email` 0.40, `chat` 0.35, `phone` 0.15, `web_form` 0.10 |
| `resolution_status` | `resolved` 0.70, `unresolved` 0.10, `escalated` 0.15, `abandoned` 0.05 |

Supplying `[composition]` at all means supplying **all four** dimensions — the table is
all-or-nothing, not per-dimension. Members you leave out of a dimension you do supply are simply
absent from the corpus.

The four dimensions are independent by design. Any combination of the four may occur, and no
joint distribution is expressible: an implausible pairing is the model's problem to render
coherently and the judge's to catch.

Valid members are closed sets:

- **category** — `billing`, `technical`, `account`, `shipping`, `product`, `other`
- **priority** — `low`, `normal`, `high`, `urgent`
- **channel** — `email`, `chat`, `phone`, `web_form`
- **resolution_status** — `resolved`, `unresolved`, `escalated`, `abandoned`

Three things get refused up front, each naming both remedies:

- **Proportions that do not sum to 1.0** within each dimension (a 1e-6 epsilon absorbs float
  noise).
- **A tolerance too tight for the corpus.** Composition is made correct by construction —
  requested proportions become whole-record counts by largest remainder before any model call —
  which bounds per-member error at `100 / record_count` percentage points. A 20-record corpus
  cannot honour the default ±2pp; it needs at least 50 records, or a tolerance of 5pp or wider.
  This is a necessary condition, not a sufficient one: meeting it does not guarantee the
  tolerance survives discards.
- **A share that rounds to zero.** `0.05` of 10 records is half a record. The refusal names the
  smallest representable share at that corpus size.

## Conversation shape

| Key | Type | Default | Constraint |
| --- | --- | --- | --- |
| `turns.min` | integer | `4` | ≥ 2 |
| `turns.max` | integer | `12` | ≥ 2, and ≥ `turns.min` |

Each conversation's length is drawn uniformly over `[min, max]`, which produces more long
conversations than a real support queue contains. The floor of 2 is the smallest exchange that
can be an exchange: one turn from each party.

## Time

| Key | Type | Default |
| --- | --- | --- |
| `time_window.start` | date | `2025-07-05` |
| `time_window.end` | date | `2026-01-01` |
| `resolution_duration.min` | duration | `PT1H` (1 hour) |
| `resolution_duration.max` | duration | `P14D` (14 days) |

Omitting `[time_window]` gives a 180-day window ending `2026-01-01`. `start` must precede `end`,
and `resolution_duration.min` must not exceed `max`.

Dates may be written as TOML's native date type (`start = 2025-01-01`, unquoted) or as a quoted
`"2025-01-01"`. Durations accept an ISO-8601 duration string (`"PT2H"`, `"P3D"`,
`"P1DT12H30M"`) or a plain integer count of seconds. Resolved configs are always written back in
ISO-8601 form.

## Quality gates

| Key | Type | Default | Range |
| --- | --- | --- | --- |
| `coherence.threshold` | float | `0.8` | 0.0 – 1.0 |
| `coherence.max_discard_rate` | float | `0.10` | 0.0 – 1.0 |
| `privacy.max_discard_rate` | float | `0.005` | 0.0 – 1.0 |
| `privacy.exceptions` | string (path) | `privacy/exceptions.json` | — |

`coherence.threshold` is the score a conversation must reach to enter the corpus.

The two `max_discard_rate` settings are the run-level ceilings on how often that gate, and the
privacy gate, may fire. Both are **re-evaluated as the run proceeds**, not only at completion: a
generator emitting identifiers on every record would otherwise cost a full release-scale run
before anyone was told. A breach stops and checkpoints the run, so the completed work survives.

Both divide by responses generated — every response counted once per attempt — which is the one
denominator every threshold uses, so a rate cannot be computed two ways.

Nothing is judged until `max(1000, 5% of record_count)` responses exist. Early in a run a single
discard is a huge proportion, and failing on it would fail runs that would have been fine. A
consequence worth knowing: **a run smaller than 1,000 records never trips the early stop at all**,
and its rates are assessed only in the final report.

`composition_tolerance_pp` is deliberately not part of this. A partial corpus has no achieved
composition — apportionment is only satisfied once every slot has been attempted — so an early
check would measure incompleteness rather than drift.

`privacy.max_discard_rate` is an **alarm, not a gate**. Every record with a privacy finding is
blocked and quarantined regardless of this number; raising it only concedes that the model's
instruction-following is imperfect and that you have accepted that. The 0.5% default assumes a
model that follows the prompt document almost always — a smaller model may not, and
`configs/samples/ollama-remote.toml` raises it to 5% with the reasoning written out. Treat a
sudden rise as the signal it is meant to be.

`privacy.exceptions` points at the approved-exception store that `privacy-approve` writes.
Exceptions are recorded as fingerprints, never as the values themselves.

## Models

Two roles, `generator` and `judge`, each taking the same fields. Both default to the same model,
and pointing them at different providers is a configuration change rather than a code change.

| Key | Type | Default |
| --- | --- | --- |
| `models.<role>.model_id` | string | `"anthropic/claude-opus-4-5"` |
| `models.<role>.max_tokens` | integer | `16000` (≥ 1) |
| `models.<role>.sampling_seed` | integer or absent | absent |
| `models.<role>.fallback_models` | array of strings | `[]` |
| `models.<role>.extra` | table | `{}` |
| `models.<role>.connection` | table | `{}` |

`model_id` is a litellm model string — `anthropic/claude-opus-5`, `openai/gpt-5`,
`vertex_ai/gemini-2.5-pro`, `ollama_chat/llama3.1`. Nothing about the provider is special-cased
here.

`sampling_seed` being absent states plainly that no sampling seed was used, rather than implying
a reproducibility the run cannot deliver. The run seed and the sampling seed are different
things: the former makes structure reproducible, the latter is a provider feature that may or may
not exist.

`fallback_models` names models to try when the configured one declines or fails. A rescued record
stays in the corpus and names its actual producer in its own provenance.

### `extra` versus `connection`

This distinction is the one people get wrong, and the validator will catch it.

**`extra`** carries provider-specific settings that *shape output* — reasoning effort, thinking
budgets, safety settings. It is passed through untyped and **recorded verbatim in the manifest**,
because anything that shapes output is provenance.

**`connection`** carries what it takes to *reach* the provider — endpoint, API version,
credentials. It is excluded from every serialisation, so it can never reach a manifest that ships
with a release. These settings do not shape output: the same model at a different address
produces the same distribution, so they were never provenance in the first place.

Putting a connection setting in `extra` is refused at load rather than recorded. The check
matches these substrings, case-insensitively, against the key name:

`api_key`, `api_base`, `api_version`, `base_url`, `auth`, `token`, `secret`, `password`,
`credential`, `organization`

That list only has to be good enough to catch a mistake — it is a diagnostic that redirects you
to `connection`, not the mechanism that keeps connection settings out of artifacts. That
mechanism is structural: `connection` is excluded from serialisation by the model itself.

Credentials are better supplied through the environment, which this pipeline never reads into an
artifact.

```toml
[models.generator]
model_id = "ollama_chat/llama3.1"
max_tokens = 4096

[models.generator.extra]        # recorded in the manifest
reasoning_effort = "high"

[models.generator.connection]   # never recorded anywhere
api_base = "http://ollama.internal:11434"
```

Because `connection` is never recorded, a config recovered with `config-from-manifest` comes back
without it. The command says so explicitly, naming which roles used which connection keys, so you
know what to supply yourself.

## Throughput and resilience

| Key | Type | Default | Constraint |
| --- | --- | --- | --- |
| `max_concurrency` | integer | `8` | ≥ 1 |
| `requests_per_minute` | integer | `1000` | ≥ 1 |
| `max_attempts_per_slot` | integer | `3` | ≥ 1 |
| `consecutive_failure_limit` | integer | `50` | ≥ 1 |
| `checkpoint_interval` | integer | `100` | ≥ 1 |
| `top_up` | boolean | `true` | — |
| `max_top_up_ratio` | float | `0.5` | ≥ 0 |

Self-hosted models are typically slower per call and have no provider-side rate limit worth
respecting — the bound that matters is your own server's concurrency. The Ollama samples drop to
`max_concurrency = 2` and `requests_per_minute = 120` for that reason.

`checkpoint_interval` should sit well inside the run's own length, or a resume has nothing recent
to resume from. An hour-long run checkpointing every 100 records may checkpoint once.

### Reaching the record count

A discarded record leaves a hole in the corpus. With `top_up = true` the run fills it: once every
requested slot has been attempted, it plans further slots — at positions past `record_count` — until
the corpus actually holds the number that was asked for. `record_count` is therefore a statement
about the corpus, not about how many slots were attempted.

The replacements are drawn from the **deficit** rather than from the requested distribution: what
apportionment assigned, minus what the corpus holds, per member of each dimension. Records lost to
discards are not a random sample — a category the generator handles badly is discarded more often —
so replacing proportionally would leave that category short. Repairing the deficit pulls achieved
composition back toward assigned instead.

`max_top_up_ratio` caps the replacement work at that fraction of `record_count`, across every round
and across resumes. Reaching the cap with the corpus still short **fails the run**: the output stays
in staging with its manifest and nothing is published. So does a round that produces no records at
all, which is what a systematically unproducible slice of the corpus looks like.

Two consequences are worth knowing before turning this on for a large run:

- **Cost becomes variable.** A run discarding 5% of its records spends roughly 5% more model calls.
  The run report states what was spent, under `top_up`.
- **`record_index` is not dense.** Discarded positions leave gaps and replacements sit past
  `record_count`, so a complete corpus of N records has N distinct ascending indices whose maximum
  exceeds `N - 1`. Which extra records a run produces is not seed-reproducible, because it depends
  on which records the judge discarded (FR-009q).

With `top_up = false` the run attempts exactly `record_count` slots and keeps whatever survives —
the older behaviour — but a corpus that comes up short is now reported as a failure rather than
published quietly.

## Budget

| Key | Type | Default |
| --- | --- | --- |
| `budget.max_runtime` | duration or absent | absent |
| `budget.max_model_calls` | integer or absent | absent |

Both absent means no ceiling. A declared ceiling **stops and checkpoints** the run rather than
failing it, so the work already done survives and `--resume` continues it.

```toml
[budget]
max_runtime = "PT2H"
max_model_calls = 5000
```

## Environment

Nothing in the environment is a configuration setting, but two categories of variable affect a
run and are handled deliberately differently.

**Credentials are never recorded, anywhere** — `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`. They are excluded by never being read, not by being
redacted afterwards: a value that is never read cannot be written by accident.

**Routing variables are recorded as provenance**, because a setting that changes which model
answers is exactly the hidden state a manifest exists to eliminate:

`ANTHROPIC_BASE_URL`, `ANTHROPIC_PROFILE`, `ANTHROPIC_AUTH_TOKEN_FILE`, `ANTHROPIC_WORKSPACE_ID`,
`ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`,
`AWS_REGION`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`

Of those, the two whose value is an *address* rather than a *selection* —
`ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN_FILE` — are recorded as `<set>` rather than by
value. That an override was in effect is provenance; where it pointed is deployment
infrastructure a published manifest should not carry.

## Where configs live

`configs/*` is gitignored apart from `configs/samples/`. Your own configs belong in `configs/`
and stay out of the repository — they tend to carry a host address or a model only you can reach,
which is nobody else's default. Nothing is lost by keeping them there: every manifest embeds the
full resolved config a run used, so a published corpus stays reproducible from its own artifacts.

The tracked samples are worked examples of most of the above:

| Sample | What it demonstrates |
| --- | --- |
| `smoke.toml` | 20 records, about 40 model calls; widens tolerance to 10pp because 20 records cannot hold 2pp |
| `smoke16.toml` | `smoke.toml` at `max_concurrency = 16`; the throughput comparison pair, identical otherwise |
| `medium.toml` | 200 records with a small `checkpoint_interval` — large enough to interrupt mid-flight and resume |
| `release.toml` | Release scale: 100,000 records, with the `[budget]` ceiling an unattended run needs |
| `billing-heavy.toml` | A `[composition]` skewed toward billing, at 500 records where the 2pp default is achievable |
| `ollama-remote.toml` | `connection` versus `extra`, and a raised `privacy.max_discard_rate` with the reasoning written out |
| `planted-pii.toml` | The privacy gate blocking: a prompt document that asks for real-looking contact details, expected to fail the run with nothing in the release path |
| `tight-tolerance.toml` | A refusal fixture — 2pp at 20 records is unsatisfiable by arithmetic alone; exit 2 naming both remedies |
| `bad-composition.toml` | A refusal fixture — category proportions sum to 1.4; exit 2 before any model call |
