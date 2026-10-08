"""Fixture and compatibility entry point for the first Redos vertical slice.

The fixture declares people, schedules, recipes, needs, and business flows.
The driver only advances the generic runtime; it does not order named actors
to eat, shop, socialize, mill, or spread information.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .bootstrap import build_micro_world
from .living import Recipe
from .model import Business, GoodType, JobOpening, Route, ScheduleEntry, World
from .runtime import DockIncident, run


@dataclass
class SliceState:
    world: World
    bread_market_id: str = "shop-market"
    incident_event_id: str | None = None
    incident_proposition: str = "dock-incident"
    incident_day: int = 5


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
        world.places[place_id].x = x
        world.places[place_id].y = y
    pairs = (
        ("tavern", "shop"), ("tavern", "workshop"), ("tavern", "dock"),
        ("tavern", "home-a"), ("tavern", "home-b"), ("tavern", "home-c"),
        ("shop", "workshop"), ("shop", "dock"), ("workshop", "warehouse"),
        ("workshop", "dock"), ("home-a", "tavern"), ("home-b", "shop"), ("home-c", "workshop"),
    )
    for index, (origin, destination) in enumerate(pairs):
        _add_route(world, f"block-{index}-forward", origin, destination)
        _add_route(world, f"block-{index}-reverse", destination, origin)
    local_places = set(coordinates)
    for route in world.routes.values():
        if route.origin_id in local_places and route.destination_id in local_places:
            route.travel_days = 0


def _install_jobs(world: World) -> None:
    assignments = (
        ("shop-market-cashier", "shopkeeper"),
        ("workshop-business", "cooper"),
        ("tavern-business", "server"),
        ("warehouse-business", "warehouse clerk"),
    )
    dock_staff = []
    for index, actor_id in enumerate(f"citizen-{i}" for i in range(12)):
        actor = world.actors[actor_id]
        business_id, occupation = assignments[index % len(assignments)]
        opening_id = f"opening-{occupation}"
        if opening_id not in world.job_openings:
            world.add(JobOpening(opening_id, business_id, occupation, 24.0, 8, 16))
        employer = world.businesses[business_id]
        actor.employer_id = business_id
        actor.occupation = occupation
        if actor_id not in employer.employees:
            employer.employees.append(actor_id)
        residence = actor.household_id and world.households[actor.household_id].residence_id or actor.location_id
        actor.schedule = [ScheduleEntry(0, 7, "sleep", residence), ScheduleEntry(7, 8, "eat", residence)]
        actor.schedule.append(ScheduleEntry(8, 16, "work", employer.location_id, priority=10, interruptible=False))
        if business_id == "warehouse-business":
            dock_staff.append(actor)
        if index in {0, 3, 5, 8, 10}:
            actor.schedule.append(ScheduleEntry(18, 22, "visit tavern", "tavern"))
    # Dock work is an ordinary warehouse duty, not an incident-specific list
    # of witnesses.  Rotate two cargo clerks into the duty by seed; the
    # external incident does not name or select either clerk.
    for offset in range(min(2, len(dock_staff))):
        dock_worker = dock_staff[(world.seed + offset) % len(dock_staff)]
        dock_worker.schedule.append(ScheduleEntry(11, 14, "inspect dock", "dock", priority=11))


def build_integrated_world(*, seed: int = 0) -> SliceState:
    world = build_micro_world(seed=seed)
    _wire_block(world)
    _install_jobs(world)
    for good_id, name, price in (("grain", "Grain", 4.0), ("flour", "Flour", 8.0), ("bread", "Bread", 12.0)):
        if good_id not in world.goods:
            world.add(GoodType(good_id, name, price))
    workshop = world.businesses["workshop-business"]
    tavern = world.businesses["tavern-business"]
    shop_cashier = world.businesses["shop-market-cashier"]
    warehouse = world.businesses["warehouse-business"]
    for business in (workshop, tavern, warehouse):
        business.cash = max(business.cash, 10_000.0)
    market = world.markets["shop-market"]
    market.fixed_prices["bread"] = 12.0
    market.balances["bread"] = world.quantity_held("shop", "bread")
    market.demand_backlog["bread"] = 0.0
    market.price_history["bread"] = [12.0]
    if world.quantity_held("shop", "bread") == 0:
        world.create_lot("bread", 30.0, holder_id="shop", owner_id=shop_cashier.id, provenance=("initial shop stock",))
    if "bakery-business" not in world.businesses:
        world.add(Business("bakery-business", "Corner Bakery", "shop", "bakery", cash=5_000.0, advertising=1.0, price_markup={"bread": 0.05}))
        world.create_lot("bread", 20.0, holder_id="bakery-business", owner_id="bakery-business", provenance=("bakery production",))
    workshop.inventory_targets["flour"] = 5.0
    tavern.inventory_targets["bread"] = 5.0
    world.recipes[workshop.id] = [Recipe("mill-grain", {"grain": 1}, "flour", 1)]
    world.recipes[tavern.id] = [Recipe("bake-bread", {"flour": 1}, "bread", 1)]
    for household in world.households.values():
        household.daily_expenses = 2.0
    world.runtime.update({
        "food_market_place": "shop",
        "food_market_id": "shop-market",
        "expense_payee": "tavern-business",
        "input_flows": (("warehouse-business", "workshop-business", "grain", 5.0, 4.0), ("workshop-business", "tavern-business", "flour", 1.0, 8.0)),
        "business_flows": (("tavern-business", "shop-market-cashier", "bread", 1.0, 12.0),),
        "competition_markets": (("shop-market", "bread"),),
    })
    return SliceState(world)


def run_autonomous_days(slice_state: SliceState, days: int, *, external_events: tuple[DockIncident, ...] = ()) -> World:
    """Compatibility wrapper whose only world action is generic time advance."""
    world = run(slice_state.world, days, external_events=external_events)
    incident = next((event for event in world.events if event.kind == "incident"), None)
    slice_state.incident_event_id = incident.id if incident else None
    return world


def default_dock_incident(slice_state: SliceState) -> DockIncident:
    return DockIncident(slice_state.world.now + timedelta(days=slice_state.incident_day - 1, hours=13))
