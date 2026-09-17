# Feature Specification: Ticket Generation Pipeline

**Feature Branch**: `bootstrap-speckit` *(no dedicated feature branch created; spec directory is `specs/001-ticket-generation-pipeline`)*

**Created**: 2026-08-18

**Status**: Draft

**Input**: User description: "Multi-turn customer support ticket generation pipeline. This is the product: it generates the dataset. Define the versioned record schema the generator writes against (conversation turns with speaker roles, ticket metadata, and provenance fields), then generate synthetic multi-turn customer/agent conversations from an explicit seed and a single serialized configuration, so any run is replayable or auditable. Every run writes a run manifest capturing seed, config, code revision, input hashes, schema version, record counts, and filter accounting by reason (Constitution Principle II and III). Every run passes its own output through a blocking automated PII scan before the output is written to the release path, because Constitution Principle IV requires every generation pipeline to run one. Output is JSON Lines under data/. The generator must be able to produce a corpus at release scale (~100,000 records) and let the operator control the mix of ticket categories, priorities, channels, and resolution outcomes. Out of scope: the standalone validation tool for datasets postprocessed by external tools, which is feature 002."

## Clarifications

### Session 2026-08-18

- Q: By what method is conversation text produced? → A: A language model generates it; exact reproducibility becomes best-effort with model identity and parameters captured in the manifest
- Q: What happens when the privacy scan flags generated records? → A: Discard the flagged records and account for them under a privacy discard reason; the rest of the corpus proceeds
- Q: Where do the support scenarios come from? → A: A committed domain prompt markdown file; the model elaborates plausible subdomain scenarios from it
- Q: How is conversation length determined? → A: A configurable min/max range, with each conversation's length sampled from it as a seeded choice
- Q: How is conversation coherence decided? → A: A model-as-judge scores every generated record against a rubric; records below a configured threshold are discarded and accounted for
- Q: What happens when a long run is interrupted? → A: Runs checkpoint progress and resume where they stopped, reconciling into a single manifest
- Q: How does the generator achieve throughput at release scale? → A: Bounded concurrency with retry and backoff, with per-record seeded choices assigned before dispatch so results stay order-independent
- Q: What default values should the run's thresholds and tolerances take? → A: Composition ±2 percentage points, privacy discard rate 0.5%, coherence discard rate 10%, coherence score threshold 0.8 — all configurable

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce a corpus of support conversations (Priority: P1)

A dataset author wants a corpus of multi-turn customer support conversations. They write a configuration
describing what they want, choose a seed, and run the generator. It produces a file of conversation records
— each a coherent exchange between a customer and a support agent about a plausible support issue — every
one of which conforms to the project's record contract.

**Why this priority**: This is the product. Everything else in the repository exists to make this output
trustworthy; without it there is no dataset. On its own it already delivers the core value: a usable corpus.

**Independent Test**: Run the generator with a small record count and a fixed seed, then confirm the output
file contains that many records, every record conforms to the schema, and each conversation reads as a
coherent multi-turn exchange — no manifest, privacy, or composition machinery required.

**Acceptance Scenarios**:

1. **Given** a valid configuration and a seed, **When** the author runs the generator, **Then** it produces
   the requested number of records, each conforming to the record contract, and reports how many it wrote.
2. **Given** a generated record, **When** the author inspects it, **Then** its turns alternate between a
   customer and a support agent, are ordered, and are non-empty, and the exchange concerns a single
   coherent support issue.
3. **Given** the same seed and the same configuration, **When** the author runs the generator twice,
   **Then** the two runs produce equivalent output, or — where exact reproduction is not achievable — the
   run records everything needed to explain the difference.
4. **Given** a configuration that is invalid or internally contradictory, **When** the author runs the
   generator, **Then** it refuses to run and names the specific problem rather than producing partial output.
5. **Given** a request for a corpus at release scale, **When** the generator runs, **Then** it writes
   records incrementally so that progress is observable and memory does not grow with corpus size.

---

### User Story 2 - No generated output reaches the release path carrying personal data (Priority: P2)

Before any generated output is treated as releasable, the pipeline scans it for content resembling real
personal identifiers. If anything is found, the output does not reach the release path. Findings a reviewer
has judged to be legitimately synthetic can be recorded as approved exceptions so they do not re-block
every subsequent run.

**Why this priority**: Constitution Principle IV requires every generation pipeline to run a blocking scan
over its output, and the consequence of failure is irreversible once published. It ranks below generation
only because there must be output before there is anything to scan.

**Independent Test**: Run the generator with a configuration deliberately seeded to emit identifier-shaped
content; confirm the run is blocked, nothing is written to the release path, and the findings name the
offending records.

**Acceptance Scenarios**:

1. **Given** generated output containing a value shaped like a real email address, phone number, payment
   card, or government identifier, **When** the pipeline scans it, **Then** each finding is reported with
   its record identifier, the field it appeared in, the category detected, and a masked rendering that
   never reproduces the matched value.
2. **Given** any unreviewed privacy finding, **When** the run completes its scan, **Then** the output does
   not reach the release path and the blocking reason is reported.
3. **Given** a finding a reviewer has adjudicated — from its masked rendering, or from the quarantined
   record when the mask is insufficient — and recorded as an approved synthetic value with a stated reason,
   **When** a later run produces the same content, **Then** it no longer blocks, but remains visible in the
   run's report as an approved exception.
4. **Given** output with no detectable identifiers, **When** the scan completes, **Then** it reports a clean
   result, states how many records and fields it examined, and names the detectors that ran.
5. **Given** a scan that cannot cover its mandatory categories, **When** the run starts, **Then** it fails
   before generating rather than producing output no one can vouch for.

---

### User Story 3 - Reconstruct how a corpus was produced (Priority: P3)

Months later, someone investigating a data quality complaint needs to know exactly how a corpus was made:
the seed, the full configuration, the code revision, what inputs were consumed, how many records were
produced, and why any were discarded. They open the run manifest beside the artifact and find all of it,
and can trace any single record back to that run.

**Why this priority**: Constitution Principles II and III require it, and provenance cannot be
retrofitted — a corpus produced without a manifest is permanently unauditable. It ranks below the privacy
gate because a missing manifest is recoverable by regenerating; published personal data is not.

**Independent Test**: Generate a small corpus, then confirm its manifest records seed, configuration, code
revision, input hashes, and counts, that the counts reconcile exactly, and that every record carries
identifiers resolving to that manifest.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** its manifest is written, **Then** the manifest records the seed, the
   full serialized configuration, the code revision, the identifying hashes of all inputs, the schema
   version, and the output record count.
2. **Given** a run that discarded records — because they failed the schema, failed the privacy scan, or were
   rejected as unusable — **When** the manifest is written, **Then** every discarded record is accounted for
   by count and by reason, and input count minus all discards equals output count.
3. **Given** any record in the corpus, **When** someone inspects it, **Then** it carries a record identifier,
   the run identifier, the source or template it derives from, and the schema version it was written against.
4. **Given** a run whose output cannot be reproduced exactly, **When** the manifest is written, **Then** it
   records the non-deterministic inputs that explain why, rather than implying reproducibility it cannot
   deliver.
5. **Given** a manifest missing any required element, **When** it is checked, **Then** the check fails and
   names the missing element.

---

### User Story 4 - Control the composition of the corpus (Priority: P4)

An author needs a corpus with a particular shape — weighted toward billing issues, mostly resolved, mostly
email and chat — rather than an arbitrary mix. They express the desired composition in the configuration and
the generator honors it, reporting the composition it actually achieved.

