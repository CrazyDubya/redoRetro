"""Factories used by tests and the first vertical-slice experiments."""

from __future__ import annotations

from .market import create_star_market, install_star_goods
from .model import Actor, Business, Household, Place, Route, World


def build_tiny_world() -> World:
    world = World()
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
