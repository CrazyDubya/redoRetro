"""Compact Living Harbor fixture and machine-readable acceptance audit."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .audit import causal_chain, conservation_errors, inventory_totals, market_balance_errors, validate_world
from .bank import deposit, open_account
from .insurance import issue_policy
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
        if {route.origin_id, route.destination_id} == {"dock", "workshop"}:
            route.mode = "cart"
            route.allowed_modes = ("cart",)

    for business in (
        Business("brooklyn-supplier", "Brooklyn Supplier", "brooklyn-landing", "supplier", cash=5_000.0),
        Business("staten-farm", "Staten Island Farm", "staten-landing", "farm", cash=5_000.0),
        Business("newjersey-transshipper", "New Jersey Transshipper", "newjersey-landing", "warehouse", cash=5_000.0),
        Business("dock-supplier", "Manhattan Dock Supplier", "dock", "supplier", cash=5_000.0),
        Business("port-authority", "Harbor Port Authority", "dock", "port", cash=25_000.0),
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
    asset_specs = (
        ("manhattan-sloop", "Manhattan Sloop", "vessel", "dock", "dock-supplier", 20, 1.0),
        ("staten-sloop", "Staten Sloop", "vessel", "staten-landing", "staten-farm", 20, 1.0),
        ("warehouse-cart", "Warehouse Cart", "cart", "newjersey-landing", "newjersey-transshipper", 10, 0.5),
        ("dock-cart", "Dock Cart", "cart", "dock", "dock-supplier", 10, 0.5),
    )
    for asset_id, name, asset_type, location_id, owner_id, capacity, cost in asset_specs:
        add_asset(
            world,
            TransportAsset(
                asset_id,
                name,
                asset_type,
                location_id,
                owner_id,
                capacity=capacity,
                home_location_id=location_id,
                fuel=200,
                fuel_capacity=200,
                fuel_burn_per_hour=0.1 if asset_type == "vessel" else 0.02,
                operating_cost_per_hour=cost,
                operating_cost_payee_id="port-authority",
            ),
        )
    world.runtime["transport_services"] = (
        ("staten-sloop", "staten-landing-facility", "manhattan-dock"),
        ("manhattan-sloop", "manhattan-dock", "brooklyn-landing-facility"),
        ("warehouse-cart", "newjersey-landing-facility", "manhattan-workshop"),
        ("dock-cart", "manhattan-dock", "manhattan-workshop"),
    )
    world.runtime["input_flows"] = (
        ("staten-farm", "dock-supplier", "grain", 5.0, 4.0),
        ("dock-supplier", "workshop-business", "grain", 3.0, 4.0),
        ("newjersey-transshipper", "workshop-business", "grain", 3.0, 4.0),
        ("dock-supplier", "brooklyn-supplier", "grain", 2.0, 4.0),
        ("workshop-business", "tavern-business", "flour", 1.0, 8.0),
    )
    # These are live financial participants in the harbor world.  Their
    # balances and obligations advance through the same runtime clock as the
    # transport network.
    world.add(Business("harbor-bank", "Harbor Bank", "dock", "bank", cash=100_000.0))
    world.add(Business("harbor-mutual", "Harbor Mutual", "dock", "insurer", cash=50_000.0))
    account = open_account(world, "harbor-bank", "port-authority", annual_interest_rate=0.0365, service_charge=1.0, account_id="port-authority-account")
    deposit(world, account.id, 1_000.0)
    issue_policy(
        world,
        "harbor-mutual",
        "warehouse-business",
        line="cargo",
        region_id="warehouse",
        premium=10.0,
        coverage_limit=250.0,
        policy_id="harbor-cargo-policy",
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
            facility.id: {
                "queue": list(facility.queue),
                "arrival_queue": list(facility.arrival_queue),
                "active": list(facility.active_shipments),
                "handling_hours": facility.handling_hours,
                "completed_operations": facility.completed_operations,
                "peak_queue_length": facility.peak_queue_length,
            }
            for facility in world.transport_facilities.values()
        },
        "transport_costs": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "transport_cost_accrued"),
        "transport_costs_settled": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "transport_cost_settled"),
        "transport_costs_outstanding": sum(asset.operating_cost_due for asset in world.transport_assets.values()),
        "transport_costs_unpaid_events": sum(1 for event in world.events if event.kind == "transport_cost_unpaid"),
        "payments": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "payment"),
        "production_events": sum(1 for event in world.events if event.kind == "production"),
        "work_events": sum(1 for event in world.events if event.kind == "work"),
        "inventory": inventory_totals(world),
        "money": {
            "actors": sum(actor.money for actor in world.actors.values()),
            "businesses": sum(business.cash for business in world.businesses.values()),
            "households": sum(household.cash for household in world.households.values()),
        },
        "banking": {
            "accounts": {account.id: {"balance": account.balance, "status": account.status} for account in world.bank_accounts.values()},
            "loans": {loan.id: {"principal": loan.outstanding_principal, "interest": loan.accrued_interest, "status": loan.status} for loan in world.bank_loans.values()},
            "interest_events": sum(1 for event in world.events if event.kind in {"deposit_interest_accrued", "loan_interest_accrued"}),
            "fee_events": sum(1 for event in world.events if event.kind == "bank_service_charge"),
        },
        "insurance": {
            "policies": {policy.id: policy.status for policy in world.insurance_policies.values()},
            "claims": {claim.id: claim.status for claim in world.insurance_claims.values()},
            "approved_exposure": sum(claim.indemnity for claim in world.insurance_claims.values() if claim.status == "approved"),
        },
        "checkpoints": list(world.runtime.get("harbor_checkpoints", ())),
        "causal_disruptions": {event.id: causal_chain(world, event.id) for event in disruption_events},
        "invariants": {
            "validation_errors": validate_world(world),
            "conservation_errors": conservation_errors(world),
            "market_balance_errors": market_balance_errors(world),
        },
    }


def run_harbor_demonstration(*, seed: int = 0, days: int = 90) -> tuple[World, dict[str, Any]]:
    """Run the long-form harbor acceptance demonstration.

    The only authored stimulus is a deterministic waterway disruption.  All
    contracts, carrier assignments, production, banking, claims and recovery
    thereafter proceed through the ordinary clock.  Daily checkpoints are
    retained in the returned machine-readable audit so a late corruption is
    not hidden by an end-state-only assertion.
    """
    if days <= 0:
        raise ValueError("harbor demonstration must run at least one day")
    from .audit import conservation_errors
    from .runtime import advance_world
    from .simulation import apply_transport_weather, set_route_condition

    world = build_harbor_world(seed=seed).world
    disruption_start = 20
    disruption_end = 50
    for hour in range(days * 24):
        if hour == disruption_start:
            apply_transport_weather(
                world,
                ("staten-dock", "dock-staten"),
                weather="storm",
                waterway="storm",
                accessible=False,
            )
        if hour == disruption_end:
            for route_id in ("staten-dock", "dock-staten"):
                set_route_condition(world, route_id, accessible=True, waterway="calm")
        advance_world(world, 1)
        if world.now.hour == 0:
            world.runtime.setdefault("harbor_checkpoints", []).append(
                {
                    "time": world.now.isoformat(),
                    "validation_errors": validate_world(world),
                    "conservation_errors": conservation_errors(world),
                    "market_balance_errors": market_balance_errors(world),
                    "active_shipments": sum(1 for shipment in world.shipments.values() if shipment.status not in {"delivered", "failed"}),
                    "outstanding_transport_costs": sum(asset.operating_cost_due for asset in world.transport_assets.values()),
                }
            )
    return world, harbor_audit(world)