**Why this priority**: Composition control is what makes the corpus useful for a specific downstream task
rather than merely large. It ranks last because a corpus with an arbitrary but valid mix is still a usable
corpus, whereas one that fails the earlier gates is not.

**Independent Test**: Generate a corpus with a specified composition and confirm the achieved distribution
across categories, priorities, channels, and resolution outcomes matches what was requested within the
stated tolerance.

**Acceptance Scenarios**:

1. **Given** a configuration specifying a desired mix of ticket categories, priorities, channels, and
   resolution outcomes, **When** the generator runs, **Then** the achieved composition matches the request
   within the stated tolerance.
2. **Given** any completed run, **When** the author reads the run report, **Then** it states the composition
   actually achieved, not only the composition requested.
3. **Given** a composition request that cannot be satisfied — proportions that do not sum correctly, or a
   combination the generator cannot produce — **When** the run starts, **Then** it refuses and explains
   which part of the request is unsatisfiable.
4. **Given** a configuration that specifies no composition, **When** the generator runs, **Then** it uses a
   documented default distribution rather than an undefined one.

---

### Edge Cases

- **Interrupted run**: A run killed partway must not leave a partially written file in the release path that
  looks complete; incomplete output is distinguishable from finished output, and the run can be resumed from
  its checkpoint.
- **Resume attempted with changed inputs**: Resuming a checkpoint whose configuration, seed, prompt
  document, or rubric no longer matches is refused rather than silently producing a mixed-provenance corpus.
- **Checkpoint corrupted or unreadable**: An unusable checkpoint is reported as such, leaving the operator to
  restart deliberately rather than resuming from an unknown state.
- **Zero records requested**: A request for zero records is refused as a configuration error rather than
  silently producing an empty corpus.
- **Every record discarded**: If all generated records fail the schema or the privacy scan, the run fails
  with the discards fully accounted for, rather than writing an empty artifact.
- **Duplicate output**: Generation may produce identical conversations by chance; the run reports how many
  duplicates it produced so the author can judge corpus diversity.
- **Unicode and multilingual content**: Non-Latin scripts, emoji, and right-to-left text are valid turn
  content and must not be treated as malformed.
- **Very long conversations**: A conversation with an unusually large number of turns is valid; nothing may
  assume a small fixed maximum.
- **Repeated run into an existing path**: Re-running into a path that already holds an artifact must not
  silently overwrite it or, worse, append to it.
- **Judge unavailable while the generator is working**: A record that cannot be scored is discarded and
  accounted for, never admitted unjudged.
- **Judge rejects nearly everything**: A coherence discard rate above threshold fails the run rather than
  quietly producing a corpus far smaller than requested.
- **Model unavailable or rate-limited mid-run**: A long run must survive transient failures without losing
  completed work, and must not silently deliver a smaller corpus than requested.
- **Sustained provider outage**: When retries are exhausted across many consecutive records, the run stops
  and checkpoints rather than burning through the remaining corpus emitting discards.
- **Declared budget exhausted mid-run**: A run that reaches its declared time or call ceiling stops and
  checkpoints with its partial corpus intact and its accounting complete, rather than continuing past the
  ceiling or discarding completed work. Resuming is the operator's decision, not an automatic one.
- **Concurrency changed between runs**: Two runs with the same seed and configuration but different
  concurrency levels must still produce comparable corpora, since seeded choices are position-derived rather
  than order-derived.
- **Model returns unusable output**: A response that is unparseable or structurally invalid is discarded and
  accounted for, not coerced into a record.
- **Prompt document changed between runs**: Two corpora generated from different prompt document versions
  are distinguishable from their manifests, since the document's hash is recorded as a run input.
- **Privacy scan finds content in a field the author considers non-textual**: Every field carrying free text
  is scanned; the set of scanned fields is stated in the report rather than assumed.

## Requirements *(mandatory)*

### Functional Requirements

**Record contract**

- **FR-001**: The project MUST publish a machine-readable, versioned definition of a support ticket record
  covering its conversation turns, ticket metadata, and provenance fields, and the generator MUST write
  against that definition.
- **FR-002**: The definition MUST carry a `MAJOR.MINOR.PATCH` version, and every record MUST declare the
  version it was written against.
- **FR-003**: Each record MUST provide a stable record identifier, the run identifier that produced it, the
  source or template it derives from, and its schema version.
- **FR-003a**: The run identifier MUST be generated fresh for each run instance and carried in the run's
  checkpoint, so that a **resumed** run continues under the identifier it started with while a **rerun** —
  even one with the same seed and configuration — receives a new one. Deriving the run identifier from the
  inputs would make two legitimate reruns indistinguishable and would give two separate corpora the same
  record identifiers.
- **FR-003b**: The record identifier MUST be derived deterministically from the run identifier and the
  record's `record_index`. Uniqueness within a run is then structural rather than checked, and
  uniqueness across runs follows from FR-003a. This is what lets a resumed run satisfy FR-015b by
  construction: regenerating a position yields the identifier that position always had, so no identifier
  can be issued twice and none can be skipped.
- **FR-004**: Each conversation turn MUST identify its speaker role, its position in the conversation, and
  its content.
- **FR-005**: Permitted speaker roles MUST be enumerated in the definition; any other value is invalid.
- **FR-006**: Each record MUST carry ticket metadata comprising a topic category, a priority level, an
  originating channel, a resolution status, and the times the ticket was created and resolved, each
  constrained to an enumerated set where applicable.
- **FR-006a**: Ticket timestamps MUST be **seeded choices, not model output and not wall-clock time**. The
  configuration declares a date window; a record's creation time is drawn from that window by the same
  position-derived generator as its other seeded choices (FR-012b), and its resolution time is that creation
  time plus a seeded duration. Timestamps therefore reproduce exactly across runs of the same seed, and a
  corpus can be stratified by date. Model-chosen timestamps would let narrative and metadata agree at the
  cost of reproducibility; wall-clock times would record when the generator ran rather than anything about
  the ticket.
- **FR-006b**: A resolution time MUST be present when — and only when — the resolution status is *resolved*.
  A ticket that was escalated, abandoned, or left unresolved has no resolution to time, and recording one
  anyway would make the field mean different things in different records.
- **FR-007**: The generator MUST validate every record it produces against the definition before writing it,
  and MUST discard and account for any record that does not conform.

**Generation**

- **FR-008**: The generator MUST accept a single serialized configuration, an explicit seed, and a committed
  domain prompt document as its only inputs, and MUST NOT read hidden state from the operator's environment.
  **Model credentials are the sole exception**: they are an access mechanism rather than a generation input,
  they MUST NOT influence output content, and they MUST NOT be recorded anywhere in the run's artifacts.
- **FR-008c**: Any environment setting that could change which model serves a request, how it is routed, or
  the parameters it runs under — an alternate endpoint, an account or profile selection, an inference region
  — MUST be recorded in the manifest as a non-deterministic input. An unrecorded environment setting that
  alters output is exactly the hidden state FR-008 prohibits; recording it converts it into provenance. A
  setting that cannot be observed and recorded MUST cause the run to refuse rather than proceed unrecorded.
  A setting whose value is a **network address** MUST be recorded as having been set rather than by value,
  per FR-042; the fact of the override is what makes it provenance, and the address is not needed to audit
  a corpus.
- **FR-008a**: Support scenarios MUST derive from a committed domain prompt document, from which the
  generation model elaborates plausible subdomain scenarios. The prompt document is a run input: its
  identifying hash MUST be recorded in the manifest, so a change to it is visible as a change in provenance.
