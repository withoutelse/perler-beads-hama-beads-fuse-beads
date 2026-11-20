from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from app.domain.joint_booleans import JointBoolean
from app.domain.joint_reachability import (
    JointReachability,
    JointReachabilityExtraction,
    SkippedJointReachability,
)


class JointSpacingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class JointSpacingSkipReason(str, Enum):
    """Why a reachable joint cannot be placed without tearing the plate edge."""

    SPACING_TOO_NARROW = "spacing_too_narrow"
    CONTINUOUS_SLOT = "continuous_slot"
    EDGE_MARGIN_INSUFFICIENT = "edge_margin_insufficient"
    UNSUPPORTED_EDGE = "unsupported_edge"


@dataclass(frozen=True, slots=True)
class JointSpacingConfig:
    """Manufacturability rules for M4-T4 same-edge joint spacing.

    ``min_gap_cells`` is the extra material required between two joints on the
    same plate edge. The complete start-to-start spacing is
    ``max(left.width, right.width) + min_gap_cells``. ``min_edge_margin_cells``
    is the material that must remain between a slot footprint and either end of
    the contact edge. Both values default to two cells, matching the product
    tear-prevention rule. A slot gap of at least one cell is always required,
    so two slots may never touch or overlap.
    """

    min_gap_cells: int = 2
    min_edge_margin_cells: int = 2

    def __post_init__(self) -> None:
        for name, value in (
            ("min_gap_cells", self.min_gap_cells),
            ("min_edge_margin_cells", self.min_edge_margin_cells),
        ):
            if not _is_positive_int(value):
                raise JointSpacingError(
                    "JOINT_SPACING_INVALID_CONFIG",
                    f"{name} must be a positive integer",
                )
            if value < 2:
                raise JointSpacingError(
                    "JOINT_SPACING_INVALID_CONFIG",
                    f"{name} must be at least two cells",
                )


@dataclass(frozen=True, slots=True)
class JointSpacing:
    """A reachable joint that keeps a tear-resistant gap on its plate edge."""

    reachability: JointReachability
    boolean: JointBoolean
    plate_id: str
    contact_edge: str
    previous_joint_id: str | None = None
    next_joint_id: str | None = None
    gap_before_cells: int | None = None
    gap_after_cells: int | None = None
    slot_gap_before_cells: int | None = None
    slot_gap_after_cells: int | None = None
    required_gap_before_cells: int | None = None
    required_gap_after_cells: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reachability, JointReachability):
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "spacing must wrap a joint reachability record",
            )
        if not isinstance(self.boolean, JointBoolean):
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "spacing must wrap a joint boolean",
            )
        _validate_boolean_matches_reachability(self.boolean, self.reachability)
        if not self.plate_id or self.plate_id != self.reachability.plate_a:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "spacing plate must be the tongue plate",
            )
        if not self.contact_edge:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "contact edge label is required",
            )
        _validate_neighbor(
            "previous",
            self.previous_joint_id,
            self.gap_before_cells,
            self.slot_gap_before_cells,
            self.required_gap_before_cells,
            self.reachability.boolean_id,
        )
        _validate_neighbor(
            "next",
            self.next_joint_id,
            self.gap_after_cells,
            self.slot_gap_after_cells,
            self.required_gap_after_cells,
            self.reachability.boolean_id,
        )

    @property
    def id(self) -> str:
        return self.reachability.boolean_id

    @property
    def boolean_id(self) -> str:
        return self.reachability.boolean_id

    @property
    def candidate_id(self) -> str:
        return self.reachability.candidate_id

    @property
    def contact_edge_id(self) -> str:
        return self.reachability.contact_edge_id

    @property
    def plate_a(self) -> str:
        return self.reachability.plate_a

    @property
    def plate_b(self) -> str:
        return self.reachability.plate_b

    @property
    def position(self) -> int:
        return self.boolean.position

    @property
    def width(self) -> int:
        return self.boolean.width

    @property
    def slot_width(self) -> int:
        return self.boolean.slot_width

    @property
    def contact_length(self) -> int:
        return self.boolean.contact_length

    @property
    def edge_margin_cells(self) -> int:
        return self.boolean.edge_margin_cells


