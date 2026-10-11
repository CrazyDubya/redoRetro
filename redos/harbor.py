"""Compact Living Harbor fixture and machine-readable acceptance audit."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from .audit import causal_chain, conservation_errors, inventory_totals, market_balance_errors, money_conservation_errors, money_totals, validate_world
from .bank import deposit, open_account, originate_loan
from .insurance import approve_claim, file_claim, issue_policy, record_loss
from .model import Actor, Business, GoodType, Household, JobOpening, Place, Property, Route, ScheduleEntry, TransportAsset, TransportFacility, TransportService, World
from .realestate import add_property, lease_property
from .transport import add_asset, add_facility, add_service
from .vertical import SliceState, build_integrated_world


def build_harbor_world(*, seed: int = 0) -> SliceState:
    """Extend the living block into a small regional transport network."""
    state = build_integrated_world(seed=seed)
    world = state.world
    for place in (
        Place("brooklyn-landing", "Brooklyn Landing", 2, x=5.0, y=1.0),
        Place("staten-landing", "Staten Island Landing", 2, x=5.0, y=-2.0),
        Place("newjersey-landing", "New Jersey Landing", 2, x=1.0, y=-4.0),
        Place("newjersey-transfer", "New Jersey Transshipment Yard", 2, x=2.0, y=-3.5),
    ):
        world.add(place)
    routes = (
        Route("dock-brooklyn", "dock", "brooklyn-landing", 2.0, 1, "water", "water", ("vessel",)),
        Route("brooklyn-dock", "brooklyn-landing", "dock", 2.0, 1, "water", "water", ("vessel",)),
        Route("dock-staten", "dock", "staten-landing", 2.5, 1, "water", "water", ("vessel",)),
        Route("staten-dock", "staten-landing", "dock", 2.5, 1, "water", "water", ("vessel",)),
        # New Jersey cargo must cross a shore-side transfer yard before it can
        # board a vessel.  The historical route names are retained so weather
        # fixtures continue to refer to the land leg explicitly.
        Route("newjersey-dock", "newjersey-landing", "newjersey-transfer", 1.0, 1, "cart", "road", ("cart",)),
        Route("dock-newjersey", "newjersey-transfer", "newjersey-landing", 1.0, 1, "cart", "road", ("cart",)),
        Route("newjersey-transfer-dock", "newjersey-transfer", "dock", 2.5, 2, "water", "water", ("vessel",)),
        Route("dock-newjersey-transfer", "dock", "newjersey-transfer", 2.5, 2, "water", "water", ("vessel",)),
        Route("north-shop", "north", "shop", 2.0, 2, "cart", "road", ("cart",)),
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
        if {route.origin_id, route.destination_id} == {"shop", "north"}:
            route.mode = "cart"
            route.allowed_modes = ("cart",)

    for business in (
        Business("brooklyn-supplier", "Brooklyn Supplier", "brooklyn-landing", "supplier", cash=5_000.0),
        Business("staten-farm", "Staten Island Farm", "staten-landing", "farm", cash=5_000.0),
        Business("newjersey-transshipper", "New Jersey Transshipper", "newjersey-landing", "warehouse", cash=5_000.0),
        Business("dock-supplier", "Manhattan Dock Supplier", "dock", "supplier", cash=5_000.0),
        Business("port-authority", "Harbor Port Authority", "dock", "port", cash=25_000.0),
        Business("dock-works", "Dock Works", "dock", "service", cash=5_000.0),
        Business("staten-works", "Staten Works", "staten-landing", "service", cash=5_000.0),
        Business("jersey-works", "Jersey Works", "newjersey-transfer", "service", cash=5_000.0),
        Business("jersey-landing-works", "Jersey Landing Works", "newjersey-landing", "service", cash=5_000.0),
        Business("shop-works", "Shop Works", "shop", "service", cash=5_000.0),
    ):
        world.add(business)
    for worker_id, name, employer_id, location_id in (
        ("dock-mechanic", "Dock Mechanic", "dock-works", "dock"),
        ("staten-mechanic", "Staten Mechanic", "staten-works", "staten-landing"),
        ("jersey-mechanic", "Jersey Mechanic", "jersey-works", "newjersey-transfer"),
        ("jersey-landing-mechanic", "Jersey Landing Mechanic", "jersey-landing-works", "newjersey-landing"),
        ("shop-mechanic", "Shop Mechanic", "shop-works", "shop"),
    ):
        world.add(
            Actor(
                worker_id,
                name,
                location_id,
                occupation="transport mechanic",
                employer_id=employer_id,
                money=100.0,
                schedule=[ScheduleEntry(0, 7, "sleep", location_id), ScheduleEntry(8, 16, "work", location_id, priority=10, interruptible=False)],
            )
        )
        world.businesses[employer_id].employees.append(worker_id)
        world.add(JobOpening(f"opening-{worker_id}", employer_id, "transport mechanic", 8.0, 8, 16))
    # One ordinary regional commuter makes the passenger-to-labor link part of
    # the harbor fixture itself.  The worker starts at Brooklyn Landing and
    # reaches a dock-side job only by boarding the declared ferry service.
    world.add(Business("brooklyn-dock-employer", "Brooklyn Dock Employer", "dock", "dock employer", cash=10_000.0))
    world.add(JobOpening("opening-brooklyn-commuter", "brooklyn-dock-employer", "dock worker", 24.0, 8, 16))
    world.add(Household("brooklyn-commuter-household", "Brooklyn commuter household", "brooklyn-landing", cash=0.0, daily_expenses=2.0))
    commuter = Actor(
        "brooklyn-commuter",
        "Brooklyn Commuter",
        "brooklyn-landing",
        age=29,
        household_id="brooklyn-commuter-household",
        occupation="dock worker",
        employer_id="brooklyn-dock-employer",
        money=0.0,
        schedule=[
            ScheduleEntry(0, 7, "sleep", "brooklyn-landing"),
            ScheduleEntry(8, 16, "work", "dock", priority=10, interruptible=False),
            ScheduleEntry(16, 24, "return home", "brooklyn-landing"),
        ],
    )
    world.add(commuter)
    world.households["brooklyn-commuter-household"].members.append(commuter.id)
    world.businesses["brooklyn-dock-employer"].employees.append(commuter.id)
    world.create_lot("bread", 12.0, holder_id="brooklyn-commuter-household", owner_id="brooklyn-commuter-household", provenance=("commuter household provisions",))
    for good_id, name, price in (
        ("fuel", "Barrelled fuel", 2.0),
        ("stores", "Vessel and cart stores", 1.0),
        ("maintenance-parts", "Maintenance parts", 5.0),
    ):
        if good_id not in world.goods:
            world.add(GoodType(good_id, name, price))
    world.create_lot("grain", 40.0, holder_id="staten-farm", owner_id="staten-farm", provenance=("staten harvest",))
    world.create_lot("grain", 20.0, holder_id="newjersey-transshipper", owner_id="newjersey-transshipper", provenance=("new jersey overland supply",))
    for station_id in ("dock-works", "staten-works", "jersey-works", "jersey-landing-works", "shop-works"):
        world.create_lot("fuel", 400.0, holder_id=station_id, owner_id=station_id, provenance=(f"{station_id} fuel purchase",))
        world.create_lot("stores", 80.0, holder_id=station_id, owner_id=station_id, provenance=(f"{station_id} stores purchase",))
        world.create_lot("maintenance-parts", 40.0, holder_id=station_id, owner_id=station_id, provenance=(f"{station_id} parts purchase",))

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
        ("newjersey-sloop", "New Jersey Sloop", "vessel", "newjersey-transfer", "newjersey-transshipper", 20, 1.0),
        ("dock-cart", "Dock Cart", "cart", "dock", "dock-supplier", 10, 0.5),
        ("merchant-cart", "Merchant Prince Cart", "cart", "shop", "shop-market-cashier", 5, 0.25),
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
                wear_per_hour=0.0003,
                fuel=24,
                fuel_capacity=24,
                fuel_burn_per_hour=0.1 if asset_type == "vessel" else 0.02,
                supplies={"stores": 20.0},
                supply_capacity={"stores": 20.0},
                supply_burn_per_hour={"stores": 0.001},
                operating_cost_per_hour=cost,
                operating_cost_payee_id="port-authority",
            ),
        )
    add_asset(
        world,
        TransportAsset(
            "brooklyn-ferry",
            "Brooklyn Ferry",
            "vessel",
            "brooklyn-landing",
            "brooklyn-dock-employer",
            capacity=8,
            home_location_id="brooklyn-landing",
            fuel=48.0,
            fuel_capacity=48.0,
            fuel_burn_per_hour=0.1,
            supplies={"stores": 24.0},
            supply_capacity={"stores": 24.0},
            supply_burn_per_hour={"stores": 0.001},
            operating_cost_per_hour=0.5,
            operating_cost_payee_id="port-authority",
        ),
    )
    # The same ferry serves both physical directions.  It is not a teleport
    # link: the reverse service becomes boardable only after the vessel reaches
    # Manhattan and releases its outbound passenger movement.
    world.runtime["passenger_services"] = (
        ("brooklyn-ferry", "brooklyn-landing", "dock"),
        ("brooklyn-ferry", "dock", "brooklyn-landing"),
    )
    world.runtime["transport_services"] = (
        ("staten-sloop", "staten-landing-facility", "manhattan-dock"),
        ("manhattan-sloop", "manhattan-dock", "brooklyn-landing-facility"),
        ("dock-cart", "manhattan-dock", "manhattan-workshop"),
    )
    world.runtime["freight_plans"] = (
        {
            "origin_id": "newjersey-landing",
            "destination_id": "dock",
            "good_type_ids": ("grain",),
            "carrier_plan": ("warehouse-cart", "newjersey-sloop"),
            "relay_leg_counts": (1, 1),
            "route_ids": ("newjersey-dock", "newjersey-transfer-dock"),
            "origin_facility_id": "newjersey-landing-facility",
            "destination_facility_id": "manhattan-dock",
        },
    )
    world.runtime["asset_service_plans"] = tuple(
        {
            "asset_id": asset_id,
            "service_location_id": service_location,
            "source_holder_id": station_id,
            "good_type_id": "fuel",
            "supply": "fuel",
            "target_fraction": 0.75,
            "unit_price": 2.0,
            "payee_id": station_id,
            "supply_plans": (
                {
                    "supply": "stores",
                    "good_type_id": "stores",
                    "target_fraction": 0.75,
                    "unit_price": 1.0,
                    "payee_id": station_id,
                },
            ),
            "maintenance_source_holder_id": station_id,
            "maintenance_good_type_id": "maintenance-parts",
            "maintenance_worker_id": worker_id,
            # Service work is intentionally visible during a 30-day harbor
            # run; the threshold still leaves normal wear below full condition
            # rather than repairing every idle asset.
            "maintenance_threshold": 0.95,
            "maintenance_parts": 1.0,
            "repair_amount": 0.25,
            "maintenance_unit_price": 5.0,
            "maintenance_labor_price": 1.0,
            "maintenance_payee_id": station_id,
        }
        for asset_id, service_location, station_id, worker_id in (
            ("manhattan-sloop", "dock", "dock-works", "dock-mechanic"),
            ("staten-sloop", "staten-landing", "staten-works", "staten-mechanic"),
            ("warehouse-cart", "newjersey-landing", "jersey-landing-works", "jersey-landing-mechanic"),
            ("newjersey-sloop", "newjersey-transfer", "jersey-works", "jersey-mechanic"),
            ("dock-cart", "dock", "dock-works", "dock-mechanic"),
            ("merchant-cart", "shop", "shop-works", "shop-mechanic"),
        )
    )
    # A persistent ordered service participates in the same world clock as
    # freight.  It is also the carrier used by the autonomous price-spread
    # decision below.
    add_service(
        world,
        TransportService(
            "merchant-cart-service",
            "merchant-cart",
            ("shop", "north"),
            accepted_good_type_ids=("metals",),
            timetable_hours=(48.0,),
        ),
    )
    add_facility(world, TransportFacility("merchant-origin-facility", "shop", handling_capacity=1))
    add_facility(world, TransportFacility("merchant-destination-facility", "north", handling_capacity=1))
    # One real market lot, owned by the shop firm and held at the public
    # market place.  Quoting and booking must discover this same lot.
    world.create_lot("metals", 3.0, holder_id="shop", owner_id="shop-market-cashier", provenance=("merchant surplus",))
    world.runtime["merchant_route_plans"] = (
        {
            "service_id": "merchant-cart-service",
            "market_ids": ("shop-market", "north-market"),
            "good_type_ids": ("metals",),
            "parties": {
                "shop-market": ("shop-market-cashier", "shop-market-cashier"),
                "north-market": ("north-market-cashier", "north-market-cashier"),
            },
            "origin_facility_id": "merchant-origin-facility",
            "destination_facility_id": "merchant-destination-facility",
            "facility_by_market": {
                "shop-market": "merchant-origin-facility",
                "north-market": "merchant-destination-facility",
            },
            "due_days": 4,
        },
    )
    world.runtime["input_flows"] = (
        ("staten-farm", "dock-supplier", "grain", 5.0, 4.0),
        ("dock-supplier", "workshop-business", "grain", 3.0, 4.0),
        ("newjersey-transshipper", "dock-supplier", "grain", 3.0, 4.0),
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
    # This account is intentionally opened without a deposit.  The ordinary
    # finance clock must create and retry its monthly fee obligation rather
    # than silently discarding an unaffordable charge.
    open_account(
        world,
        "harbor-bank",
        "brooklyn-supplier",
        service_charge=7.0,
        account_id="brooklyn-fee-account",
    )
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
    loan = originate_loan(
        world,
        "harbor-bank",
        "newjersey-transshipper",
        600.0,
        annual_interest_rate=0.12,
        term_days=90,
        loan_id="harbor-working-capital",
    )
    world.runtime["loan_repayment_plans"] = [
        {"loan_id": loan.id, "amount": 210.0, "period_days": 30, "next_due_at": world.now + timedelta(days=30)},
    ]
    premises = Property(
        "brooklyn-supplier-lease",
        "Brooklyn supplier premises",
        "brooklyn-landing",
        "warehouse",
        "port-authority",
        market_value=2_000.0,
        monthly_rent=25.0,
    )
    add_property(world, premises)
    lease_property(world, premises.id, "brooklyn-supplier")
    world.runtime["_money_initial_total"] = money_totals(world)["total"]
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
    disruption_events = [event for event in world.events if event.kind in {"transport_weather", "freight_delayed", "freight_failed", "passenger_delayed", "travel_delayed"}]
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
        "physical_asset_services": {
            "supplies_purchased": sum(1 for event in world.events if event.kind == "asset_supply_purchased"),
            "maintenance_operations": sum(1 for event in world.events if event.kind == "asset_maintenance"),
            "wear_events": sum(1 for event in world.events if event.kind == "asset_wear"),
            "supply_payments": sum(
                event.data.get("amount", 0.0)
                for event in world.events
                if event.kind == "payment" and "purchased" in event.description
            ),
            "maintenance_payments": sum(
                event.data.get("amount", 0.0)
                for event in world.events
                if event.kind == "payment" and "maintenance" in event.description
            ),
        },
        "payments": sum(event.data.get("amount", 0.0) for event in world.events if event.kind == "payment"),
        "production_events": sum(1 for event in world.events if event.kind == "production"),
        "work_events": sum(1 for event in world.events if event.kind == "work"),
        "inventory": inventory_totals(world),
        "money": money_totals(world),
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
        "real_estate": {
            property.id: {
                "tenant": property.occupied_by_id,
                "last_rent_at": property.last_rent_at.isoformat() if property.last_rent_at else None,
            }
            for property in world.properties.values()
        },
        "scheduled_services": {
            service.id: {
                "asset_id": service.asset_id,
                "status": service.status,
                "current_stop": service.stop_place_ids[service.current_stop_index],
                "completed_cycles": service.completed_cycles,
                "late_hours": service.late_hours,
            }
            for service in world.transport_services.values()
        },
        "passenger_outcomes": {
            "boardings": sum(1 for event in world.events if event.kind == "passenger_boarded"),
            "arrivals": sum(1 for event in world.events if event.kind == "passenger_arrived"),
            "delays": sum(1 for event in world.events if event.kind in {"passenger_delayed", "travel_delayed"} and "brooklyn-commuter" in event.actors),
            "wage_misses": sum(1 for event in world.events if event.kind == "wage_missed"),
            "commuter": {
                "location": world.actors["brooklyn-commuter"].location_id,
                "wages": sum(
                    event.data.get("amount", 0.0)
                    for event in world.events
                    if event.kind == "payment" and "brooklyn-commuter" in event.actors and "wages" in event.description
                ),
                "work_hours": sum(world.actors["brooklyn-commuter"].work_hours_by_day.values()),
                "household_debt": world.households["brooklyn-commuter-household"].debt,
            },
        },
        "merchant_trades": [event.id for event in world.events if event.kind == "ocean_trade_booked"],
        "obligations": {
            "bank_fees": dict(world.runtime.get("_bank_fee_obligations", {})),
            "loan_repayments": dict(world.runtime.get("_loan_repayment_obligations", {})),
            "claims": dict(world.runtime.get("_claim_obligations", {})),
            "transport_costs": dict(world.runtime.get("_transport_cost_obligations", {})),
        },
        "checkpoints": list(world.runtime.get("harbor_checkpoints", ())),
        "causal_disruptions": {event.id: causal_chain(world, event.id) for event in disruption_events},
        "invariants": {
            "validation_errors": validate_world(world),
            "conservation_errors": conservation_errors(world),
            "market_balance_errors": market_balance_errors(world),
            "money_errors": money_conservation_errors(world),
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
    claim_prepared = False
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
        # The loss is the only additional authored stimulus.  Assessment,
        # approval, retry and payment remain ordinary autonomous lifecycle
        # operations after this event is registered.
        if hour == 72 and not claim_prepared:
            loss = record_loss(
                world,
                "warehouse-business",
                loss_kind="cargo damage",
                covered_risk="cargo",
                location_id="warehouse",
                verified_loss_amount=40.0,
                description="grain was damaged while stored at the warehouse",
            )
            claim = file_claim(
                world,
                "harbor-cargo-policy",
                loss_event_id=loss.id,
                loss_amount=40.0,
                claim_id="harbor-cargo-claim",
            )
            approve_claim(world, claim.id)
            claim_prepared = True
        advance_world(world, 1)
        if world.now.hour == 0:
            world.runtime.setdefault("harbor_checkpoints", []).append(
                {
                    "time": world.now.isoformat(),
                    "validation_errors": validate_world(world),
                    "conservation_errors": conservation_errors(world),
                    "market_balance_errors": market_balance_errors(world),
                    "money_errors": money_conservation_errors(world),
                    "active_shipments": sum(1 for shipment in world.shipments.values() if shipment.status not in {"delivered", "failed"}),
                    "outstanding_transport_costs": sum(asset.operating_cost_due for asset in world.transport_assets.values()),
                }
            )
    return world, harbor_audit(world)