- **FR-008d**: The domain prompt document MUST declare an **enumerable list of subdomains**. Scenario
  derivation is two-level: the subdomain is a seeded choice made before dispatch (FR-012b), and the model
  elaborates a specific situation within the subdomain it is given. Without an enumerable list, "scenario
  selection" cannot be a seeded choice at all, and the corpus cannot be stratified deterministically.
- **FR-008b**: Each record MUST record **both** the subdomain it was assigned and the specific scenario the
  model elaborated within it, in addition to its `source_id`, so that records remain distinguishable and the
  corpus can be stratified — the prompt document alone is common to every record and cannot serve that
  purpose. The subdomain is reproducible from the seed; the elaborated scenario is model text and is not.
- **FR-009**: The generator MUST produce coherent multi-turn exchanges in which turns are ordered, are
  non-empty, alternate between participants, and concern a single support issue. **The customer speaks
  first**: a support interaction begins with the party raising the issue, and leaving the opening role
  unstated would let two conforming implementations produce corpora that differ on every record.
- **FR-009a**: Conversation text MUST be produced by a language model prompted from the domain prompt
  document and the run configuration.
- **FR-009d**: The configuration MUST accept a minimum and maximum turn count, and each conversation's
  length MUST be sampled **uniformly** from that range as a seeded choice, so the length distribution is
  reproducible even though the text is not. Naming the distribution matters: "sampled from a range" alone
  admits implementations that produce materially different corpora while both conforming. Uniform sampling
  produces more long conversations than real support traffic contains, which is an accepted simplification —
  the range means exactly what it says, and the resulting distribution is testable.
- **FR-009e**: The generator MUST reject and account for any conversation whose turn count falls outside the
  configured range, and MUST refuse to start when the range is invalid: a minimum exceeding the maximum, or a
  minimum below **2**. Two turns — one from each party — is the smallest exchange that can be an exchange;
  a single turn is a statement, and no coherence rubric can meaningfully score one.
- **FR-009b**: The generator MUST structurally validate every model response before accepting it as a
  record, and MUST discard and account for any response that is unparseable, structurally invalid, or
  violates the ordering, alternation, non-emptiness, or turn-count constraints in FR-009 and FR-009d. A
  **turn-count violation is always accounted under the turn-count reason**, never under the general
  structural one: the two failures have different causes — a length the model would not honor, versus output
  it could not form — and FR-026's accounting is only useful if each response lands under one reason
  predictably.
- **FR-009f**: Every structurally valid record MUST additionally be scored for coherence by a model-based
  judge, against a committed, versioned rubric.
- **FR-009g**: The coherence rubric MUST be a committed artifact whose identifying hash is recorded in the
  manifest as a run input, so a change in judging standards is visible as a change in provenance.
- **FR-009p**: The rubric MUST declare an identifier, a version, its **criteria**, and each criterion's
  **weight**. The coherence score is the weighted mean of the judge's per-criterion scores, each on a
  normalized 0–1 scale. This is what gives the threshold a stable meaning: a holistic score would mean
  whatever the judging model read the prose to mean and would drift with the model, whereas a declared
  criterion set makes the rubric a checkable artifact and lets a low score be attributed to a specific
  criterion during calibration. Weights MUST sum to 1, and a rubric that does not is a configuration error.
- **FR-009h**: Records scoring below a configured coherence threshold MUST be discarded and accounted for
  under a distinct coherence discard reason. The threshold defaults to **0.8** on a normalized 0–1 scale.
- **FR-009i**: Each accepted record MUST carry the coherence score it received **and the identifier of the
  rubric that produced it**, so the corpus can be filtered or stratified by quality without re-judging it.
  The rubric identifier is not optional detail: the criteria and weights behind a score live in the rubric
  (FR-009p), so a bare number cannot be compared across rubric versions or interpreted without one.
- **FR-009j**: The identity and parameters of the judging model MUST be recorded in the manifest alongside
  those of the generating model, because the judge is a non-deterministic input that shapes which records
  survive (Constitution Principle II). The judge MAY be the same model as the generator, and is by default.
- **FR-009q**: Because judging is a model call, **the set of records that survives is not perfectly
  reproducible**: the same conversation may be admitted by one run and discarded by another. This is
  accepted behaviour, not a defect, and is the reason FR-009g, FR-009i, and FR-009j require the rubric hash,
  the per-record score, and the judge's identity and parameters to be recorded — the gate is auditable
  though it is not deterministic. FR-010's reproducibility claim covers structure and composition, which are
  seeded, and deliberately does not extend to which records survive judging.
- **FR-009k**: A coherence discard rate above a configured threshold MUST fail the run, because a generator
  whose output is mostly rejected is defective and filtering around it would mask the defect. The threshold
  defaults to **10%** of records generated, with "records generated" as defined in FR-026a.
- **FR-009l**: A judge failure MUST NOT silently admit an unjudged record. If a record cannot be scored
  after the configured retries, it MUST be discarded and accounted for under a distinct reason.
- **FR-009c**: The generator MUST tolerate transient model failures without losing completed work — a
  failed or rejected response MUST NOT abort a run that can still proceed, and repeated failure MUST be
  reported as a discard reason rather than silently reducing corpus size.
- **FR-009m**: A model that **declines a request on safety grounds** is a distinct outcome from an
  unparseable response and from a transport failure, and MUST be handled as such: the slot is retried, and a
  slot that keeps being declined is discarded under a **model refusal** reason rather than counted as a
  malformed response. Conflating the two would hide a prompt domain that systematically trips a classifier
  behind a statistic that reads as a flaky provider.
- **FR-009n**: A record produced by a model **other than the one configured** — because a declined request
  was rescued elsewhere — is acceptable corpus output, provided FR-027a's per-record model identity is
  recorded and the manifest reports how many records each model served. A corpus may therefore contain
  records from more than one model; what matters is that no record misstates which model produced it, and
  that a datasheet can report the mix.
- **FR-009o**: The number of attempts a slot receives MUST be a **single configured value** covering every
  retryable per-record failure — a declined request, an unparseable or structurally invalid response, and an
  unscorable one alike. It is distinct from transport-level retries of a single request, which are reported
  separately under FR-012d, because a degraded provider and a defective generator are different facts.
- **FR-010**: Given the same seed, configuration, and prompt document, the generator MUST produce output
  that is equivalent in structure and composition. Exact textual reproduction is NOT guaranteed, because
  model sampling is not reproducible in general; the manifest MUST therefore record the model identity, its
  parameters, and any sampling seed, so that a run that cannot be replayed can still be audited
  (Constitution Principle II).
- **FR-010a**: **Equivalent** means: for every `record_index` present in both corpora, the seeded choices
  match exactly — assigned category, priority, channel, resolution status, subdomain, turn count, and ticket
  timestamps — and each achieved composition lies within the configured tolerance of the other. Turn text is
  excluded, and so is *which* positions are present: FR-009q makes survival through the coherence gate
  non-deterministic, so two equivalent runs may write different numbers of records. Without this definition
  "equivalent" cannot be tested, and SC-003 would rest on whichever reading an implementer chose.
- **FR-010b**: Reproducibility is claimed **within a code revision**. Two runs of the same inputs at
  different revisions are not required to be equivalent; the manifest records the revision of every segment
  that produced a corpus (FR-015f, FR-025a), so a difference is explained rather than denied. Claiming
  reproducibility across arbitrary revisions would be a promise no change to the generator could keep.