@dataclass(frozen=True, slots=True)
class SkippedJointSpacing:
    """A reachable joint rejected by same-edge spacing or edge-margin rules."""

    boolean_id: str
    candidate_id: str
    contact_edge_id: str
    plate_a: str
    plate_b: str
    contact_edge: str
    position: int
    width: int
    slot_width: int
    contact_length: int
    edge_margin_cells: int
    required_gap_cells: int
    actual_gap_cells: int
    slot_gap_cells: int
    reason: JointSpacingSkipReason
    conflict_joint_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        _validate_ids(
            self.boolean_id,
            self.candidate_id,
            self.contact_edge_id,
        )
        _validate_plates(self.plate_a, self.plate_b)
        if not self.contact_edge:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "contact edge label is required",
            )
        for name, value in (
            ("position", self.position),
            ("width", self.width),
            ("slot_width", self.slot_width),
            ("contact_length", self.contact_length),
            ("edge_margin_cells", self.edge_margin_cells),
            ("required_gap_cells", self.required_gap_cells),
            ("actual_gap_cells", self.actual_gap_cells),
            ("slot_gap_cells", self.slot_gap_cells),
        ):
            if not _is_non_negative_int(value):
                raise JointSpacingError(
                    "JOINT_SPACING_INVALID_RECORD",
                    f"{name} must be a non-negative integer",
                )
        if self.width <= 0 or self.slot_width <= self.width:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "slot width must be larger than tongue width",
            )
        if self.contact_length <= 0 or self.required_gap_cells <= 0:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "contact length and required gap must be positive",
            )
        if not isinstance(self.reason, JointSpacingSkipReason):
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                "skip reason must be a JointSpacingSkipReason",
            )
        if self.conflict_joint_id is not None:
            if not self.conflict_joint_id:
                raise JointSpacingError(
                    "JOINT_SPACING_INVALID_RECORD",
                    "conflict joint id must be non-empty when provided",
                )
            if self.conflict_joint_id == self.boolean_id:
                raise JointSpacingError(
                    "JOINT_SPACING_INVALID_RECORD",
                    "a joint cannot conflict with itself",
                )

    @property
    def id(self) -> str:
        return self.boolean_id


