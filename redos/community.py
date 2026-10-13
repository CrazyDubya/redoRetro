"""Validated community records in the canonical World (M4.1).

This phase registers situated institutions, ties, and explicit rule records.
It does not adjudicate aid, hearings, labor agreements, or NPC decisions.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit

from .model import HistoricalProvenance, Institution, InstitutionalRule, ScheduleEntry, SocialTie, SupportDuty, World, require_finite


COMMUNITY_COLLECTIONS = {
    SocialTie: "social_ties",
    Institution: "institutions",
    InstitutionalRule: "institutional_rules",
    SupportDuty: "support_duties",
}
TIE_KINDS = frozenset({"kin", "patronage", "work", "apprenticeship", "mutual_aid", "congregation"})
INSTITUTION_KINDS = frozenset({"civic", "congregation", "poor_relief", "trade"})
RULE_ACTIONS = frozenset({"membership", "hearing", "relief", "gathering", "labor"})
RULE_REQUIREMENTS = frozenset({"member", "official", "documented_evidence"})
GENERATED_ID = re.compile(
    r"(?:event|lot|movement|observation|statement|contract|shipment|reposition|bank-account|bank-loan|holding|trade|policy|claim)-\d+"
)


def _interval(start: datetime, end: datetime | None, label: str) -> None:
    if not isinstance(start, datetime) or start.tzinfo is not None:
        raise ValueError(f"{label} must start at a naive canonical datetime")
    if end is not None:
        if not isinstance(end, datetime) or end.tzinfo is not None or end <= start:
            raise ValueError(f"{label} must end after its start")


def _ids(ids: tuple[str, ...], valid: dict, label: str) -> None:
    if not isinstance(ids, tuple) or any(not isinstance(key, str) or not key for key in ids):
        raise ValueError(f"{label} must be a tuple of nonempty IDs")
    if len(set(ids)) != len(ids) or any(key not in valid for key in ids):
        raise ValueError(f"{label} contains duplicate or unknown IDs")


def validate_community_entity(world: World, entity: SocialTie | Institution | InstitutionalRule | SupportDuty) -> None:
    """Preflight all references and bounds without mutating canonical state."""
    if not isinstance(entity.id, str) or not entity.id:
        raise ValueError("community ID must not be empty")
    if GENERATED_ID.fullmatch(entity.id):
        raise ValueError("community ID uses a reserved generated namespace")
    _interval(entity.starts_at, entity.ends_at, entity.id)
    provenance = entity.provenance
    if not isinstance(provenance, HistoricalProvenance):
        raise ValueError("community record requires typed historical provenance")
    _interval(provenance.applies_from, provenance.applies_until, "provenance")
    if not all(isinstance(value, str) and value.strip() for value in (
        provenance.source_url, provenance.claim, provenance.geographic_scope, provenance.uncertainty
    )):
        raise ValueError("provenance must specify source, claim, geography and uncertainty")
    source = urlsplit(provenance.source_url)
    if source.scheme not in {"https", "http"} or not source.netloc:
        raise ValueError("provenance source must be an HTTP(S) URL")
    if provenance.confidence not in {"documented", "supported", "reconstructed", "uncertain"}:
        raise ValueError("unknown provenance confidence")
    if entity.starts_at < provenance.applies_from or (
        provenance.applies_until is not None
        and (entity.ends_at is None or entity.ends_at > provenance.applies_until)
    ):
        raise ValueError("record interval exceeds its provenance applicability")

    if isinstance(entity, SocialTie):
        _ids((entity.actor_a_id, entity.actor_b_id), world.actors, "tie parties")
        if entity.kind not in TIE_KINDS or entity.visibility not in {"private", "public"}:
            raise ValueError("unknown tie kind or visibility")
        _ids(entity.evidence_event_ids, {event.id: event for event in world.events}, "tie evidence")
    elif isinstance(entity, Institution):
        if entity.kind not in INSTITUTION_KINDS or not isinstance(entity.name, str) or not entity.name.strip():
            raise ValueError("institution requires a name and supported kind")
        if entity.place_id not in world.places:
            raise ValueError("institution requires a canonical physical place")
        _ids(entity.jurisdiction_place_ids, world.places, "institution jurisdiction")
        if entity.place_id not in entity.jurisdiction_place_ids:
            raise ValueError("institution premises must be in its jurisdiction")
        _ids(entity.member_actor_ids, world.actors, "institution members")
        _ids(entity.official_actor_ids, world.actors, "institution officials")
        if not set(entity.official_actor_ids) <= set(entity.member_actor_ids):
            raise ValueError("institution officials must be members")
        if type(entity.capacity) is not int or entity.capacity <= 0:
            raise ValueError("institution capacity must be a positive integer")
        if entity.cash_holder_id is not None and entity.cash_holder_id not in {
            **world.actors, **world.businesses, **world.households
        }:
            raise ValueError("institution cash must use a canonical money holder")
        if entity.inventory_holder_id is not None:
            if entity.inventory_holder_id not in {**world.places, **world.businesses, **world.households}:
                raise ValueError("institution storage requires a stationary canonical holder")
            try:
                location = world.location_of(entity.inventory_holder_id)
            except KeyError as exc:
                raise ValueError("institution stock must use a canonical holder") from exc
            if location != entity.place_id:
                raise ValueError("institution storage must be at its premises")
        occupied: set[int] = set()
        if not isinstance(entity.operating_hours, tuple):
            raise ValueError("institution hours must be immutable records")
        for entry in entity.operating_hours:
            if (
                not isinstance(entry, ScheduleEntry)
                or type(entry.start_hour) is not int or type(entry.end_hour) is not int
                or not 0 <= entry.start_hour < entry.end_hour <= 24
                or entry.target_location_id != entity.place_id
            ):
                raise ValueError("institution hours require valid bounds and its premises")
            hours = set(range(entry.start_hour, entry.end_hour))
            if occupied & hours:
                raise ValueError("institution operating hours overlap")
            occupied.update(hours)
    elif isinstance(entity, InstitutionalRule):
        institution = world.institutions.get(entity.institution_id)
        if institution is None:
            raise ValueError("rule requires a registered institution")
        if entity.action not in RULE_ACTIONS or entity.requirement not in RULE_REQUIREMENTS:
            raise ValueError("unknown institutional action or requirement")
        if entity.starts_at < institution.starts_at or (
            institution.ends_at is not None
            and (entity.ends_at is None or entity.ends_at > institution.ends_at)
        ):
            raise ValueError("rule interval exceeds institution interval")
    else:
        if entity.supporter_id not in world.actors or entity.household_id not in world.households:
            raise ValueError("support duty requires an actor and household")
        if entity.jurisdiction_place_id not in world.places:
            raise ValueError("support duty requires a canonical jurisdiction")
        for value in (entity.amount, entity.period_hours):
            require_finite(value, "support duty")
        if entity.amount <= 0 or entity.period_hours < 1:
            raise ValueError("support amount must be positive and period at least one hour")
        _interval(entity.next_due_at, None, "support deadline")
        try:
            entity.next_due_at + timedelta(hours=entity.period_hours)
        except OverflowError as exc:
            raise ValueError("support interval exceeds canonical calendar") from exc
        if entity.next_due_at < entity.starts_at:
            raise ValueError("support deadline precedes duty")
        if entity.status not in {"active", "cancelled", "expired"}:
            raise ValueError("unknown support duty state")
        _ids(entity.causal_event_ids, {event.id: event for event in world.events}, "support evidence")


def validate_new_community_id(world: World, record_id: str) -> None:
    if not isinstance(record_id, str) or not record_id or GENERATED_ID.fullmatch(record_id):
        raise ValueError("record ID is empty or reserved")
    if any(
        record_id in collection for name, collection in vars(world).items()
        if isinstance(collection, dict) and not name.startswith("_")
    ) or any(event.id == record_id for event in world.events):
        raise ValueError(f"duplicate community ID {record_id}")


def register_community_entity(world: World, entity: SocialTie | Institution | InstitutionalRule | SupportDuty):
    """Register one validated record, with no replacement of existing IDs."""
    validate_new_community_id(world, entity.id)
    validate_community_entity(world, entity)
    collection = getattr(world, COMMUNITY_COLLECTIONS[type(entity)])
    collection[entity.id] = entity
    event = world.record(
        "community_record_registered", f"registered {type(entity).__name__} {entity.id}",
        entities=[entity.id],
        causes=entity.evidence_event_ids if isinstance(entity, SocialTie) else entity.causal_event_ids if isinstance(entity, SupportDuty) else (),
        data={"record_type": type(entity).__name__, "source": entity.provenance.source_url},
    )
    if isinstance(entity, SupportDuty):
        entity.causal_event_ids = (*entity.causal_event_ids, event.id)
    return entity


def set_institution_members(
    world: World, institution_id: str, member_actor_ids: tuple[str, ...], official_actor_ids: tuple[str, ...]
) -> Institution:
    """Explicitly replace the roster after validating every reference."""
    institution = world.institutions[institution_id]
    if not institution.starts_at <= world.now or (
        institution.ends_at is not None and world.now >= institution.ends_at
    ):
        raise ValueError("institution is not active at the current time")
    updated = replace(institution, member_actor_ids=member_actor_ids, official_actor_ids=official_actor_ids)
    validate_community_entity(world, updated)
    if updated == institution:
        return institution
    world.institutions[institution_id] = updated
    world.record("institution_roster_changed", f"changed roster of {institution_id}",
                 actors=member_actor_ids, entities=[institution_id])
    return updated


def community_errors(world: World) -> list[str]:
    """Audit the same invariants used by the registration gateways."""
    errors: list[str] = []
    seen: set[str] = set()
    for cls, name in COMMUNITY_COLLECTIONS.items():
        for key, entity in getattr(world, name).items():
            try:
                if type(entity) is not cls or key != entity.id or key in seen:
                    raise ValueError("invalid or duplicate community registry key")
                if any(
                    key in collection for other_name, collection in vars(world).items()
                    if isinstance(collection, dict) and not other_name.startswith("_") and other_name != name
                ) or any(event.id == key for event in world.events):
                    raise ValueError("community ID conflicts with another canonical record")
                seen.add(key)
                validate_community_entity(world, entity)
            except (ValueError, TypeError, AttributeError) as exc:
                errors.append(f"{name}:{key}: {exc}")
    return errors