- **FR-009r**: The configuration MUST carry the **language** conversations are generated in, defaulting to
  English, and it MUST be recorded in the manifest. Without an explicit setting the corpus language is
  whatever the prompt document happens to elicit, and can drift between runs with no record of having done
  so. Declaring it makes a multilingual corpus a deliberate act and a monolingual one a stated fact.
- **FR-011**: The generator MUST refuse to run on an invalid or internally contradictory configuration,
  naming the specific problem, rather than producing partial output.
- **FR-012**: The generator MUST write records incrementally so that memory does not grow with corpus size
  and progress is observable during a long run.
- **FR-012g**: "Observable" MUST mean **reported to the operator while the run proceeds** — records
  completed against the target, elapsed time, and the discard count so far — not merely inferable from
  the output file growing. An operator watching a long run needs to distinguish a working run from a hung
  one, and that is the question progress reporting exists to answer; a corpus that can be tailed does not
  answer it. Reporting MUST go to the diagnostic stream, never to the machine-readable output, and MUST be
  suppressible for unattended runs.
- **FR-012a**: The generator MUST process multiple conversations concurrently, with the level of concurrency
  configurable, so that a release-scale corpus is achievable in a single run.
- **FR-012b**: All seeded choices for a record — its turn count, its composition assignment, its subdomain
  selection (FR-008d), and its ticket timestamps (FR-006a) — MUST be derived deterministically from the run seed and the record's position,
  assigned before the record is dispatched. The scenario the model elaborates within an assigned subdomain
  is model output, not a seeded choice, and is reproducible only in the structural sense FR-010 states. They MUST NOT be drawn from a shared sequential stream, so that output does not
  depend on the order in which concurrent work completes. Nor may any derivation depend on **interpreter
  or process state** — a value that varies between two invocations of the same code is as much hidden state
  as an unrecorded environment setting, and defeats the seed it appears to honour. A seeded choice MUST
  also not depend on another seeded choice unless the requirements say it does: coupling them means a
  change to one dimension silently moves another.
- **FR-012c**: Records MUST be written in **ascending `record_index`**, independent of completion order, so
  that two runs with the same seed and configuration produce corpora comparable record by record. A record's
  serialization MUST also be deterministic — identical record content yields identical bytes — so that
  comparison is a diff rather than a parse. This does **not** make two corpora byte-comparable as files: turn
  text differs between runs by FR-010, and the comparison FR-010a defines is per position, not per byte.
- **FR-012d**: The generator MUST retry transient failures and rate-limit responses with backoff, and MUST
  report retry counts in the run report so that a degraded provider is visible rather than merely slow.
- **FR-012e**: The generator MUST bound its own request rate so a run cannot be throttled into failure by
  its own concurrency, and the bound MUST be configurable.
- **FR-012f**: The configuration MUST allow the operator to declare a **run budget** — a maximum wall-clock
  duration, a maximum number of model calls, or both. When a declared budget is exhausted, the run MUST stop
  and checkpoint rather than continue or fail outright, so that no completed work is lost and the operator
  decides whether to resume. The manifest MUST record the declared budget and the actual spend against it.
  An unattended run at release scale otherwise has no ceiling on time or cost.
- **FR-013**: The generator MUST write output as JSON Lines beneath the project's data directory, placing
  release-path output in a location distinct from scratch and intermediate output.
- **FR-014**: The generator MUST NOT overwrite or append to an existing artifact at its output path. It MUST
  refuse and name the conflicting path. **No option to overwrite exists**: the data directory is outside
  version control, so an overwritten corpus and its manifest are unrecoverable, and removing a release
  artifact is therefore a deliberate manual act rather than a flag that can find its way into a script that
  runs unattended.
- **FR-014a**: The generator MUST claim its destination path at run start and MUST re-verify the claim
  immediately before the artifact is placed there. Checking only at the start leaves two concurrent runs
  both passing the check and the second silently replacing the first's output at the end.
- **FR-015**: An interrupted run MUST NOT leave output in the release path that is indistinguishable from a
  completed run. Incomplete output MUST NOT occupy the release path **at all**: it lives in intermediate
  output until the run succeeds, and the artifact appears in the release path by a single indivisible
  operation. Distinguishing complete from incomplete by location — which the constitution's separation of
  directories already provides — cannot be defeated by a partial write, a crash, or a naming mistake, as a
  suffix convention can.
- **FR-015a**: A run MUST checkpoint its progress periodically — records written, discard tallies by reason,
  and the state needed to continue seeded choices — so that an interrupted run can resume rather than
  restart.
- **FR-015b**: A resumed run MUST continue from its checkpoint without regenerating or duplicating records
  already written, and MUST NOT reuse a record identifier already issued. An identifier counts as **issued
  when a record carrying it has been written**. Re-deriving the identifier of a position whose earlier
  attempts were all discarded is therefore not reuse — no record ever bore it — which is what allows
  FR-009c's retries and FR-003b's deterministic derivation to coexist with this requirement.
- **FR-015c**: A resumed run MUST produce a single manifest describing the whole corpus, with counts and
  discard accounting reconciling across all segments, so provenance is not fragmented by an interruption.
- **FR-015d**: The manifest MUST record that a run was resumed and how many times, since an interrupted run
  is a material fact about how the corpus was produced.
- **FR-015e**: Resuming MUST be refused when the configuration, seed, prompt document, or rubric differs
  from the checkpointed run, because continuing under changed inputs would produce a corpus the manifest
  cannot honestly describe.
- **FR-015f**: A **changed code revision does not refuse a resume**. Instead, the manifest MUST record one
  segment per run or resume, each carrying its own code revision and the range of records it produced, so a
  corpus generated across more than one revision is described honestly rather than prevented. Refusing would
  discard the completed part of a long run over an edit made while it was interrupted; recording keeps the
  provenance intact and leaves the judgement to whoever decides to release. This is the same trade FR-025a
  makes for a modified working tree.
- **FR-015g**: A checkpoint that cannot be read MUST be reported as unusable and MUST refuse the resume; the
  partial output MUST be preserved rather than discarded. Restarting from scratch MUST be an explicit
  operator action, because the alternative is a tool that silently decides to throw away completed work at
  the moment its own state became untrustworthy.
- **FR-015h**: Resuming MUST identify which run it continues. When the operator does not name a run, the
  candidate is found by matching input fingerprints; exactly one match resumes, several matches MUST refuse
  and name the candidates, and none MUST refuse rather than start a new run under the guise of resuming.
- **FR-015i**: On success, the staging copy and the checkpoint MUST be removed — the artifact in the release
  path supersedes them — while the run report and any quarantine artifact MUST be retained, since the
  quarantine is the input to FR-022's approval and cannot be reconstructed without regenerating the corpus.
  A run that failed or was interrupted MUST retain everything, which is precisely when it is needed.

**Privacy gate**

- **FR-016**: Every run MUST scan its own generated output for content matching known categories of real
  personal identifier before that output reaches the release path.
- **FR-016a**: The scan MUST run on **every structurally valid model response, before that response is
  judged for coherence**. Scanning is offline and cheap next to a model call, so scanning early costs almost
  nothing and buys two things: PII emission is measured across all usable output rather than only the part
  that survived the coherence gate — the measurement matters most exactly when the generator is worst — and
  no judging call is spent on a record that is about to be discarded for a privacy finding.
- **FR-017**: Detection MUST be performed by one or more registered detectors behind a common interface, so
  a detector can be added or replaced without changing the record definition or the pipeline.
