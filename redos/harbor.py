"""Compact Living Harbor fixture and machine-readable acceptance audit."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .audit import causal_chain, conservation_errors, inventory_totals, market_balance_errors, validate_world
from .model import Business, Place, Route, TransportAsset, TransportFacility, World
from .transport import add_asset, add_facility
from .vertical import SliceState, build_integrated_world


def build_harbor_world(*, seed: int = 0) -> SliceState:
    """Extend the living block into a small regional transport network."""
    state = build_integrated_world(seed=seed)
    world = state.world
    for place in (
        Place("brooklyn-landing", "Brooklyn Landing", 2, x=5.0, y=1.0),
        Place("staten-landing", "Staten Island Landing", 2, x=5.0, y=-2.0),
        Place("newjersey-landing", "New Jersey Landing", 2, x=1.0, y=-4.0),
    ):
        world.add(place)
    routes = (
        Route("dock-brooklyn", "dock", "brooklyn-landing", 2.0, 1, "water", "water", ("vessel",)),
        Route("brooklyn-dock", "brooklyn-landing", "dock", 2.0, 1, "water", "water", ("vessel",)),
        Route("dock-staten", "dock", "staten-landing", 2.5, 1, "water", "water", ("vessel",)),
        Route("staten-dock", "staten-landing", "dock", 2.5, 1, "water", "water", ("vessel",)),
        Route("staten-warehouse", "staten-landing", "warehouse", 3.0, 1, "water", "water", ("vessel",)),
        Route("warehouse-staten", "warehouse", "staten-landing", 3.0, 1, "water", "water", ("vessel",)),
        Route("staten-workshop", "staten-landing", "workshop", 3.0, 1, "water", "water", ("vessel",)),
        Route("workshop-staten", "workshop", "staten-landing", 3.0, 1, "water", "water", ("vessel",)),
        Route("newjersey-dock", "newjersey-landing", "dock", 2.0, 1, "cart", "road", ("cart",)),
        Route("dock-newjersey", "dock", "newjersey-landing", 2.0, 1, "cart", "road", ("cart",)),
    )
    for route in routes:
        world.add(route)
    # The existing block connection becomes the ordinary cart service between
    # the warehouse and workshop; no special freight route is needed.
    for route in world.routes.values():
        if route.origin_id == "warehouse" and route.destination_id == "workshop":
            route.mode = "cart"
            route.allowed_modes = ("cart",)
        if route.origin_id == "workshop" and route.destination_id == "warehouse":
            route.mode = "cart"
            route.allowed_modes = ("cart",)

    for business in (
        Business("brooklyn-supplier", "Brooklyn Supplier", "brooklyn-landing", "supplier", cash=5_000.0),
        Business("staten-farm", "Staten Island Farm", "staten-landing", "farm", cash=5_000.0),
        Business("newjersey-transshipper", "New Jersey Transshipper", "newjersey-landing", "warehouse", cash=5_000.0),
    ):
        world.add(business)
    world.create_lot("grain", 40.0, holder_id="staten-farm", owner_id="staten-farm", provenance=("staten harvest",))
    world.create_lot("grain", 20.0, holder_id="newjersey-transshipper", owner_id="newjersey-transshipper", provenance=("new jersey overland supply",))

    for facility in (
        TransportFacility("manhattan-dock", "dock", handling_capacity=1, storage_access_id="warehouse-business"),
        TransportFacility("brooklyn-landing-facility", "brooklyn-landing", handling_capacity=1),
        TransportFacility("staten-landing-facility", "staten-landing", handling_capacity=1),
        TransportFacility("newjersey-landing-facility", "newjersey-landing", handling_capacity=1),
        TransportFacility("manhattan-warehouse", "warehouse", handling_capacity=1, storage_access_id="warehouse-business"),
        TransportFacility("manhattan-workshop", "workshop", handling_capacity=1, storage_access_id="workshop-business"),
    ):
        add_facility(world, facility)
    add_asset(world, TransportAsset("manhattan-sloop", "Manhattan Sloop", "vessel", "dock", "warehouse-business", capacity=20, fuel=200, fuel_capacity=200, fuel_burn_per_hour=0.1, operating_cost_per_hour=1.0))
    add_asset(world, TransportAsset("staten-sloop", "Staten Sloop", "vessel", "staten-landing", "staten-farm", capacity=20, fuel=200, fuel_capacity=200, fuel_burn_per_hour=0.1, operating_cost_per_hour=1.0))
    add_asset(world, TransportAsset("warehouse-cart", "Warehouse Cart", "cart", "warehouse", "warehouse-business", capacity=10, fuel=200, fuel_capacity=200, fuel_burn_per_hour=0.02, operating_cost_per_hour=0.5))
    world.runtime["transport_services"] = (
        ("staten-sloop", "staten-landing-facility", "manhattan-workshop"),
        ("warehouse-cart", "manhattan-warehouse", "manhattan-workshop"),
    )
    world.runtime["input_flows"] = (
        ("staten-farm", "workshop-business", "grain", 5.0, 4.0),
        ("workshop-business", "tavern-business", "flour", 1.0, 8.0),
    )
    return state


def harbor_audit(world: World) -> dict[str, Any]:
    """Return JSON-compatible evidence for the 30-day harbor demonstration."""
    journeys = {
        "completed": [shipment.id for shipment in world.shipments.values() if shipment.status == "delivered"],
        "delayed": [shipment.id for shipment in world.shipments.values() if any(event.kind == "freight_delayed" and shipment.id in event.entities for event in world.events)],
        "failed": [shipment.id for shipment in world.shipments.values() if shipment.status == "failed"],
    }
    moved: dict[str, float] = defaultdict(float)
    for shipment in world.shipments.values():
        contract = world.contracts[shipment.contract_id]
        if shipment.status == "delivered":
            moved[contract.good_type_id] += contract.quantity
    utilization = {
        asset.id: {
            "assignments": sum(1 for event in world.events if event.kind == "asset_assigned" and asset.id in event.entities),
            "operating_cost_due": asset.operating_cost_due,
            "location": asset.location_id,
        }
        for asset in world.transport_assets.values()
    }
    disruption_events = [event for event in world.events if event.kind in {"transport_weather", "freight_delayed", "freight_failed", "passenger_delayed"}]
    return {
        "time": world.now.isoformat(),
        "journeys": journeys,
        "goods_moved": dict(moved),
        "asset_utilization": utilization,
        "facility_utilization": {
            facility.id: {"queue": list(facility.queue), "arrival_queue": list(facility.arrival_queue), "active": list(facility.active_shipments)}
            for facility in world.transport_facilities.values()
        },
        "transport_costs": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "transport_cost_accrued"),
        "payments": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "payment"),
        "production_events": sum(1 for event in world.events if event.kind == "production"),
        "work_events": sum(1 for event in world.events if event.kind == "work"),
        "inventory": inventory_totals(world),
        "money": {
            "actors": sum(actor.money for actor in world.actors.values()),
            "businesses": sum(business.cash for business in world.businesses.values()),
            "households": sum(household.cash for household in world.households.values()),
        },
        "causal_disruptions": {event.id: causal_chain(world, event.id) for event in disruption_events},
        "invariants": {
            "validation_errors": validate_world(world),
            "conservation_errors": conservation_errors(world),
            "market_balance_errors": market_balance_errors(world),
        },
    }
