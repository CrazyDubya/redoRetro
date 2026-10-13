"""Household continuity and support using canonical resources and obligations."""

from dataclasses import replace
from datetime import timedelta

from .community import _ids, _interval, validate_new_community_id
from .model import Obligation, World, require_finite


HOUSEHOLD_ARRANGEMENTS = {"unspecified", "wage_dependent", "independent_tradesperson", "dependent_extended"}
OBLIGATION_TRANSITIONS = {
    "open": {"defaulted", "settled", "cancelled"},
    "defaulted": {"settled", "cancelled"},
    "settled": set(), "cancelled": set(),
}


def _money_holder(world: World, holder_id: str):
    holder = world.actors.get(holder_id) or world.businesses.get(holder_id) or world.households.get(holder_id)
    if holder is None:
        raise ValueError("obligation requires a canonical money holder")
    return holder


def validate_obligation(world: World, obligation: Obligation) -> None:
    _money_holder(world, obligation.debtor_id)
    _money_holder(world, obligation.creditor_id)
    if obligation.debtor_id == obligation.creditor_id:
        raise ValueError("obligation parties must be distinct")
    if obligation.jurisdiction_place_id not in world.places:
        raise ValueError("obligation requires a canonical jurisdiction")
    source = world.support_duties.get(obligation.source_id)
    if source is None:
        raise ValueError("support obligation requires an existing duty")
    if (obligation.debtor_id, obligation.creditor_id, obligation.jurisdiction_place_id, obligation.amount) != (
        source.supporter_id, source.household_id, source.jurisdiction_place_id, source.amount
    ):
        raise ValueError("obligation does not match its signed source")
    if obligation.due_at < source.starts_at or (source.ends_at is not None and obligation.due_at >= source.ends_at):
        raise ValueError("obligation deadline exceeds source interval")
    _interval(obligation.due_at, None, "obligation deadline")
    for value in (obligation.amount, obligation.paid, obligation.accounted_debt):
        require_finite(value, "obligation")
    if obligation.amount <= 0 or not 0 <= obligation.paid <= obligation.amount or not 0 <= obligation.accounted_debt <= obligation.amount - obligation.paid + 1e-9:
        raise ValueError("invalid obligation amount or reconciliation")
    if obligation.status not in OBLIGATION_TRANSITIONS:
        raise ValueError("unknown obligation state")
    if obligation.status == "settled" and abs(obligation.paid - obligation.amount) > 1e-9:
        raise ValueError("settled obligation is not fully paid")
    _ids(obligation.causal_event_ids, {event.id: event for event in world.events}, "obligation causes")


def register_obligation(world: World, obligation: Obligation) -> Obligation:
    validate_new_community_id(world, obligation.id)
    validate_obligation(world, obligation)
    if obligation.status != "open" or obligation.paid != 0 or obligation.accounted_debt != 0:
        raise ValueError("new obligation must be unpaid and open")
    if world.support_duties[obligation.source_id].status != "active":
        raise ValueError("source duty cannot create new obligations")
    world.obligations[obligation.id] = obligation
    event = world.record("obligation_created", f"{obligation.debtor_id} owes {obligation.creditor_id}",
                         actors=[obligation.debtor_id, obligation.creditor_id], entities=[obligation.id, obligation.source_id],
                         causes=obligation.causal_event_ids,
                         data={"amount": obligation.amount, "due_at": obligation.due_at.isoformat(), "jurisdiction": obligation.jurisdiction_place_id})
    obligation.causal_event_ids = (*obligation.causal_event_ids, event.id)
    return obligation


def settle_obligation(world: World, obligation_id: str, *, amount: float | None = None) -> float:
    obligation = world.obligations[obligation_id]
    validate_obligation(world, obligation)
    if obligation.status == "settled" and amount is None:
        return 0.0
    if obligation.status not in {"open", "defaulted"}:
        raise ValueError("obligation is not payable")
    remaining = obligation.amount - obligation.paid
    payment_amount = remaining if amount is None else require_finite(amount, "obligation payment")
    if not 0 < payment_amount <= remaining + 1e-9:
        raise ValueError("payment exceeds the outstanding obligation")
    payment_amount = min(payment_amount, remaining)
    debtor = _money_holder(world, obligation.debtor_id)
    retired_debt = min(obligation.accounted_debt, payment_amount)
    require_finite(debtor.debt, "debtor debt")
    if debtor.debt + 1e-9 < retired_debt:
        raise ValueError("debtor debt does not reconcile with obligation")
    # World.pay prevalidates both balances; nothing is mutated before it.
    payment = world.pay(obligation.debtor_id, obligation.creditor_id, payment_amount,
                        causes=obligation.causal_event_ids[-1:], reason="community obligation payment")
    debtor.debt -= retired_debt
    obligation.accounted_debt -= retired_debt
    obligation.paid += payment_amount
    if abs(obligation.paid - obligation.amount) < 1e-9:
        obligation.status = "settled"
    event = world.record("obligation_payment", f"paid {payment_amount} toward {obligation_id}",
                         actors=[obligation.debtor_id, obligation.creditor_id], entities=[obligation.id, obligation.source_id],
                         causes=[payment.id], data={"amount": payment_amount, "remaining": obligation.amount - obligation.paid, "status": obligation.status})
    obligation.causal_event_ids = (*obligation.causal_event_ids, event.id)
    return payment_amount