- **FR-017a**: A detector that fails while examining a record MUST cause that record to be treated as
  flagged and discarded — failing closed, under a discard reason distinct from an actual finding, so a
  detector malfunction is never mistaken for either a clean result or a real identifier. Repeated detector
  failures MUST stop the run rather than let it continue producing output nothing can vouch for.
- **FR-018a**: Floor coverage MUST be established by **demonstration, not declaration**: at run start, each
  floor type is probed with committed synthetic canary values, and the run proceeds only if every floor type
  is actually detected. A detector that declares a category it no longer detects — an upstream regression, a
  misconfiguration — passes a declaration check and fails a probe, and it is precisely that case the floor
  exists to catch.
- **FR-018b**: A category MAY be registered as **advisory**: reported for visibility but never blocking.
  Every report MUST state each category's blocking status, so an advisory finding is never read as a gate
  that passed and a blocking category is never assumed to be advisory.
- **FR-018**: The scan MUST detect at minimum: email addresses, phone numbers, payment card numbers, and
  **US Social Security numbers**. A detector set that cannot cover this floor MUST fail the run before
  generation rather than producing unvouched output. The floor is stated at the level of the identifier
  **type** actually detected rather than as a broad category: naming "government identifiers" would promise
  coverage of non-US identifiers that no offline detector delivers, which is the same overclaim FR-019
  exists to prevent, merely relocated from the report into the requirement.
- **FR-019**: Every run report MUST enumerate both the identifier **types the scan covers** and the types it
  does not, at the same level of specificity as FR-018's floor — so a clean result is never mistaken for
  coverage the scan does not provide, and so widening coverage later is visible as a change in what the
  report claims rather than a silent improvement.
- **FR-020**: Every privacy finding MUST report the record identifier, the field, the category detected, and
  the detector that reported it — and MUST NOT reproduce the matched value itself.
- **FR-020a**: Every privacy finding MUST additionally carry a **masked rendering** of the matched value —
  enough context for a reviewer to recognize a deliberately synthetic value without reproducing the value
  itself. Masking MUST be deterministic, MUST preserve at most the non-identifying remainder of the value
  (for an email, the domain; for a payment card, the issuer range; for other categories, length and shape
  alone), and MUST NOT be reversible. A masked rendering is not the matched value and does not violate
  FR-020.
- **FR-021**: A record carrying an unreviewed privacy finding MUST NOT reach the release path. Such records
  MUST be discarded and accounted for under a distinct privacy discard reason, and the remainder of the
  corpus MUST proceed; the gate MUST NOT be advisory and MUST NOT pass a flagged record through.
- **FR-021b**: **Every attempt** discarded for a privacy finding MUST be retained in a **quarantine
  artifact** outside the release path — including one that a later attempt replaced, whose record therefore
  never reaches the corpus. The discard is counted either way (FR-026a), so retaining only the attempts that
  also lost their slot would leave the report claiming findings the quarantine cannot show, and the rescued
  attempts are the ones no other artifact records at all. Quarantine exists so that a reviewer has something
  to adjudicate when the masked rendering alone is insufficient. The quarantine artifact MUST be identified in the run report, MUST NOT be committed to
  the repository, and MUST NOT be treated as dataset output. Without it, FR-022's approval has no input:
  the record is gone and FR-020 withholds the value, leaving a reviewer asked to judge something no
  artifact contains. Its second purpose is diagnostic and is what makes it earn its keep in practice: a run
  that trips on values outside the reserved-for-fiction ranges is telling the operator that the prompt
  document needs steering or the exemption ranges need widening, and neither is actionable from a masked
  rendering alone.
- **FR-021a**: The run report MUST state how many records were discarded for privacy reasons. A discard rate
  above a configured threshold MUST fail the run, because a generator emitting identifiers at volume is
  defective and filtering around it would mask the defect. The threshold defaults to **0.5%** of records
  generated, as defined in FR-026a — synthetic content should almost never trip the scanner, so a higher
  rate signals a real defect rather than noise.
- **FR-021d**: The privacy discard rate measures **how often the generator produces identifier-shaped
  content outside the reserved-for-fiction ranges** — not how often real personal data was produced, which
  no offline detector can determine. Raising the threshold therefore weakens an *alarm*, not the gate: every
  blocked record is still blocked, and nothing unscanned still reaches the release path. What a higher
  threshold concedes is that the operator has accepted a generator whose instruction-following is
  imperfect. The default of 0.5% assumes a model that follows the prompt document almost always; a smaller
  or self-hosted model may not, and the configured value MUST be set deliberately rather than the default
  treated as achievable everywhere.
- **FR-022**: Reviewers MUST be able to record a reviewed finding as an approved exception with a stated
  reason; approved exceptions MUST remain visible in the run report and MUST NOT store the matched value.
  A reviewer MUST be able to reach that decision from the masked rendering (FR-020a) or from the quarantine
  artifact (FR-021b), and MUST NOT be required to have observed the original run.
- **FR-022a**: An approved exception MUST record **who approved it and when**. Approval by the person who
  ran the generator is permitted — requiring a second person would make the mechanism unusable on a
  single-maintainer project, and an unusable control is not a control — but every active exception MUST be
  listed in the datasheet of any release that relies on it, so approvals meet a reviewer at the moment that
  matters rather than on a timer. Approvals do not expire.
- **FR-022b**: The stated reason for an exception MUST NOT contain the matched value or any other personal
  identifier. Recording an exception MUST run the registered detectors over the reason text and refuse a
  reason that trips them — otherwise the free-text field defeats the fingerprinting that keeps values out of
  the repository in the first place.
- **FR-023**: The scan MUST report how many records and fields it examined and which detectors ran, so a
  clean result is distinguishable from a scan that examined nothing.
- **FR-023a**: The scanned fields are the record's **model-derived text**: every conversation turn's content
  and the elaborated scenario. The report MUST state the field set it examined. Fields the pipeline assigns
  — identifiers, enumerated metadata, timestamps, schema version — and the subdomain, which comes from the
  committed prompt document, are **not** scanned: an identifier can only enter the corpus through model
  output, and scanning pipeline-assigned values would produce findings on UUIDs and hashes that every run
  would then have to except. The accepted consequence is that a prompt document containing a real identifier
  is not caught by this gate; it is caught by review of a committed file.
- **FR-024**: Every detector MUST operate without contacting a network service — for detection, and equally
  for telemetry, analytics, or usage reporting — so the gate is runnable offline, yields identical findings
  for identical input, and cannot transmit the content it examines. The pipeline MUST disable such reporting
  explicitly rather than relying on a dependency's default staying unchanged.

**Run manifest and provenance**

- **FR-025**: Every run MUST write a manifest recording the seed, the full serialized configuration, the
  code revision, the identifying hashes of all inputs, the schema version, the output record count, and the
  times the run started and completed. The timestamps are required because Principle II names wall-clock
  time as a non-deterministic input to capture, and because the elapsed time of a run is part of what a
  later reader needs to judge whether it can be repeated.
- **FR-025a**: The manifest MUST record the code revision **with an explicit indicator of whether the
  working tree was modified**, and MUST state why the revision is unavailable when it cannot be determined.
  A revision recorded from a modified tree silently misrepresents what produced the artifact; the indicator
  makes that condition reviewable instead of invisible. Neither a modified tree nor an unavailable revision
  fails a run — recording the caveat truthfully is the requirement, and weighing it belongs to the separate
  act of deciding to release.
