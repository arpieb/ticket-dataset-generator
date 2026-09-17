"""Documented defaults (FR-033).

These are requirements, not implementation choices: changing them changes the corpus every
unconfigured run produces. The distribution and turn range below are the normative table in
FR-033; the thresholds are the four documented in the spec's Clarifications.
"""

from datetime import timedelta

from ticket_dataset_generator.schema.enums import Category, Channel, Priority, ResolutionStatus

DEFAULT_CATEGORY: dict[str, float] = {
    Category.BILLING: 0.25,
    Category.TECHNICAL: 0.25,
    Category.ACCOUNT: 0.20,
    Category.SHIPPING: 0.15,
    Category.PRODUCT: 0.10,
    Category.OTHER: 0.05,
}

DEFAULT_PRIORITY: dict[str, float] = {
    Priority.LOW: 0.20,
    Priority.NORMAL: 0.50,
    Priority.HIGH: 0.20,
    Priority.URGENT: 0.10,
}

DEFAULT_CHANNEL: dict[str, float] = {
    Channel.EMAIL: 0.40,
    Channel.CHAT: 0.35,
    Channel.PHONE: 0.15,
    Channel.WEB_FORM: 0.10,
}

DEFAULT_RESOLUTION_STATUS: dict[str, float] = {
    ResolutionStatus.RESOLVED: 0.70,
    ResolutionStatus.UNRESOLVED: 0.10,
    ResolutionStatus.ESCALATED: 0.15,
    ResolutionStatus.ABANDONED: 0.05,
}

DEFAULT_COMPOSITION: dict[str, dict[str, float]] = {
    "category": DEFAULT_CATEGORY,
    "priority": DEFAULT_PRIORITY,
    "channel": DEFAULT_CHANNEL,
    "resolution_status": DEFAULT_RESOLUTION_STATUS,
}

#: Turn-count range (FR-033). The floor of 2 lives in the config model; 4 is the default.
DEFAULT_TURNS_MIN = 4
DEFAULT_TURNS_MAX = 12

#: The smallest exchange that can be an exchange: one turn from each party (FR-009e).
MINIMUM_TURNS = 2

DEFAULT_COHERENCE_THRESHOLD = 0.8  # FR-009h
DEFAULT_COHERENCE_MAX_DISCARD_RATE = 0.10  # FR-009k
DEFAULT_PRIVACY_MAX_DISCARD_RATE = 0.005  # FR-021a
DEFAULT_COMPOSITION_TOLERANCE_PP = 2.0  # FR-031

#: A litellm model string: ``<provider>/<model>``. The default is a Claude model because that is
#: what this project was developed against, not because anything requires it — pointing either
#: role at another provider is a configuration change (research R1).
DEFAULT_MODEL_ID = "anthropic/claude-opus-4-5"
DEFAULT_MAX_TOKENS = 16_000

DEFAULT_MAX_CONCURRENCY = 8  # FR-012a
DEFAULT_REQUESTS_PER_MINUTE = 1_000  # FR-012e
DEFAULT_MAX_ATTEMPTS_PER_SLOT = 3  # FR-009o
DEFAULT_CONSECUTIVE_FAILURE_LIMIT = 50
DEFAULT_CHECKPOINT_INTERVAL = 100  # FR-015a

#: Whether a run generates replacement slots for discarded ones until the corpus actually holds
#: `record_count` records (FR-040). On, because the alternative is a corpus that is quietly
#: smaller than the one that was asked for -- exactly what FR-009c forbids.
DEFAULT_TOP_UP = True
#: The ceiling on that replacement work, as a fraction of `record_count`, across every round. A
#: generator discarding badly enough to exhaust this is defective, and the discard-rate gates
#: (FR-009k, FR-021a) will usually have stopped the run long before it is reached.
DEFAULT_MAX_TOP_UP_RATIO = 0.5

DEFAULT_LANGUAGE = "en"  # FR-009r

#: Ticket creation times are drawn from a window ending now-ish; the default spans 180 days.
DEFAULT_TIME_WINDOW_DAYS = 180
DEFAULT_RESOLUTION_MIN = timedelta(hours=1)  # FR-006a
DEFAULT_RESOLUTION_MAX = timedelta(days=14)

DEFAULT_PROMPT_DOCUMENT = "prompts/samples/consumer-electronics-support.md"
DEFAULT_RUBRIC = "prompts/coherence-rubric.md"
DEFAULT_EXCEPTIONS = "privacy/exceptions.json"

#: Release-path artifacts are distinguishable from scratch work by location alone (FR-013).
RELEASE_DIR = "data/release"
INTERIM_DIR = "data/interim"
