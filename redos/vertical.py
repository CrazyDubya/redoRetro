"""The first integrated Redos vertical slice.

This module deliberately contains orchestration, not a second world model.  It
invokes the canonical movement, inventory, payment, production, information,
and market gateways already used by the donor-specific kernels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations

from .bootstrap import build_micro_world
from .employment import charge_household_expense, pay_wages
from .living import Recipe, meet, produce, propagate_information, recollect, tell, witness_event
from .enterprise import compete
from .market import buy, refresh_market
from .model import Actor, Business, GoodType, JobOpening, Place, Route, ScheduleEntry, World
from .simulation import run_days, tick


@dataclass
class SliceState:
    world: World
    bread_market_id: str = "shop-market"
    incident_event_id: str | None = None
    incident_proposition: str = "dock-incident"
    incident_day: int = 5


def _ensure_good(world: World, good_id: str, name: str, price: float) -> None:
    if good_id not in world.goods:
        world.add(GoodType(good_id, name, price))


def _add_route(world: World, route_id: str, origin: str, destination: str) -> None:
    if route_id not in world.routes:
        world.add(Route(route_id, origin, destination, 0.2, 0, "walk"))


def _wire_block(world: World) -> None:
    coordinates = {
        "home-a": (0.0, 1.0), "home-b": (0.0, 0.0), "home-c": (0.0, -1.0),
        "tavern": (1.0, 0.0), "shop": (2.0, 0.0), "workshop": (2.0, -1.0),
        "warehouse": (3.0, -1.0), "dock": (3.0, 0.0), "north": (8.0, 0.0), "south": (8.0, -3.0),
    }
    for place_id, (x, y) in coordinates.items():
        if place_id in world.places:
            world.places[place_id].x = x
            world.places[place_id].y = y
    pairs = (
        ("tavern", "shop"), ("tavern", "workshop"), ("tavern", "dock"),
        ("tavern", "home-a"), ("tavern", "home-b"), ("tavern", "home-c"),
        ("shop", "workshop"), ("shop", "dock"), ("workshop", "warehouse"),
        ("workshop", "dock"),
    )
    for index, (origin, destination) in enumerate(pairs):
        _add_route(world, f"block-{index}-forward", origin, destination)
        _add_route(world, f"block-{index}-reverse", destination, origin)
    local_places = set(coordinates)
    for route in world.routes.values():
        if route.origin_id in local_places and route.destination_id in local_places:
            route.travel_days = 0


def _install_jobs(world: World) -> None:
    businesses = ("shop-market-cashier", "workshop-business", "tavern-business")
    occupations = ("shopkeeper", "cooper", "server")
    for index, actor_id in enumerate(f"citizen-{i}" for i in range(12)):
        actor = world.actors[actor_id]
        business_id = businesses[index % 3]
        occupation = occupations[index % 3]
        opening_id = f"opening-{occupation}"
        if opening_id not in world.job_openings:
            world.add(JobOpening(opening_id, business_id, occupation, 24.0, 8, 16))
        employer = world.businesses[business_id]
        actor.employer_id = business_id
        actor.occupation = occupation
        if actor_id not in employer.employees:
            employer.employees.append(actor_id)
        actor.schedule = [entry for entry in actor.schedule if entry.activity != "work"]
        actor.schedule.insert(1, ScheduleEntry(8, 16, "work", employer.location_id, priority=10, interruptible=False))


def build_integrated_world() -> SliceState:
    world = build_micro_world()
    _wire_block(world)
    _install_jobs(world)
    _ensure_good(world, "grain", "Grain", 4.0)
    _ensure_good(world, "flour", "Flour", 8.0)
    _ensure_good(world, "bread", "Bread", 12.0)
    workshop = world.businesses["workshop-business"]
    warehouse = world.businesses["warehouse-business"]
    tavern = world.businesses["tavern-business"]
    shop_market = world.markets["shop-market"]
    tavern.cash = 10_000.0
    workshop.cash = 10_000.0
    # The shop market uses the same physical place inventory as Star Trader.
    shop_market.fixed_prices["bread"] = 12.0
    shop_market.balances["bread"] = 100.0
    shop_market.demand_backlog["bread"] = 0.0
    shop_market.price_history["bread"] = [12.0]
    if world.quantity_held("shop", "bread") == 0:
        world.create_lot("bread", 100.0, holder_id="shop", owner_id="shop-market-cashier", provenance=("initial bakery stock",))
    if "bakery-business" not in world.businesses:
        world.add(Business("bakery-business", "Corner Bakery", "shop", "bakery", cash=5_000.0, advertising=1.0, price_markup={"bread": 0.05}))
        world.create_lot("bread", 20.0, holder_id="bakery-business", owner_id="bakery-business", provenance=("bakery production",))
    if world.quantity_held(workshop.id, "grain") < 20:
        world.transfer_goods("grain", 20 - world.quantity_held(workshop.id, "grain"), from_holder=warehouse.id, to_holder=workshop.id, to_owner=workshop.id, reason="workshop acquired grain input")
    workshop.production_rates["flour"] = 1.0
    tavern.production_rates["bread"] = 2.0
    for household in world.households.values():
        household.daily_expenses = 2.0
        if world.quantity_held(household.id, "bread") == 0:
            world.create_lot("bread", 5.0, holder_id=household.id, owner_id=household.id, provenance=("household provision",))
    # Two scheduled visitors make the incident genuinely witnessed in-world.
    for actor_id in ("citizen-1", "citizen-2"):
        actor = world.actors[actor_id]
        actor.schedule.insert(2, ScheduleEntry(12, 14, "visit dock", "dock", priority=20))
    return SliceState(world)


def _produce_and_route(world: World) -> None:
    workshop = world.businesses["workshop-business"]
    tavern = world.businesses["tavern-business"]
    warehouse = world.businesses["warehouse-business"]
    if world.quantity_held(workshop.id, "grain") < 1:
        available = world.quantity_held(warehouse.id, "grain")
        if available >= 5:
            world.transfer_goods("grain", 5, from_holder=warehouse.id, to_holder=workshop.id, to_owner=workshop.id, reason="workshop replenished grain")
    if world.quantity_held(workshop.id, "grain") >= 1:
        produce(world, workshop.id, Recipe("mill-grain", {"grain": 1}, "flour", 1))
    if world.quantity_held(workshop.id, "flour") >= 1:
        world.transfer_goods("flour", 1, from_holder=workshop.id, to_holder=tavern.id, to_owner=tavern.id, reason="flour delivered to tavern bakery")
    if world.quantity_held(tavern.id, "flour") >= 1:
        produce(world, tavern.id, Recipe("bake-bread", {"flour": 1}, "bread", 1))
        world.transfer_goods("bread", 1, from_holder=tavern.id, to_holder="shop", to_owner="shop-market-cashier", reason="bread delivered to shop")


def _daily_finance(world: World) -> None:
    for business_id in ("shop-market-cashier", "workshop-business", "tavern-business"):
        pay_wages(world, business_id)
    for household in world.households.values():
        member = household.members[0]
        charge_household_expense(world, member, household.daily_expenses, expense="rent and household costs", payee_id="tavern-business")


def _household_meals(world: World) -> None:
    for household in world.households.values():
        if world.quantity_held(household.id, "bread") >= 1:
            world.consume_goods(household.id, "bread", 1, reason="household ate bread")
            for actor_id in household.members:
                actor = world.actors[actor_id]
                actor.health = min(1.0, actor.health + 0.01)
                world.record("meal", f"{actor_id} ate with household", actors=[actor_id], entities=[household.id, "bread"])
        else:
            for actor_id in household.members:
                actor = world.actors[actor_id]
                actor.health = max(0.0, actor.health - 0.02)
                world.record("hunger", f"{actor_id} missed a household meal", actors=[actor_id], entities=[household.id])


def _shop_purchases(world: World) -> None:
    market = world.markets["shop-market"]
    for household in world.households.values():
        shopper = next((world.actors[actor_id] for actor_id in household.members if world.actors[actor_id].location_id == "shop" and world.actors[actor_id].traveling_to is None), None)
        if shopper is None or shopper.money < 12 or world.quantity_held("shop", "bread") < 1:
            continue
        try:
            buy(world, shopper.id, market.id, "bread", 1)
            world.transfer_goods("bread", 1, from_holder=shopper.id, to_holder=household.id, to_owner=household.id, reason="shopper brought bread home")
        except ValueError:
            continue


def _social_hour(world: World, slice_state: SliceState) -> None:
    patrons = [actor for actor in world.actors.values() if actor.location_id == "tavern" and actor.traveling_to is None]
    for first, second in combinations(patrons, 2):
        meet(world, first.id, second.id, location_id="tavern")
    if any(slice_state.incident_proposition in actor.beliefs for actor in patrons):
        propagate_information(world, proposition=slice_state.incident_proposition, location_id="tavern")


def _incident(world: World, slice_state: SliceState) -> None:
    if slice_state.incident_event_id is not None or world.now.day != slice_state.incident_day or world.now.hour != 13:
        return
    incident = world.record("incident", "a cargo seal was broken at the dock", entities=["dock", "warehouse"])
    slice_state.incident_event_id = incident.id
    witnesses = [actor.id for actor in world.actors.values() if actor.location_id == "dock" and actor.traveling_to is None]
    if not witnesses:
        return
    observations = witness_event(world, event_id=incident.id, content="I saw a cargo seal broken", witnesses=witnesses)
    for index, observation in enumerate(observations):
        if index == 0:
            recollect(world, observation.id, content="I saw someone near the cargo seal", confidence=0.45)
        actor = world.actors[observation.witness_id]
        actor.knowledge[slice_state.incident_proposition] = observation.id
        actor.beliefs[slice_state.incident_proposition] = world.observations[observation.id].recollection or observation.content


def run_autonomous_days(slice_state: SliceState, days: int) -> World:
    world = slice_state.world
    for _ in range(days):
        _daily_finance(world)
        _produce_and_route(world)
        for _hour in range(24):
            tick(world, 1)
            if world.now.hour == 7:
                _household_meals(world)
            if world.now.hour == 16:
                _shop_purchases(world)
            if world.now.hour == 19:
                _social_hour(world, slice_state)
            _incident(world, slice_state)
        for market_id in world.markets:
            refresh_market(world, market_id)
        compete(world, "shop-market", "bread")
    return world