- **FR-025b**: The manifest MUST identify the artifact it describes by filename and by content checksum, so
  a manifest cannot be read beside an artifact it does not describe, and so a corpus altered after the fact
  is detectable.
- **FR-026**: The manifest MUST account for every discarded record by count and by reason, such that input
  count minus all discards equals output count.
- **FR-026a**: **"Records generated" means every response received from the generating model, counted once
  per attempt.** A slot retried three times contributes three. Every counted response either becomes a
  written record or is discarded under exactly one reason, so FR-026's arithmetic closes as
  `records generated − all discards = records written`. This one definition governs every rate expressed
  as a proportion of records generated — FR-009k and FR-021a included — so that a threshold cannot be
  computed two ways. Note the consequence: a run with heavy retries has a larger denominator, so both
  discard rates are diluted rather than inflated by retrying.
- **FR-026b**: Discard reasons MUST come from a **closed, documented set**, so that the FR-026 reconciliation
  is auditable rather than a sum over free text. The permitted reasons are: **structurally invalid model
  response**, **turn count outside the configured range**, **record failed schema validation**, **coherence
  below threshold**, **unjudgeable after retries**, **privacy finding**, **detector failure**, **model
  refusal**, and **attempts exhausted**. Adding a reason is an additive change to the manifest contract; using one outside the set is
  invalid.
- **FR-027**: The manifest MUST record non-deterministic inputs — including any generation model identity
  and parameters — so a run that cannot be replayed exactly can still be audited.
- **FR-027a**: When the model that serves a request may differ from the model configured — because a request
  was rescued after a refusal, or routed elsewhere — **each record MUST carry the identity of the model that
  actually produced it**, and the manifest MUST additionally report how many records each model served. A
  single run-level model identity would be false for part of the corpus, and provenance that is false for an
  unidentifiable subset is worse than provenance that is absent.
- **FR-028**: The manifest MUST be validatable, and validation MUST name any missing required element.
  Validation MUST also check the FR-026 reconciliation arithmetic and name the discrepancy when the counts
  do not close — a manifest whose fields are all present but whose accounting does not balance is not valid,
  and presence checking alone would pass exactly the manifests worth catching.
- **FR-029**: Every record MUST be traceable to the manifest of the run that produced it using only the
  record's own fields.
- **FR-029a**: A run's manifest MUST be written beside its artifact and **named by the run identifier**, so
  that a record's own `run_id` locates the manifest file directly. Without a naming rule, FR-029's claim is
  unachievable: a record carries an identifier, not a path, and someone holding a single record would have
  no way to find the run that produced it — which is precisely the investigation FR-029 exists to support.

**Composition control**

- **FR-030**: The configuration MUST allow the operator to specify a desired distribution across ticket
  categories, priorities, channels, and resolution outcomes.
- **FR-031**: The generator MUST honor a requested distribution within a configurable tolerance, defaulting
  to **±2 percentage points**. The tolerance is evaluated **per member of each dimension**: for every member
  of every controlled dimension, the absolute difference between its achieved proportion and its requested
  proportion MUST NOT exceed the tolerance. A dimension passes only when its worst member passes, and a
  failure MUST name the offending member and its drift, not merely the dimension. Aggregate measures are
  deliberately not used: someone slicing the corpus by one category cares about that category's drift, and
  an average would let a badly-served member hide behind well-served ones.
- **FR-031a**: The run MUST report **three** distributions per dimension — the composition **requested**,
  the composition **assigned** to slots before generation, and the composition **achieved** in the written
  corpus. Requested versus assigned exposes apportionment error; assigned versus achieved exposes drift
  caused by discards. Without the middle term an operator cannot tell which of the two caused a tolerance
  failure, and the two call for entirely different responses.
- **FR-031b**: A tolerance the corpus size cannot achieve MUST be refused before generating. Assigning whole
  records to proportions bounds the per-member error at `1 / record_count` before any discard occurs, so a
  tolerance below that is unsatisfiable by arithmetic alone. The refusal MUST state both the minimum corpus
  size and the minimum tolerance that would work. This is a necessary condition, not a sufficient one:
  meeting it does not guarantee the tolerance survives discards.
- **FR-032**: The generator MUST refuse an unsatisfiable composition request and explain which part cannot
  be satisfied. A request is unsatisfiable when: its proportions for a dimension do not sum to 1 within a
  stated epsilon; it names a value that is not a member of that dimension's enumeration; a requested
  proportion is too small to round to a whole record at the requested corpus size; or the requested
  tolerance is unachievable at that corpus size (FR-031b).
- **FR-033**: When no composition is specified, the generator MUST apply the following default distribution
  and the default turn-count range of **4 to 12** turns. These defaults are requirements, not implementation
  choices: changing them changes the corpus every unconfigured run produces.

  | Dimension | Default distribution |
  |-----------|----------------------|
  | Category | `billing` 0.25, `technical` 0.25, `account` 0.20, `shipping` 0.15, `product` 0.10, `other` 0.05 |
  | Priority | `low` 0.20, `normal` 0.50, `high` 0.20, `urgent` 0.10 |
  | Channel | `email` 0.40, `chat` 0.35, `phone` 0.15, `web_form` 0.10 |
  | Resolution status | `resolved` 0.70, `unresolved` 0.10, `escalated` 0.15, `abandoned` 0.05 |
- **FR-034**: The run report MUST state how many duplicate conversations were produced, so corpus diversity
  is visible.

**Reporting**

- **FR-035**: Every run MUST produce a report covering records generated, records discarded by reason,
  privacy findings, detectors run, uncovered categories, and achieved composition.
- **FR-036**: The report MUST be available in a machine-readable form so automation can act on it without
  parsing prose, and the run MUST signal success or failure unambiguously.
- **FR-036a**: The report MUST be **JSON**, and MUST be locatable from a run identifier alone. On success it
  is written beside the artifact as `<run_id>.report.json`; otherwise it is written as `report.json` inside
  the run's intermediate directory, which already carries the identifier. A report findable only if you
  already know how the run ended would be hardest to reach exactly when it is most needed.
- **FR-036b**: A run's outcome MUST be one of four distinguishable states, because they call for different
  responses and a binary cannot express them: **completed** (the artifact reached the release path),
  **refused** (nothing was generated and nothing was spent), **failed** (output exists but did not qualify,
  with the accounting explaining why), and **stopped** (interrupted, budget exhausted, or halted by a
  threshold — resumable, with work preserved).
- **FR-037**: The discard-rate thresholds — privacy (FR-021a) and coherence (FR-009k) — MUST be evaluated
  **during the run**, not only at its end, once enough records have been generated for a rate to be
  meaningful: at least 1,000, or 5% of the requested corpus size, whichever is larger. A breach MUST stop
  the run, checkpoint it, and report failure. Evaluating only at completion means a generator emitting
  identifiers on every record still costs a full release-scale run before anyone is told; the minimum sample
  exists so that an early cluster of discards cannot fail a run that would have been fine.
- **FR-037a**: The **composition tolerance** (FR-031) MUST be evaluated only at completion. A partial corpus
  has no achieved composition to compare — apportionment is only satisfied once every slot has been
  attempted — so an early check would measure incompleteness rather than drift.
- **FR-040**: `record_count` is a statement about **the corpus**, not about how many slots were
  attempted. Once every requested slot has been attempted, a run whose corpus is short MUST generate
  replacement slots until it holds `record_count` records. Taking discards off the top of the corpus makes
  the delivered size a function of how badly the generator happened to behave, which is precisely what
  FR-009c forbids doing silently.
