"""Slot planning — every seeded choice a record needs, computed before dispatch.

A run is N ordered slots. Each slot's choices are a pure function of ``(seed, position)``:
composition assignment, turn count, subdomain, and ticket timestamps (FR-012b, FR-006a). That
is what makes the corpus reproducible in structure regardless of concurrency (SC-013), and what
lets a discarded slot be retried in place without perturbing the corpus shape (research R3).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from ticket_dataset_generator.config.models import GenerationConfig
from ticket_dataset_generator.planning.apportion import apportion, apportion_dimension
from ticket_dataset_generator.planning.seeding import slot_random, stream_random
from ticket_dataset_generator.schema.enums import COMPOSITION_DIMENSIONS, ResolutionStatus


@dataclass(frozen=True, slots=True)
class Slot:
    """One unit of work. ``position`` becomes the record's ``record_index``."""

    position: int
    category: str
    priority: str
    channel: str
    resolution_status: str
    turn_count: int
    subdomain: str
    created_at: datetime
    resolved_at: datetime | None

    def metadata(self) -> dict[str, object]:
        """The assignment, shaped for
        :class:`~ticket_dataset_generator.schema.record.TicketMetadata`.
        """
        return {
            "category": self.category,
            "priority": self.priority,
            "channel": self.channel,
            "resolution_status": self.resolution_status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


def _assignment_pools(config: GenerationConfig, seed: int) -> dict[str, list[str]]:
    """Apportioned members, shuffled by a seed-derived generator, one list per dimension.

    Shuffling matters: without it every billing ticket would occupy the first block of
    positions, and any consumer taking a prefix of the corpus would get a skewed sample.
    """
    counts = apportion(config)
    pools: dict[str, list[str]] = {}
    for dimension in COMPOSITION_DIMENSIONS:
        pool: list[str] = []
        for member, count in sorted(counts[dimension].items()):
            pool.extend([member] * count)
        # A dimension-specific derivation so the four are shuffled independently. Keyed by the
        # dimension's *name* rather than by ``hash(name)``: Python randomises string hashing per
        # process, so that keyed the shuffle to the interpreter rather than to the seed, and two
        # runs of the same config assigned different composition to the same positions.
        stream_random(seed, f"pool/{dimension}").shuffle(pool)
        pools[dimension] = pool
    return pools


def _slot_at(
    config: GenerationConfig,
    seed: int,
    position: int,
    assignment: dict[str, str],
) -> Slot:
    """One slot: the composition ``assignment`` it was given, plus its seeded draws.

    Split out of :func:`plan_slots` because a top-up slot differs from an original one in
    exactly one respect — where its assignment comes from — and in none of the draws below.
    Keeping one body means a replacement record cannot drift from the shape of the record it
    replaces.
    """
    window_start = datetime.combine(config.time_window.start, datetime.min.time(), tzinfo=UTC)
    window_end = datetime.combine(config.time_window.end, datetime.min.time(), tzinfo=UTC)
    window_seconds = max(int((window_end - window_start).total_seconds()), 1)
    resolution_min = int(config.resolution_duration.min.total_seconds())
    resolution_max = int(config.resolution_duration.max.total_seconds())

    rng = slot_random(seed, position)
    resolution_status = assignment["resolution_status"]
    created_at = window_start + timedelta(seconds=rng.randrange(window_seconds))
    # Drawn before the conditional below, and deliberately so. ``resolved_at`` consumes from
    # this generator only for resolved tickets, so drawing the turn count afterwards made it
    # depend on the composition assignment — a change to the resolved/escalated split moved
    # every turn count with it. Unconditional draws come first so each stays a function of
    # (seed, position) alone.
    turn_count = rng.randint(config.turns.min, config.turns.max)
    # Present when and only when the ticket was resolved (FR-006b).
    resolved_at = (
        created_at + timedelta(seconds=rng.randint(resolution_min, resolution_max))
        if resolution_status == ResolutionStatus.RESOLVED
        else None
    )
    return Slot(
        position=position,
        category=assignment["category"],
        priority=assignment["priority"],
        channel=assignment["channel"],
        resolution_status=resolution_status,
        # Uniform over the range: naming the distribution is what stops two conforming
        # implementations producing materially different corpora (FR-009d).
        turn_count=turn_count,
        subdomain="",  # assigned separately, once the document's list is known
        created_at=created_at,
        resolved_at=resolved_at,
    )


def plan_slots(config: GenerationConfig, seed: int) -> list[Slot]:
    """Every slot for the run, in position order."""
    pools = _assignment_pools(config, seed)
    return [
        _slot_at(
            config,
            seed,
            position,
            {dimension: pools[dimension][position] for dimension in COMPOSITION_DIMENSIONS},
        )
        for position in range(config.record_count)
    ]


def plan_top_up_slots(
    config: GenerationConfig,
    seed: int,
    deficit: dict[str, dict[str, int]],
    *,
    start_position: int,
    count: int,
    round_index: int,
) -> list[Slot]:
    """Replacement slots for records the run planned but never wrote (FR-040).

    ``deficit`` is what apportionment assigned minus what the corpus actually holds, per member
    of each dimension. Drawing the replacements from *that* rather than from the original
    distribution is the whole point: the records that were lost are not a random sample of the
    corpus — a category the generator handles badly is discarded more often — so replacing them
    proportionally would leave the very drift the top-up exists to remove. Repairing the deficit
    instead pulls achieved composition back toward assigned.

    Positions continue past ``record_count`` rather than reusing the discarded ones. A position
    whose attempts were all discarded issued no identifier, so reuse would be permitted by
    FR-015b — but fresh positions keep writes strictly ascending, which is what lets the staging
    file stay a prefix of the corpus and a byte offset stay a valid recovery point (research R6).
    """
    pools: dict[str, list[str]] = {}
    for dimension in COMPOSITION_DIMENSIONS:
        pool: list[str] = []
        for member, missing in sorted(deficit.get(dimension, {}).items()):
            pool.extend([member] * max(missing, 0))
        # Short pools are possible: a dimension can be at or above its assignment while the
        # corpus as a whole is short, because discards are counted per record and a record
        # carries one member of every dimension. Top up from the requested distribution in that
        # case — there is no deficit to repair, only a corpus to fill.
        if len(pool) < count:
            fallback = apportion_dimension(getattr(config.effective_composition, dimension), count)
            for member, extra in sorted(fallback.items()):
                pool.extend([member] * extra)
        # Keyed by round as well as dimension: two rounds drawing the same stream would assign
        # the same members in the same order to different positions.
        stream_random(seed, f"topup/{round_index}/{dimension}").shuffle(pool)
        pools[dimension] = pool

    return [
        _slot_at(
            config,
            seed,
            start_position + offset,
            {dimension: pools[dimension][offset] for dimension in COMPOSITION_DIMENSIONS},
        )
        for offset in range(count)
    ]


def assign_subdomains(slots: Sequence[Slot], subdomains: Sequence[str], seed: int) -> list[Slot]:
    """Draw each slot's subdomain from the prompt document's declared list (FR-008d).

    Separate from :func:`plan_slots` because the list comes from a committed document that the
    planner should not have to read. The draw uses the same position-derived generator, so the
    subdomain is as reproducible as everything else.
    """
    if not subdomains:
        raise ValueError("no subdomains declared; the prompt document must list them (FR-008d)")
    ordered = sorted(subdomains)
    return [
        replace(
            slot,
            subdomain=ordered[slot_random(seed, slot.position, 0).randrange(len(ordered))],
        )
        for slot in slots
    ]