@dataclass(frozen=True, slots=True)
class JointSpacingExtraction:
    """M4-T4 spacing results together with the M4-T3 reachability they consume."""

    reachability: JointReachabilityExtraction
    accepted: tuple[JointSpacing, ...] = ()
    skipped: tuple[SkippedJointSpacing, ...] = ()

    def __post_init__(self) -> None:
        reachable_by_id = {
            record.boolean_id: record
            for record in self.reachability.reachable
        }
        boolean_by_id = {
            boolean.id: boolean for boolean in self.reachability.booleans.booleans
        }
        accepted_ids = [record.boolean_id for record in self.accepted]
        if len(accepted_ids) != len(set(accepted_ids)):
            raise JointSpacingError(
                "JOINT_SPACING_DUPLICATE_ID",
                "accepted joint ids must be unique",
            )
        skipped_ids = [record.boolean_id for record in self.skipped]
        if len(skipped_ids) != len(set(skipped_ids)):
            raise JointSpacingError(
                "JOINT_SPACING_DUPLICATE_ID",
                "skipped joint ids must be unique",
            )
        if set(accepted_ids) & set(skipped_ids):
            raise JointSpacingError(
                "JOINT_SPACING_DUPLICATE_REACHABILITY",
                "a reachable joint cannot be both accepted and skipped",
            )

        for accepted_record in self.accepted:
            source = reachable_by_id.get(accepted_record.boolean_id)
            if source is None:
                raise JointSpacingError(
                    "JOINT_SPACING_UNKNOWN_REACHABILITY",
                    "accepted spacing must reference a reachable joint",
                )
            _validate_spacing_matches_reachability(accepted_record, source)
            _validate_boolean_matches_reachability(accepted_record.boolean, source)

        for skipped_record in self.skipped:
            source = reachable_by_id.get(skipped_record.boolean_id)
            if source is None:
                raise JointSpacingError(
                    "JOINT_SPACING_UNKNOWN_REACHABILITY",
                    "skipped spacing must reference a reachable joint",
                )
            boolean = boolean_by_id.get(source.boolean_id)
            if boolean is None:
                raise JointSpacingError(
                    "JOINT_SPACING_UNKNOWN_REACHABILITY",
                    "reachable joint has no source boolean",
                )
            _validate_skipped_matches_reachability(
                skipped_record,
                source,
                boolean,
            )

    @property
    def graph(self):
        return self.reachability.graph

    @property
    def source(self) -> JointReachabilityExtraction:
        return self.reachability

    @property
    def reachability_extraction(self) -> JointReachabilityExtraction:
        return self.reachability

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def source_skipped(self) -> tuple[SkippedJointReachability, ...]:
        return self.reachability.skipped

    @property
    def unhandled_reachable(self) -> tuple[JointReachability, ...]:
        handled = {record.boolean_id for record in self.accepted}
        handled |= {record.boolean_id for record in self.skipped}
        return tuple(
            record
            for record in self.reachability.reachable
            if record.boolean_id not in handled
        )

    def spacing_by_id(self, boolean_id: str) -> JointSpacing:
        for record in self.accepted:
            if record.boolean_id == boolean_id:
                return record
        raise KeyError(boolean_id)

    def accepted_for_edge(self, contact_edge_id: str) -> tuple[JointSpacing, ...]:
        return tuple(
            record
            for record in self.accepted
            if record.contact_edge_id == contact_edge_id
        )

    def skipped_for_edge(
        self,
        contact_edge_id: str,
    ) -> tuple[SkippedJointSpacing, ...]:
        return tuple(
            record
            for record in self.skipped
            if record.contact_edge_id == contact_edge_id
        )

    def accepted_for_plate(self, plate_id: str) -> tuple[JointSpacing, ...]:
        if plate_id not in self.graph.nodes:
            raise JointSpacingError(
                "JOINT_SPACING_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )
        return tuple(
            record
            for record in self.accepted
            if plate_id in (record.plate_a, record.plate_b)
        )

    def skipped_for_plate(self, plate_id: str) -> tuple[SkippedJointSpacing, ...]:
        if plate_id not in self.graph.nodes:
            raise JointSpacingError(
                "JOINT_SPACING_UNKNOWN_PLATE",
                f"unknown plate {plate_id}",
            )
        return tuple(
            record
            for record in self.skipped
            if plate_id in (record.plate_a, record.plate_b)
        )


@dataclass(frozen=True, slots=True)
class _SpacingItem:
    reachability: JointReachability
    boolean: JointBoolean
    contact_edge: str


@dataclass(frozen=True, slots=True)
class _SpacingFootprint:
    """One joint footprint on one plate edge.

    A joint has a tongue footprint on plate A and a slot footprint on plate B.
    Both plates must be checked because two different tongues can share the same
    slot plate edge, and two different slots can share the same tongue plate
    edge.
    """

    item: _SpacingItem
    plate_id: str
    side: str
    start: int
    width: int
    contact_length: int
    edge_margin_cells: int


@dataclass(frozen=True, slots=True)
class _SpacingConflict:
    reason: JointSpacingSkipReason
    previous: _SpacingItem | None
    required_gap_cells: int
    actual_gap_cells: int
    slot_gap_cells: int
    detail: str


def generate_joint_spacing(
    reachability: JointReachabilityExtraction,
    config: JointSpacingConfig | None = None,
) -> JointSpacingExtraction:
    """Check same-plate, same-edge joint spacing and edge margins.

    M4-T3 already proves that each slot has a free path to the plate boundary.
    M4-T4 adds the remaining tear-prevention rule: joints on the same plate
    edge must keep ``max(width) + min_gap_cells`` start-to-start spacing, their
    slot footprints must not touch, and the slot must keep the configured edge
    margin. Both the tongue plate A and the slot plate B are checked. The
    earlier joint wins; later conflicting joints are recorded in ``skipped``
    with a stable reason. This stage does not construct the final ``Joint`` or
    ironing markers.
    """

    settings = config or JointSpacingConfig()
    boolean_by_id = {
        boolean.id: boolean for boolean in reachability.booleans.booleans
    }
    edge_by_id = {edge.id: edge for edge in reachability.graph.edges}
    items: list[_SpacingItem] = []
    for record in reachability.reachable:
        boolean = boolean_by_id.get(record.boolean_id)
        if boolean is None:
            raise JointSpacingError(
                "JOINT_SPACING_UNKNOWN_REACHABILITY",
                "reachable joint has no source boolean",
            )
        edge = edge_by_id.get(record.contact_edge_id)
        contact_edge = edge.contact_edge if edge is not None else record.contact_edge_id
        items.append(_SpacingItem(record, boolean, contact_edge))

    # A-side order is the canonical processing order. It is stable even when
    # two joints share only their B-side edge.
    items.sort(key=lambda item: (item.boolean.position, item.reachability.boolean_id))

    accepted_items: list[_SpacingItem] = []
    accepted_footprints: dict[
        tuple[str, str], list[_SpacingFootprint]
    ] = defaultdict(list)
    skipped_by_id: dict[str, SkippedJointSpacing] = {}

    for item in items:
        footprints = _spacing_footprints(item)
        margin_issue = _first_edge_margin_issue(footprints, settings)
        if margin_issue is not None:
            skipped_by_id[item.reachability.boolean_id] = _make_skipped(
                item,
                margin_issue.reason,
                margin_issue.required_gap_cells,
                margin_issue.actual_gap_cells,
                margin_issue.slot_gap_cells,
                None,
                margin_issue.detail,
            )
            continue

        conflict = _first_conflict(footprints, accepted_footprints, settings)
        if conflict is not None:
            skipped_by_id[item.reachability.boolean_id] = _make_skipped(
                item,
                conflict.reason,
                conflict.required_gap_cells,
                conflict.actual_gap_cells,
                conflict.slot_gap_cells,
                (
                    conflict.previous.reachability.boolean_id
                    if conflict.previous is not None
                    else None
                ),
                conflict.detail,
            )
            continue

        for footprint in footprints:
            accepted_footprints[
                (footprint.plate_id, item.contact_edge)
            ].append(footprint)
        accepted_items.append(item)

    accepted_by_id = _build_accepted_spacing(accepted_items, settings)

    accepted = tuple(
        accepted_by_id[record.boolean_id]
        for record in reachability.reachable
        if record.boolean_id in accepted_by_id
    )
    skipped = tuple(
        skipped_by_id[record.boolean_id]
        for record in reachability.reachable
        if record.boolean_id in skipped_by_id
    )
    return JointSpacingExtraction(
        reachability=reachability,
        accepted=accepted,
        skipped=skipped,
    )


def _spacing_footprints(item: _SpacingItem) -> tuple[_SpacingFootprint, ...]:
    boolean = item.boolean
    return (
        _SpacingFootprint(
            item=item,
            plate_id=item.reachability.plate_a,
            side="plate A",
            start=boolean.position,
            width=boolean.width,
            contact_length=boolean.contact_length,
            edge_margin_cells=boolean.edge_margin_cells,
        ),
        _SpacingFootprint(
            item=item,
            plate_id=item.reachability.plate_b,
            side="plate B",
            start=boolean.slot_u_start,
            width=boolean.slot_width,
            contact_length=boolean.contact_length,
            edge_margin_cells=boolean.edge_margin_cells,
        ),
    )


def _first_edge_margin_issue(
    footprints: tuple[_SpacingFootprint, ...],
    config: JointSpacingConfig,
) -> _SpacingConflict | None:
    for footprint in footprints:
        issue = _edge_margin_issue(footprint, config)
        if issue is not None:
            return issue
    return None


def _edge_margin_issue(
    footprint: _SpacingFootprint,
    config: JointSpacingConfig,
) -> _SpacingConflict | None:
    required_margin = max(
        config.min_edge_margin_cells,
        footprint.edge_margin_cells,
    )
    available_before = footprint.start
    available_after = footprint.contact_length - (
        footprint.start + footprint.width
    )
    if (
        available_before < required_margin
        or available_after < required_margin
    ):
        return _SpacingConflict(
            reason=JointSpacingSkipReason.EDGE_MARGIN_INSUFFICIENT,
            previous=None,
            required_gap_cells=required_margin,
            actual_gap_cells=max(0, min(available_before, available_after)),
            slot_gap_cells=0,
            detail=(
                f"{footprint.side} slot does not keep the configured edge margin "
                f"({available_before}/{available_after} < "
                f"{required_margin})"
            ),
        )
    return None


def _first_conflict(
    footprints: tuple[_SpacingFootprint, ...],
    accepted_footprints: dict[tuple[str, str], list[_SpacingFootprint]],
    config: JointSpacingConfig,
) -> _SpacingConflict | None:
    conflicts: list[_SpacingConflict] = []
    for footprint in footprints:
        accepted = accepted_footprints.get(
            (footprint.plate_id, footprint.item.contact_edge),
            (),
        )
        conflict = _find_conflict(footprint, accepted, config)
        if conflict is not None:
            conflicts.append(conflict)
    if not conflicts:
        return None
    return min(conflicts, key=_conflict_sort_key)


def _find_conflict(
    current: _SpacingFootprint,
    accepted: list[_SpacingFootprint] | tuple[()],
    config: JointSpacingConfig,
) -> _SpacingConflict | None:
    best: _SpacingConflict | None = None
    for previous in accepted:
        required_gap = _required_gap(previous.item, current.item, config)
        if previous.start <= current.start:
            actual_gap = current.start - previous.start
            slot_gap = current.start - (previous.start + previous.width)
        else:
            actual_gap = previous.start - current.start
            slot_gap = previous.start - (current.start + current.width)
        conflict: _SpacingConflict | None = None
        if slot_gap < 1:
            conflict = _SpacingConflict(
                reason=JointSpacingSkipReason.CONTINUOUS_SLOT,
                previous=previous.item,
                required_gap_cells=required_gap,
                actual_gap_cells=actual_gap,
                slot_gap_cells=max(0, slot_gap),
                detail=f"{current.side} slot footprints touch or overlap",
            )
        elif actual_gap < required_gap:
            conflict = _SpacingConflict(
                reason=JointSpacingSkipReason.SPACING_TOO_NARROW,
                previous=previous.item,
                required_gap_cells=required_gap,
                actual_gap_cells=actual_gap,
                slot_gap_cells=slot_gap,
                detail=f"{current.side} joint start positions are too close",
            )
        if conflict is not None and (
            best is None or _conflict_sort_key(conflict) < _conflict_sort_key(best)
        ):
            best = conflict
    return best


def _conflict_sort_key(conflict: _SpacingConflict) -> tuple[int, int, str]:
    previous_id = (
        conflict.previous.reachability.boolean_id
        if conflict.previous is not None
        else ""
    )
    return (conflict.slot_gap_cells, conflict.actual_gap_cells, previous_id)


def _build_accepted_spacing(
    accepted_items: list[_SpacingItem],
    config: JointSpacingConfig,
) -> dict[str, JointSpacing]:
    grouped: dict[tuple[str, str], list[_SpacingItem]] = defaultdict(list)
    for item in accepted_items:
        grouped[(item.reachability.plate_a, item.contact_edge)].append(item)

    accepted_by_id: dict[str, JointSpacing] = {}
    for items in grouped.values():
        items.sort(
            key=lambda item: (
                item.boolean.position,
                item.reachability.boolean_id,
            )
        )
        for index, item in enumerate(items):
            previous = items[index - 1] if index > 0 else None
            following = items[index + 1] if index + 1 < len(items) else None
            accepted_by_id[item.reachability.boolean_id] = JointSpacing(
                reachability=item.reachability,
                boolean=item.boolean,
                plate_id=item.reachability.plate_a,
                contact_edge=item.contact_edge,
                previous_joint_id=(
                    previous.reachability.boolean_id if previous is not None else None
                ),
                next_joint_id=(
                    following.reachability.boolean_id
                    if following is not None
                    else None
                ),
                gap_before_cells=(
                    _start_gap(previous, item) if previous is not None else None
                ),
                gap_after_cells=(
                    _start_gap(item, following) if following is not None else None
                ),
                slot_gap_before_cells=(
                    _slot_gap(previous, item) if previous is not None else None
                ),
                slot_gap_after_cells=(
                    _slot_gap(item, following) if following is not None else None
                ),
                required_gap_before_cells=(
                    _required_gap(previous, item, config)
                    if previous is not None
                    else None
                ),
                required_gap_after_cells=(
                    _required_gap(item, following, config)
                    if following is not None
                    else None
                ),
            )
    return accepted_by_id


def _required_gap(
    left: _SpacingItem,
    right: _SpacingItem,
    config: JointSpacingConfig,
) -> int:
    return max(left.boolean.width, right.boolean.width) + config.min_gap_cells


def _start_gap(
    left: _SpacingItem,
    right: _SpacingItem,
) -> int:
    return right.boolean.position - left.boolean.position


def _slot_gap(
    left: _SpacingItem,
    right: _SpacingItem,
) -> int:
    return right.boolean.position - (
        left.boolean.position + left.boolean.slot_width
    )


def _make_skipped(
    item: _SpacingItem,
    reason: JointSpacingSkipReason,
    required_gap_cells: int,
    actual_gap_cells: int,
    slot_gap_cells: int,
    conflict_joint_id: str | None,
    detail: str,
) -> SkippedJointSpacing:
    boolean = item.boolean
    return SkippedJointSpacing(
        boolean_id=item.reachability.boolean_id,
        candidate_id=item.reachability.candidate_id,
        contact_edge_id=item.reachability.contact_edge_id,
        plate_a=item.reachability.plate_a,
        plate_b=item.reachability.plate_b,
        contact_edge=item.contact_edge,
        position=boolean.position,
        width=boolean.width,
        slot_width=boolean.slot_width,
        contact_length=boolean.contact_length,
        edge_margin_cells=boolean.edge_margin_cells,
        required_gap_cells=required_gap_cells,
        actual_gap_cells=actual_gap_cells,
        slot_gap_cells=slot_gap_cells,
        reason=reason,
        conflict_joint_id=conflict_joint_id,
        detail=detail,
    )


def _validate_spacing_matches_reachability(
    record: JointSpacing,
    reachability: JointReachability,
) -> None:
    if (
        record.boolean_id != reachability.boolean_id
        or record.candidate_id != reachability.candidate_id
        or record.contact_edge_id != reachability.contact_edge_id
        or record.plate_a != reachability.plate_a
        or record.plate_b != reachability.plate_b
    ):
        raise JointSpacingError(
            "JOINT_SPACING_REACHABILITY_MISMATCH",
            "spacing metadata must match its reachability record",
        )


def _validate_boolean_matches_reachability(
    boolean: JointBoolean,
    reachability: JointReachability,
) -> None:
    if (
        boolean.id != reachability.boolean_id
        or boolean.candidate_id != reachability.candidate_id
        or boolean.contact_edge_id != reachability.contact_edge_id
        or boolean.plate_a != reachability.plate_a
        or boolean.plate_b != reachability.plate_b
    ):
        raise JointSpacingError(
            "JOINT_SPACING_REACHABILITY_MISMATCH",
            "joint boolean metadata must match its reachability record",
        )


def _validate_skipped_matches_reachability(
    record: SkippedJointSpacing,
    reachability: JointReachability,
    boolean: JointBoolean,
) -> None:
    if (
        record.boolean_id != reachability.boolean_id
        or record.candidate_id != reachability.candidate_id
        or record.contact_edge_id != reachability.contact_edge_id
        or record.plate_a != reachability.plate_a
        or record.plate_b != reachability.plate_b
        or record.position != boolean.position
        or record.width != boolean.width
        or record.slot_width != boolean.slot_width
        or record.contact_length != boolean.contact_length
        or record.edge_margin_cells != boolean.edge_margin_cells
    ):
        raise JointSpacingError(
            "JOINT_SPACING_REACHABILITY_MISMATCH",
            "skipped spacing metadata must match its reachability record",
        )


def _validate_neighbor(
    name: str,
    neighbor_id: str | None,
    gap: int | None,
    slot_gap: int | None,
    required_gap: int | None,
    own_id: str,
) -> None:
    if neighbor_id is None:
        if gap is not None or slot_gap is not None or required_gap is not None:
            raise JointSpacingError(
                "JOINT_SPACING_INVALID_RECORD",
                f"{name} gap requires a neighbor id",
            )
        return
    if not neighbor_id or neighbor_id == own_id:
        raise JointSpacingError(
            "JOINT_SPACING_INVALID_RECORD",
            f"{name} neighbor id must be non-empty and different",
        )
    if (
        gap is None
        or slot_gap is None
        or required_gap is None
        or not _is_non_negative_int(gap)
        or not _is_non_negative_int(slot_gap)
        or not _is_positive_int(required_gap)
    ):
        raise JointSpacingError(
            "JOINT_SPACING_INVALID_RECORD",
            f"{name} gaps must be non-negative and required gap positive",
        )
    if gap < required_gap or slot_gap < 1:
        raise JointSpacingError(
            "JOINT_SPACING_INVALID_RECORD",
            f"{name} joint does not satisfy the spacing rule",
        )


def _validate_ids(*values: str) -> None:
    if any(not value for value in values):
        raise JointSpacingError(
            "JOINT_SPACING_INVALID_RECORD",
            "spacing ids are required",
        )


def _validate_plates(plate_a: str, plate_b: str) -> None:
    if not plate_a or not plate_b or plate_a >= plate_b:
        raise JointSpacingError(
            "JOINT_SPACING_INVALID_RECORD",
            "spacing plates must be canonical and non-empty",
        )


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