- **FR-040a**: Replacement slots MUST be assigned from the composition **deficit** — what apportionment
  assigned, minus what the corpus holds, per member of each dimension — rather than from the requested
  distribution. Records lost to discards are not a random sample of the corpus: a category the generator
  handles badly is discarded more often, so replacing proportionally would preserve the very drift FR-031's
  tolerance exists to catch.
- **FR-040b**: Replacement slots MUST take **fresh positions**, continuing past `record_count`, rather than
  reusing the positions of discarded records. Reuse would be permitted by FR-015b — a position whose attempts
  were all discarded issued no identifier — but fresh positions keep writes strictly ascending, which is what
  lets the staging file remain a prefix of the corpus and a byte offset remain a sufficient recovery point.
  A complete corpus therefore has `record_count` distinct ascending `record_index` values whose maximum may
  exceed `record_count - 1`; density over `[0, N)` is **not** a property of the corpus.
- **FR-040c**: The replacement work MUST be bounded by a configured fraction of `record_count`, counted
  across every round and carried across resumes. A run that reaches the bound, or produces a round with no
  surviving record, with the corpus still short MUST **fail** — output retained in staging with its
  manifest, nothing published. Publishing a short corpus quietly is the outcome this requirement exists to
  prevent, and a bound that reset on resume would be no bound at all.
- **FR-040d**: The run report MUST state the requested record count beside the written one, and how much
  replacement work was spent reaching it. Generation beyond what was requested is the run's variable cost;
  adding it silently would be as opaque as dropping records silently (Constitution Principle III).
- **FR-040e**: Which replacement records a run produces is **not seeded-reproducible**, because it depends
  on which records the judge discarded. This is the same concession FR-009q already makes, widened from
  which positions survive to which positions exist, and is the reason FR-040d's accounting is required.
- **FR-038**: The coherence score distribution MUST be reported as **counts in fixed buckets of 0.05 across
  the 0–1 range**, together with the count, minimum, maximum, mean, and median. Fixed buckets make two runs
  comparable without re-deriving anything; a free choice of bucketing would make every run's distribution
  incomparable with every other.
- **FR-039**: Duplicate detection is **within a single run**. Two records are duplicates when their turn
  sequences — each turn's role and content in order, Unicode-normalized — are identical; ticket metadata and
  identifiers are excluded, since assigned metadata varies by construction and would mask the repetition the
  count exists to surface. Comparison against previously generated corpora is out of scope: it would require
  a persistent cross-run registry this feature does not otherwise need, and FR-034's purpose is a diversity
  signal for the run in hand.
- **FR-040**: The configuration a run used MUST be recoverable from the manifest it wrote, as a file the
  system accepts as input. Recovery returns the *resolved* configuration the run actually executed with,
  not the abbreviated one its author may have typed, so an unstated default cannot change the recovered
  run's meaning. The recovered file MUST be verified to parse back to the configuration it came from
  before it is written; a file that would load as a different run MUST NOT be produced.
- **FR-041**: Recovery MUST also report the run conditions the configuration file cannot itself carry —
  the seed, the digest of every recorded input, the code revision, and any routing environment — and MUST
  state whether the working tree still matches them. A run whose recorded inputs have changed MUST NOT be
  reproduced silently: the system either refuses, or proceeds only on an explicit instruction and states
  that the result will not reproduce the recorded corpus. Rationale: a configuration that travels alone
  invites a rerun against a changed prompt to be mistaken for a faithful reproduction, which is a worse
  failure than transcribing the configuration by hand, because it does not announce itself.
- **FR-042**: Settings that describe **how to reach a provider** — endpoint address, API version, keys and
  tokens — MUST be configured separately from settings that shape what a model produces, and MUST NOT be
  written into any artifact a release ships with. The separation MUST be structural rather than a list of
  redacted names: a configuration surface that is open-ended by design cannot be filtered safely by
  enumerating the vocabulary of every provider. A credential placed among output-shaping settings MUST be
  refused at load rather than accepted and stripped later, so that a value which would be published is
  never read at all. The manifest MUST record which connection settings a run used **by name**, so an
  alternate endpoint remains visible as provenance under FR-008c without its address being disclosed.
  Rationale: a manifest travels with the published dataset, so anything in it is disclosed to every reader
  of the corpus. Recording a digest instead of the value was rejected — an internal hostname or address
  carries too little entropy to survive brute force, so a hash would assure without protecting.

### Key Entities

- **Ticket Record**: One complete multi-turn support interaction — its ordered turns, its ticket metadata,
  and its provenance fields. The unit generated, validated, scanned, and counted.
- **Conversation Turn**: A single utterance within a record, carrying a speaker role from the permitted set,
  a position establishing order, and its textual content.
- **Ticket Metadata**: The descriptive attributes of the interaction — topic category, priority, originating
  channel, resolution status, and creation and resolution times.
- **Provenance Fields**: The identifiers binding a record to its origin — record identifier, run identifier,
  source or template identifier, and schema version.
- **Record Schema**: The versioned, machine-readable contract the generator writes against.
- **Domain Prompt Document**: The committed markdown document describing the support domain, from which the
  model elaborates subdomain scenarios. A run input; its hash is recorded in the manifest.
- **Subdomain Scenario**: The specific support situation a record was generated for, elaborated by the model
  from the domain prompt and recorded on the record so the corpus can be stratified by scenario.
- **Generation Configuration**: The single serialized object describing what to generate — corpus size,
  desired composition, turn-count range, coherence threshold, concurrency and rate bounds, and model
  parameters. Recorded verbatim in the manifest.
- **Seed**: The explicit value governing the run's random choices.
- **Run Manifest**: The record of how one run produced its output — seed, configuration, code revision,
  input hashes, schema version, counts, discard accounting, model and judge identities, and resume history.
- **Checkpoint**: The persisted progress of an in-flight run — records written, discard tallies, and the
  state needed to continue seeded choices — enabling resumption without duplication.
- **Discard Account**: One reason records were dropped, with its count. Reasons include structural
  invalidity, coherence below threshold, privacy findings, and unjudgeable records.
- **Coherence Rubric**: The committed, versioned document the judging model scores against. A run input;
  its hash is recorded in the manifest.
- **Coherence Score**: The judge's rating of a single record, retained on the accepted record so the corpus
  can be filtered by quality without re-judging.
- **Privacy Finding**: One detected potential identifier, with its record identifier, field, category,
  reporting detector, and review status — never the matched value.
- **Approved Exception**: A reviewer's recorded decision that a specific finding is a legitimate synthetic
  value, with the stated reason.
- **Run Report**: The consolidated outcome of a run — counts, discards, privacy findings, detectors run,
  uncovered categories, and achieved composition.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An author can produce a corpus of 100,000 conversation records in a single run on one machine
  without the run exhausting memory or requiring manual intervention, with concurrency sufficient that the
  run completes within the budget declared in the configuration (FR-012f) — or stops and checkpoints when
  that budget is exhausted, so the outcome is never an unbounded run.
- **SC-013**: Two runs with the same seed and configuration but different concurrency levels produce corpora
  with identical composition and identical per-position seeded choices, demonstrating that throughput does
  not compromise reproducibility.
- **SC-002**: 100% of records written to the release path conform to the record contract, verified by the
  generator's own pre-write check.
- **SC-003**: For a fixed seed and configuration, two runs produce equivalent corpora — or the manifest
  identifies precisely which inputs made them differ.