def default_obligation(world: World, obligation_id: str) -> None:
    obligation = world.obligations[obligation_id]
    if obligation.status != "open":
        return
    if world.now < obligation.due_at:
        raise ValueError("obligation is not due")
    validate_obligation(world, obligation)
    debtor = _money_holder(world, obligation.debtor_id)
    remaining = obligation.amount - obligation.paid
    projected = require_finite(debtor.debt + remaining, "default debt")
    debtor.debt = projected
    obligation.accounted_debt = remaining
    obligation.status = "defaulted"
    event = world.record("obligation_defaulted", f"{obligation.debtor_id} missed {obligation.id}",
                         actors=[obligation.debtor_id, obligation.creditor_id], entities=[obligation.id, obligation.source_id],
                         causes=obligation.causal_event_ids[-1:], data={"remaining": remaining})
    obligation.causal_event_ids = (*obligation.causal_event_ids, event.id)


def cancel_support(world: World, duty_id: str) -> None:
    duty = world.support_duties[duty_id]
    if duty.status == "cancelled":
        return
    if duty.status != "active":
        raise ValueError("support duty is not active")
    duty.status = "cancelled"
    event = world.record("support_cancelled", f"future support cancelled for {duty_id}",
                         actors=[duty.supporter_id], entities=[duty.id, duty.household_id],
                         causes=duty.causal_event_ids[-1:])
    duty.causal_event_ids = (*duty.causal_event_ids, event.id)


def advance_household_support(world: World) -> None:
    for duty in world.support_duties.values():
        while duty.status == "active" and duty.next_due_at <= world.now and (duty.ends_at is None or duty.next_due_at < duty.ends_at):
            obligation_id = f"support:{duty.id}:{duty.next_due_at.isoformat()}"
            if obligation_id not in world.obligations:
                world.add(Obligation(obligation_id, duty.supporter_id, duty.household_id,
                                     duty.jurisdiction_place_id, duty.amount, duty.next_due_at, duty.id,
                                     causal_event_ids=duty.causal_event_ids))
            duty.next_due_at += timedelta(hours=duty.period_hours)
        if duty.status == "active" and duty.ends_at is not None and world.now >= duty.ends_at:
            duty.status = "expired"
            event = world.record("support_expired", f"{duty.id} reached its term", entities=[duty.id, duty.household_id],
                                 causes=duty.causal_event_ids[-1:])
            duty.causal_event_ids = (*duty.causal_event_ids, event.id)
    for obligation in list(world.obligations.values()):
        if obligation.status not in {"open", "defaulted"} or obligation.due_at > world.now:
            continue
        try:
            settle_obligation(world, obligation.id)
        except ValueError:
            default_obligation(world, obligation.id)


def change_household_membership(world: World, actor_id: str, household_id: str, *, causes: tuple[str, ...] = ()) -> None:
    actor = world.actors[actor_id]
    target = world.households[household_id]
    _ids(causes, {event.id: event for event in world.events}, "membership causes")
    if actor.household_id == household_id:
        return
    if actor.active_task in {"acquire food", "return with food"}:
        raise ValueError("finish the existing household acquisition before changing membership")
    if actor_id in target.members:
        raise ValueError("inconsistent household membership")
    previous = world.households.get(actor.household_id or "")
    if previous is not None and actor_id not in previous.members:
        raise ValueError("inconsistent previous household membership")
    new_schedule = [replace(entry, target_location_id=target.residence_id)
                    if entry.activity in {"eat", "sleep", "leisure at home"} else entry for entry in actor.schedule]
    if previous is not None:
        previous.members.remove(actor_id)
    target.members.append(actor_id)
    actor.household_id = target.id
    actor.schedule = new_schedule
    world.record("household_membership_changed", f"{actor_id} joined {household_id}", actors=[actor_id],
                 entities=[household_id, *([previous.id] if previous else [])], causes=causes,
                 data={"previous_household": previous.id if previous else None, "residence": target.residence_id})


