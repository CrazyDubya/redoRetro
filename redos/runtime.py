"""Data-driven autonomous adjudication for the first living-world slice.

The runtime advances canonical time and lets registered schedules, needs,
recipes, contracts, and social opportunities produce actions.  The fixture
only supplies those data declarations; it does not call meal, shopping,
production, or rumor commands itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .enterprise import advance_shipments, compete, create_contract, dispatch_contract
from .bank import accrue_deposit_interest, accrue_loan_interest
from .employment import charge_household_expense, pay_wages
from .living import Recipe, meet, produce, propagate_information, recollect, revise_belief, tell, witness_event
from .market import buy, refresh_market
from .model import Actor, World
from .simulation import _start_next_leg, route_path, tick
from .transport import advance_services, dispatch_freight


@dataclass(frozen=True)
class DockIncident:
    at: datetime
    proposition: str = "dock-incident"
    description: str = "a cargo seal was broken at the dock"


def _record_working_day(world: World, actor: Actor) -> bool:
    return bool(actor.work_hours_by_day.get(world.now.date().isoformat(), 0.0))


def _bounded_encounters(world: World, location_id: str) -> tuple[tuple[str, str], ...]:
    patrons = [actor for actor in world.actors.values() if actor.location_id == location_id and actor.traveling_to is None]
    world.random.shuffle(patrons)
    # A social opportunity produces a small number of encounters.  It is not
    # a complete graph and it does not create knowledge by itself.
    encounters = tuple((first.id, second.id) for first, second in zip(patrons[::2], patrons[1::2]))
    for first_id, second_id in encounters:
        first, second = world.actors[first_id], world.actors[second_id]
        meet(world, first.id, second.id, location_id=location_id)
    return encounters


def _has_near_term_obligation(world: World, actor: Actor) -> bool:
    if actor.current_activity and (actor.current_activity.startswith("work") or actor.current_activity.startswith("inspect")):
        return True
    if actor.schedule_override_until is not None and world.now < actor.schedule_override_until:
        return True
    hour = world.now.hour
    return any(
        entry.activity.startswith(("work", "inspect"))
        and hour <= entry.start_hour <= hour + 2
        for entry in actor.schedule
    )


def _food_trip_conflicts_with_work(world: World, actor: Actor, shop_id: str) -> bool:
    hour = world.now.hour
    starts = [
        (entry.start_hour - hour) % 24 or 24
        for entry in actor.schedule
        if entry.activity.startswith(("work", "inspect")) and entry.start_hour != hour
    ]
    if not starts:
        return False
    residence_id = world.households[actor.household_id].residence_id if actor.household_id else actor.location_id
    to_shop = route_path(world, actor.location_id, shop_id)
    home_path = route_path(world, shop_id, residence_id)
    travel_hours = sum(max(1.0, route.travel_days * 24.0) for route in [*to_shop, *home_path])
    return travel_hours + 1 >= min(starts)


def _adjudicate_food_need(world: World) -> None:
    shop_id = world.runtime.get("food_market_place", "shop")
    for household in world.households.values():
        members = [world.actors[actor_id] for actor_id in household.members]
        desired = max(1.0, len(members) * 1.5)
        held = world.quantity_held(household.id, "bread")
        need = max(0.0, desired - held)
        for actor in members:
            actor.needs["food"] = need
        if need <= 0 or any(actor.active_task in {"acquire food", "return with food"} for actor in members):
            continue
        shopper = next(
            (
                actor
                for actor in members
                if actor.traveling_to is None
                and actor.active_task is None
                and not _has_near_term_obligation(world, actor)
                and not _food_trip_conflicts_with_work(world, actor, shop_id)
            ),
            None,
        )
        if shopper is None:
            continue
        shopper.active_task = "acquire food"
        shopper.task_target_location_id = shop_id
        shopper.current_activity = shopper.intention = "acquire food"
        if shopper.location_id != shop_id:
            _start_next_leg(world, shopper, shop_id)
        else:
            world.record("intention_eligible", f"{shopper.id} can acquire household food", actors=[shopper.id], entities=[household.id])


def _complete_food_task(world: World, actor: Actor) -> None:
    if actor.active_task not in {"acquire food", "return with food"} or actor.traveling_to is not None:
        return
    household = world.households.get(actor.household_id or "")
    if household is None:
        actor.active_task = None
        return
    if actor.location_id == world.runtime.get("food_market_place", "shop"):
        market_id = world.runtime.get("food_market_id", "shop-market")
        if actor.money > 0:
            try:
                buy(world, actor.id, market_id, "bread", 1)
                actor.active_task = "return with food"
                actor.task_target_location_id = household.residence_id
                actor.current_activity = actor.intention = "return with food"
                _start_next_leg(world, actor, household.residence_id)
            except ValueError:
                world.record("need_unmet", f"{actor.id} could not afford or find household food", actors=[actor.id], entities=[household.id])
                actor.active_task = "return with food"
                actor.task_target_location_id = household.residence_id
                actor.current_activity = actor.intention = "return with food"
                _start_next_leg(world, actor, household.residence_id)
        else:
            world.record("need_unmet", f"{actor.id} had no cash for household food", actors=[actor.id], entities=[household.id])
        return
    if actor.active_task == "return with food" and actor.location_id == household.residence_id:
        if world.quantity_held(actor.id, "bread") >= 1:
            world.transfer_goods(
                "bread",
                1,
                from_holder=actor.id,
                to_holder=household.id,
                to_owner=household.id,
                reason="shopper delivered food home",
            )
        else:
            world.record("need_unmet", f"{actor.id} returned without household food", actors=[actor.id], entities=[household.id])
        actor.active_task = None
        actor.task_target_location_id = None
        actor.current_activity = actor.intention = "at home"
        world.record("need_satisfied", f"{household.id} received food at home", actors=[actor.id], entities=[household.id])


def _consume_meal(world: World, actor: Actor) -> None:
    if actor.current_activity != "eat" or actor.traveling_to is not None:
        return
    household = world.households.get(actor.household_id or "")
    if household is None or actor.location_id != household.residence_id:
        return
    if world.quantity_held(household.id, "bread") >= 1:
        consumed = world.consume_goods(household.id, "bread", 1, reason="household consumed food")
        for member_id in household.members:
            member = world.actors[member_id]
            member.needs["food"] = max(0.0, member.needs.get("food", 0.0) - 1.0)
            member.health = min(1.0, member.health + 0.01)
        world.record("meal", f"{household.id} ate a meal", actors=household.members, entities=[household.id, *consumed])
    else:
        for member_id in household.members:
            member = world.actors[member_id]
            member.health = max(0.2, member.health - 0.02)
        world.record("hunger", f"{household.id} missed a meal", actors=household.members, entities=[household.id])


def _has_open_flow(world: World, seller_id: str, buyer_id: str, good_id: str) -> bool:
    return any(
        contract.seller_id == seller_id and contract.buyer_id == buyer_id and contract.good_type_id == good_id
        and contract.status in {"open", "allocated", "in_transit"}
        for contract in world.contracts.values()
    )


def _matching_transport_services(world: World, contract) -> list[tuple]:
    services = tuple(world.runtime.get("transport_services", ()))
    return [
        service for service in services
        if len(service) >= 3
        and world.transport_facilities.get(service[1]) is not None
        and world.transport_facilities.get(service[2]) is not None
        and world.transport_facilities[service[1]].place_id == contract.origin_id
        and world.transport_facilities[service[2]].place_id == contract.destination_id
    ]


def _dispatch_commercial_contract(world: World, contract_id: str) -> bool:
    """Let declared carrier services compete for an economic obligation.

    The fixture declares which facilities participate in a recurring service;
    availability, capacity, route conditions and assignment conflicts remain
    canonical transport decisions.  If no service is configured for a flow,
    the existing non-carrier shipment path remains the compatible default.
    """
    contract = world.contracts[contract_id]
    matching = _matching_transport_services(world, contract)
    if not matching:
        dispatch_contract(world, contract_id)
        return True
    for carrier_id, origin_facility_id, destination_facility_id, *handling in matching:
        try:
            dispatch_freight(
                world,
                contract_id,
                carrier_id=carrier_id,
                origin_facility_id=origin_facility_id,
                destination_facility_id=destination_facility_id,
                loading_hours=float(handling[0]) if handling else 1.0,
                unloading_hours=float(handling[1]) if len(handling) > 1 else 1.0,
            )
            return True
        except (KeyError, ValueError):
            # A unavailable carrier leaves the contract open/allocated for a
            # later adjudication rather than creating a teleporting fallback.
            continue
    return False


def _adjudicate_businesses(world: World) -> None:
    # Input and output flows are data registered by the fixture.  The runtime
    # does not know that one of them is a mill or a bakery.
    for contract in list(world.contracts.values()):
        if contract.status == "open" and _matching_transport_services(world, contract):
            _dispatch_commercial_contract(world, contract.id)
    for seller_id, buyer_id, good_id, quantity, price in world.runtime.get("input_flows", ()):
        if world.quantity_held(buyer_id, good_id) >= quantity or world.quantity_held(seller_id, good_id) < quantity or _has_open_flow(world, seller_id, buyer_id, good_id):
            continue
        contract = create_contract(
            world, seller_id, buyer_id, good_id, quantity, price,
            origin_id=world.businesses[seller_id].location_id,
            destination_id=world.businesses[buyer_id].location_id,
            due_days=1,
        )
        if contract.status == "open":
            _dispatch_commercial_contract(world, contract.id)
    for business_id, recipes in world.recipes.items():
        business = world.businesses[business_id]
        if not any(_record_working_day(world, world.actors[actor_id]) for actor_id in business.employees):
            continue
        for recipe in recipes:
            target = business.inventory_targets.get(recipe.output_good_id, recipe.output_quantity)
            if world.quantity_held(business.id, recipe.output_good_id) >= target:
                continue
            capacity = business.production_capacity.get(recipe.id, 1.0)
            needed_output = max(0.0, target - world.quantity_held(business.id, recipe.output_good_id))
            batches = min(capacity, needed_output / recipe.output_quantity)
            for good_id, quantity in recipe.inputs.items():
                if quantity > 0:
                    batches = min(batches, world.quantity_held(business.id, good_id) / quantity)
            if batches > 1e-9:
                produce(world, business.id, recipe, scale=batches)
    for seller_id, buyer_id, good_id, quantity, price in world.runtime.get("business_flows", ()):
        seller = world.businesses[seller_id]
        buyer = world.businesses[buyer_id]
        if world.quantity_held(seller.id, good_id) < quantity or _has_open_flow(world, seller_id, buyer_id, good_id):
            continue
        contract = create_contract(
            world, seller_id, buyer_id, good_id, quantity, price,
            origin_id=seller.location_id, destination_id=buyer.location_id, due_days=1,
        )
        if contract.status == "open":
            _dispatch_commercial_contract(world, contract.id)


def _settle_day(world: World) -> None:
    for business_id in world.businesses:
        pay_wages(world, business_id)
    for household in world.households.values():
        if household.daily_expenses > 0 and household.members:
            charge_household_expense(world, household.members[0], household.daily_expenses, expense="household costs", payee_id=world.runtime.get("expense_payee"))
    _adjudicate_businesses(world)
    for market_id in world.markets:
        refresh_market(world, market_id)
    for market_id, good_id in world.runtime.get("competition_markets", ()):
        compete(world, market_id, good_id)


def _inject_external_event(world: World, incident: DockIncident) -> None:
    seen = world.runtime.setdefault("external_events", set())
    if incident.proposition in seen:
        return
    if world.now != incident.at:
        return
    event = world.record("incident", incident.description, entities=["dock", "warehouse"])
    witnesses = [actor.id for actor in world.actors.values() if actor.location_id == "dock" and actor.traveling_to is None]
    observations = witness_event(world, event_id=event.id, content="I saw a cargo seal broken", witnesses=witnesses)
    for index, observation in enumerate(observations):
        if index == 0:
            recollect(world, observation.id, content="I saw someone near the cargo seal", confidence=0.45)
        actor = world.actors[observation.witness_id]
        actor.knowledge[incident.proposition] = observation.id
        revise_belief(
            world,
            actor.id,
            incident.proposition,
            world.observations[observation.id].recollection or observation.content,
            truthful=True,
            source_kind="observation",
            source_id=observation.id,
        )
    seen.add(incident.proposition)


def adjudicate_hour(world: World, *, external_events: Iterable[DockIncident] = ()) -> None:
    _adjudicate_food_need(world)
    for incident in external_events:
        _inject_external_event(world, incident)
    for actor in world.actors.values():
        _complete_food_task(world, actor)
        _consume_meal(world, actor)
    encounter_pairs: list[tuple[str, str]] = []
    encounter_locations = {
        actor.location_id
        for actor in world.actors.values()
        if actor.current_activity == "visit tavern" and actor.location_id == "tavern" and actor.traveling_to is None
    }
    for location_id in sorted(encounter_locations):
        encounter_pairs.extend(_bounded_encounters(world, location_id))
    world.runtime["active_encounters"] = tuple(encounter_pairs)
    world.runtime["active_encounter_at"] = world.now
    if 18 <= world.now.hour < 22:
        patrons = [actor for actor in world.actors.values() if actor.location_id == "tavern" and actor.traveling_to is None]
        if patrons:
            propositions = {proposition for actor in patrons for proposition in actor.beliefs}
            for proposition in propositions:
                propagate_information(
                    world,
                    proposition=proposition,
                    location_id="tavern",
                    encounter_pairs=world.runtime.get("active_encounters", ()),
                )
    if world.now.hour == 17:
        _adjudicate_businesses(world)


def advance_world(world: World, hours: int = 1, *, external_events: Iterable[DockIncident] = ()) -> None:
    if hours < 0:
        raise ValueError("time cannot move backwards")
    incidents = tuple(external_events)
    for _ in range(hours):
        if world.now.hour == 23:
            _settle_day(world)
        tick(world, 1)
        advance_shipments(world, 1)
        freight_assets = set(world.runtime.pop("_freight_advanced_assets", set()))
        # Ordered carrier services are part of the normal world clock.  Tests
        # may advance them directly, but a registered service must also run
        # autonomously during ordinary simulation.  A service-backed carrier
        # gets one shared hour, never one hour in freight plus another hour in
        # its timetable service during the same world tick.
        advance_services(world, 1, excluded_asset_ids=freight_assets)
        # Financial obligations are ordinary world-clock participants.  The
        # kernels remain callable for focused operations, while live accounts
        # and loans accrue without a scenario script having to remember them.
        for account in world.bank_accounts.values():
            if account.status == "open":
                accrue_deposit_interest(world, account.id)
        for loan in world.bank_loans.values():
            if loan.status == "open":
                accrue_loan_interest(world, loan.id)
        adjudicate_hour(world, external_events=incidents)


def run(world: World, days: int, *, external_events: Iterable[DockIncident] = ()) -> World:
    for _ in range(days * 24):
        advance_world(world, 1, external_events=external_events)
    return world