- **SC-004**: No corpus containing an unreviewed potential personal identifier can reach the release path,
  demonstrated by an end-to-end attempt that is blocked.
- **SC-005**: For any corpus, the counts reconcile exactly: records generated minus the sum of all discard
  reasons equals records written, with no unexplained difference — including across a run that was
  interrupted and resumed.
- **SC-012**: An interrupted run resumes and completes without regenerating already-written records or
  duplicating record identifiers, demonstrated end to end by killing and resuming a run.
- **SC-006**: Someone who did not run the generator can determine the seed, configuration, code revision,
  and inputs behind any corpus from its manifest alone, in under five minutes.
- **SC-007**: Any single record can be traced to the run that produced it and the source it derives from,
  using only the record's own fields.
- **SC-008**: A requested composition is achieved within ±2 percentage points for **every member of** every
  controlled dimension, and the requested, assigned, and achieved compositions are all reported for every
  run.
- **SC-009**: Every record written to the release path carries a coherence score at or above the configured
  threshold, and the run reports the score distribution across the corpus so quality is visible rather than
  assumed.
- **SC-011**: The coherence judge is calibrated at least once against human judgment on a sample before a
  corpus is released, so the automated gate is known to track what a reviewer would conclude rather than
  being trusted on faith.
- **SC-010**: A new contributor can generate their first corpus using the project's `README.md` and the
  feature's quickstart alone — those two documents are the scope of this claim. Between them they must cover
  installation, how credentials are supplied, how a configuration is written, and one worked run that
  produces a corpus.

## Assumptions

- **Synthetic by construction**: Conversations are fabricated, not derived from real support transcripts.
  The privacy scan is a safety net confirming that held, not the primary control.
- **Line-delimited output**: Corpora are written one record per line, per the constitution's designation of
  JSON Lines as the dataset source of truth.
- **Two-party conversations by default**: Records represent a customer and a support agent. Additional roles
  are accommodated by enumerating them in the schema rather than by relaxing coherence expectations.
- **English-first, not English-only**: Initial content is expected to be English, but nothing may assume it;
  multilingual and non-Latin content must be valid. The language is a declared configuration value defaulting
  to English (FR-009r), so "English" is a recorded fact about a corpus rather than an accident of prompting.
- **The judge may share the generator's model, and self-preference is the accepted risk**: Both roles default
  to the same model. A model evaluating its own output can favour it, and the mitigation here is not
  structural but empirical — the judge scores against declared rubric criteria rather than choosing between
  candidates, and SC-011's calibration against human judgement is what would expose a systematic bias.
  Pointing the two roles at different models is a configuration change, not a code change, if calibration
  shows it is needed.
- **Quarantined records are synthetic, not personal data**: A record held in quarantine (FR-021b) is
  fabricated content that a pattern detector found identifier-shaped — not a real identifier. That is why
  retaining it under the project's intermediate output is compatible with the constitution's requirement
  that no real personal data enter `data/` in any form: the requirement is about provenance of the content,
  not about its shape. The quarantine artifact is never committed and is never dataset output, and the
  approved-exception file continues to store fingerprints rather than values, so nothing identifier-shaped
  accumulates in the repository itself.
- **Reserved-for-fiction values are not personal data**: An address at `example.com` or a number in the
  `555-0100`–`555-0199` range is fabricated by construction — the standards reserving those ranges
  guarantee no real person holds one. Treating them as findings would fail every run on a corpus whose
  conversations mention an email address, which is most of them. They are exempted by range and still
  reported, so the exemption is visible rather than silent (FR-021c).
- **The blocking floor is bounded by what offline detection can do**: The mandatory types are those an
  offline pattern detector covers with high precision. Non-US government identifiers, full postal addresses,
  bank account numbers, and person names are NOT gated — reliable offline detection of them is unavailable —
  and this residual risk is accepted because records are synthetic by construction. FR-019 requires every
  report to enumerate covered and uncovered types alike, so the gap is visible at the point of use.
- **Composition tolerance is proportional**: Requested distributions are honored within a tolerance rather
  than exactly, because integer record counts cannot hit arbitrary proportions precisely. The ±2 percentage
  point default is comfortably achievable at release scale and is arithmetically impossible below 50
  records, so a run that asks for both a small corpus and a tight tolerance is refused up front (FR-031b)
  rather than allowed to spend its calls and fail at the end.
- **The controlled dimensions are independent**: Category, priority, channel, and resolution status are
  apportioned separately, so any combination of the four may occur and no joint distribution is expressible.
  A combination that reads as implausible is the generating model's problem to render coherently and the
  coherence judge's to catch — it is not a composition concern. This keeps the configuration a set of four
  simple distributions rather than a 384-cell cross-product, at the cost of not being able to forbid a
  specific pairing.
- **Thresholds are defaults, not constants**: The four documented thresholds — composition ±2pp, privacy
  discard 0.5%, coherence discard 10%, coherence score 0.8 — are starting values chosen to make the
  requirements testable from the first run. They are configurable, and the coherence values in particular
  should be revisited once the rubric has been calibrated against human judgment (SC-011).
- **Generation requires network access; the privacy gate does not**: Producing conversations calls a hosted
  model, so a run needs credentials and connectivity. The privacy scan is deliberately offline and
  deterministic (FR-024), so the gate that protects the release path never depends on a remote service.
- **Model cost and time scale with corpus size, and judging roughly doubles both**: Every record costs at
  least two model calls — one to generate, one to judge — so a 100,000-record corpus is on the order of
  200,000 calls before retries and discards. SC-001 asserts the pipeline can produce that in one run without
  exhausting memory or needing manual intervention; it does not assert the run is cheap or quick. Budgeting
  and rate-limit strategy are planning concerns, and generating a smaller corpus is the normal case.
- **The coherence gate is non-deterministic and must be treated as such**: Judging is a model call, so the
  set of records that survive is not perfectly reproducible. This is why the judge's identity, parameters,
  rubric hash, and each record's score are all recorded — the gate is auditable even though it is not
  deterministic. FR-024 keeps the *privacy* gate offline and deterministic precisely so the irreversible-risk
  control never inherits this property.
- **Exact textual reproducibility is not claimed**: Model sampling is not reproducible in general. The
  constitution anticipates this by requiring non-deterministic inputs to be captured, so runs are auditable
  rather than bit-identical. Structure and composition remain reproducible.
- **Scenario variety rests on the prompt document**: Corpus diversity depends on the model elaborating
  varied subdomains from one committed prompt. FR-034's duplicate reporting is the feedback signal for
  whether that is working; a high duplicate rate indicates the prompt needs broadening.
- **The validation tool is a separate feature**: Checking datasets that external tools have postprocessed is
  feature 002. This feature validates only its own output, before writing it.
- **Privacy scanning of an arbitrary file is deliberate shared surface with feature 002**: The standalone
  scan command accepts any JSONL path, not only artifacts this project produced, because the approval loop
  needs a cheap way to re-check a corpus after the exception file changes — re-running generation to verify
  an approval would cost two model calls per record. That capability overlaps what feature 002 will need,
  and the overlap is accepted on the expectation that **002 reuses this implementation rather than growing a
  second one**. The boundary that still holds is ownership: this feature owns the blocking gate over its own
  output; 002 owns judging a dataset of uncertain provenance as a whole.
- **No released corpus is a deliverable here**: This feature ships the pipeline. Deciding to publish a
  particular corpus — with its datasheet and sampled human review — is a separate act governed by the
  constitution's release rules.
