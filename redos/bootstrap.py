"""Factories used by tests and the first vertical-slice experiments."""

from __future__ import annotations

from .market import create_star_market, install_star_goods
from .model import Actor, Business, GoodType, Household, Place, Route, ScheduleEntry, World


def build_tiny_world(*, seed: int = 0) -> World:
    world = World(seed=seed)
    for place in (
        Place("tavern", "The Red Lantern", 2),
        Place("cellar", "Tavern cellar", 2, parent_id="tavern"),
        Place("shop", "Martha's Shop", 1),
        Place("workshop", "Cooper's Workshop", 1),
        Place("warehouse", "Quayside Warehouse", 1),
        Place("dock", "Old Dock", 1),
        Place("north", "North Market", 10),
        Place("south", "South Market", 1),
    ):
        world.add(place)
    routes = (
        Route("tavern-shop", "tavern", "shop", 0.4, 1),
        Route("shop-north", "shop", "north", 2.0, 2),
        Route("north-south", "north", "south", 3.0, 3),
        Route("south-north", "south", "north", 3.0, 3),
        Route("shop-tavern", "shop", "tavern", 0.4, 1),
        Route("shop-warehouse", "shop", "warehouse", 0.8, 1),
        Route("warehouse-shop", "warehouse", "shop", 0.8, 1),
    )
    for route in routes:
        world.add(route)
    install_star_goods(world)
    for market_id, place_id in (("shop-market", "shop"), ("north-market", "north"), ("south-market", "south")):
        world.add(Business(f"{market_id}-cashier", f"{place_id.title()} cashier", place_id, "market", cash=250_000.0))
        create_star_market(world, market_id, place_id)
    world.add(Business("tavern-business", "Red Lantern Tavern", "tavern", "tavern", cash=500.0))
    world.add(Business("workshop-business", "Cooper's Workshop", "workshop", "workshop", cash=2_000.0))
    world.add(Business("warehouse-business", "Quayside Warehouse", "warehouse", "warehouse", cash=1_000.0))
    world.add(Household("merchant-household", "Merchant household", "tavern", cash=100.0))
    world.add(Actor("merchant", "Ada", "shop", age=31, household_id="merchant-household", money=40_000.0, skills={"trade": 1.0, "access": ["cellar"]}))
    world.households["merchant-household"].members.append("merchant")
    world.add(Actor("cooper", "Thomas", "workshop", age=42, occupation="cooper", employer_id="workshop-business", money=120.0))
    world.businesses["workshop-business"].employees.append("cooper")
    return world


def build_micro_world(*, seed: int = 0) -> World:
    """Build the first architecture-test block: 12 persistent people."""
    world = build_tiny_world(seed=seed)
    world.add(Place("home-a", "Household A", 1))
    world.add(Place("home-b", "Household B", 1))
    world.add(Place("home-c", "Household C", 1))
    world.add(Place("vessel", "Small vessel", 1))
    for route in (
        Route("home-a-tavern", "home-a", "tavern", 0.2, 1),
        Route("home-b-shop", "home-b", "shop", 0.2, 1),
        Route("home-c-workshop", "home-c", "workshop", 0.2, 1),
    ):
        world.add(route)
    for good_id, name, price in (("grain", "Grain", 4.0), ("flour", "Flour", 8.0), ("bread", "Bread", 12.0), ("vessel", "Small vessel", 500.0)):
        world.add(GoodType(good_id, name, price))
    world.create_lot("grain", 100, holder_id="warehouse-business", owner_id="warehouse-business", provenance=("harvest",))
    world.create_lot("vessel", 1, holder_id="dock", owner_id="warehouse-business", provenance=("shipwright",))
    households = (
        Household("household-a", "A family", "home-a", cash=500),
        Household("household-b", "B family", "home-b", cash=500),
        Household("household-c", "C family", "home-c", cash=500),
    )
    for household in households:
        world.add(household)
    for index in range(12):
        household_id = households[index // 4].id
        residence = households[index // 4].residence_id
        workplace = ("shop", "workshop", "tavern")[index % 3]
        actor = Actor(
            f"citizen-{index}",
            f"Citizen {index}",
            residence,
            age=18 + index,
            household_id=household_id,
            occupation=("shopkeeper", "cooper", "server")[index % 3],
            money=100.0,
            schedule=[
                ScheduleEntry(0, 7, "sleep", residence),
                ScheduleEntry(8, 16, "work", workplace, priority=10, interruptible=False),
                ScheduleEntry(18, 22, "visit tavern", "tavern"),
            ],
        )
        world.add(actor)
        households[index // 4].members.append(actor.id)
    return world