def change_household_residence(world: World, household_id: str, place_id: str, *, causes: tuple[str, ...] = ()) -> None:
    household = world.households[household_id]
    if place_id not in world.places:
        raise ValueError("unknown residence")
    _ids(causes, {event.id: event for event in world.events}, "residence causes")
    if place_id == household.residence_id:
        return
    old_place = household.residence_id
    _ids(tuple(household.members), world.actors, "residence members")
    if any(institution.inventory_holder_id == household_id and institution.place_id != place_id
           for institution in world.institutions.values()):
        raise ValueError("household is registered as stationary institution storage")
    # Leave lots physically stored at the former residence. This metadata
    # change is not a moving service; actors and possessions must travel later.
    lots = world.lots_held_by(household.id)
    for lot in lots:
        if not world._lot_is_available_at(lot, old_place):
            raise ValueError("household possessions are encumbered")
    event = world.record("household_residence_changed", f"{household_id} changed residence", entities=[household_id, old_place, place_id],
                         causes=causes, data={"from": old_place, "to": place_id})
    for lot in lots:
        lot.holder_id = old_place
        lot.provenance = (*lot.provenance, event.id)
    household.residence_id = place_id
    for member_id in household.members:
        member = world.actors[member_id]
        member.schedule = [replace(entry, target_location_id=place_id)
                           if entry.activity in {"eat", "sleep", "leisure at home"} else entry for entry in member.schedule]
        if member.active_task == "return with food":
            member.task_target_location_id = place_id
    world._sync_market_balances(old_place)


def fund_household_shopper(world: World, actor_id: str, cost: float) -> bool:
    require_finite(cost, "shopping cost")
    if cost <= 0:
        raise ValueError("shopping cost must be positive")
    actor = world.actors[actor_id]
    household = world.households[actor.household_id]
    if actor.money >= cost:
        return True
    needed = cost - actor.money
    if household.cash < needed or actor.traveling_to is not None or actor.location_id != household.residence_id:
        return False
    causes = tuple(event.id for event in reversed(world.events)
                   if event.kind == "obligation_payment" and household.id in event.actors)[:1]
    allowance = world.pay(household.id, actor.id, needed, causes=causes, reason="household food acquisition allowance")
    world.runtime.setdefault("_household_shopping_causes", {})[actor.id] = (allowance.id,)
    return True


def household_food_evidence(world: World, household_id: str, quantity: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Select actual meal lots and the transfer events that supplied those lots."""
    selected: list[str] = []
    causes: list[str] = []
    remaining = quantity
    for lot in world.lots_held_by(household_id, "bread"):
        selected.append(lot.id)
        transfer = next((event for event in reversed(world.events)
                         if event.kind == "goods_transfer" and lot.id in event.entities), None)
        if transfer is not None:
            causes.append(transfer.id)
        remaining -= lot.quantity
        if remaining <= 1e-9:
            break
    return tuple(selected), tuple(dict.fromkeys(causes))


def household_errors(world: World) -> list[str]:
    errors: list[str] = []
    seen_members: set[str] = set()
    for household in world.households.values():
        if household.arrangement not in HOUSEHOLD_ARRANGEMENTS or household.residence_id not in world.places:
            errors.append(f"{household.id} has invalid arrangement or residence")
        for member_id in household.members:
            if member_id in seen_members or member_id not in world.actors or world.actors[member_id].household_id != household.id:
                errors.append(f"{household.id} has inconsistent member {member_id}")
            seen_members.add(member_id)
    for actor in world.actors.values():
        if actor.household_id is not None and actor.id not in seen_members:
            errors.append(f"{actor.id} has unregistered household membership")
    for key, obligation in world.obligations.items():
        try:
            if key != obligation.id:
                raise ValueError("obligation key mismatch")
            if any(key in registry for name, registry in vars(world).items()
                   if isinstance(registry, dict) and not name.startswith("_") and name != "obligations"):
                raise ValueError("obligation ID conflicts with a canonical record")
            validate_obligation(world, obligation)
        except (ValueError, AttributeError) as exc:
            errors.append(f"{key}: {exc}")
    return errors
