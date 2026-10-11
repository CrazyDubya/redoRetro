"""Persistent freight carriers and facility handling for the harbor slice.

This is the first Ports of Call kernel: a charter is assigned to a persistent
carrier, cargo is loaded at a facility, the carrier travels on canonical
routes, and unloading/settlement occur only after physical arrival.
"""

from __future__ import annotations

import copy

from .enterprise import allocate_contract
from .model import Movement, Shipment, TransportAsset, TransportFacility, TransportService, World, require_finite
from .simulation import best_route, effective_route_hours, route_is_accessible, route_path


PACE_MULTIPLIERS = {
    "slow": 1.25,
    "steady": 1.0,
    "urgent": 0.85,
}


def settle_operating_cost(world: World, asset_id: str, *, causes: tuple[str, ...] = ()) -> bool:
    """Settle a carrier's outstanding operating-cost obligation.

    Accrued cost is a real payable, not a bookkeeping counter that vanishes at
    the end of a movement step.  If the owner cannot pay, the amount remains
    due and the asset records an auditable unpaid obligation for a later
    retry.  Assets without a configured payee retain the payable explicitly;
    this is useful for standalone transport tests and avoids minting or
    destroying money.
    """
    asset = world.transport_assets[asset_id]
    require_finite(asset.operating_cost_due, f"{asset.id} operating cost due")
    if asset.operating_cost_due <= 1e-9:
        asset.operating_cost_due = 0.0
        asset.accrued_operating_cost = 0.0
        world.runtime.setdefault("_transport_cost_obligations", {}).pop(asset.id, None)
        return True
    obligations = world.runtime.setdefault("_transport_cost_obligations", {})
    obligation = obligations.setdefault(
        asset.id,
        {"status": "open", "amount": asset.operating_cost_due, "attempts": 0, "last_signature": None},
    )
    obligation["amount"] = asset.operating_cost_due
    obligation["attempts"] = int(obligation.get("attempts", 0)) + 1

    def record_transition(kind: str, description: str, *, reason: str, extra: dict | None = None) -> None:
        signature = (kind, round(asset.operating_cost_due, 9), reason)
        if obligation.get("last_signature") == signature:
            return
        world.record(
            kind,
            description,
            actors=[asset.owner_id] + ([asset.operating_cost_payee_id] if asset.operating_cost_payee_id else []),
            entities=[asset.id] + ([asset.operating_cost_payee_id] if asset.operating_cost_payee_id else []),
            causes=causes,
            data={"amount": asset.operating_cost_due, "reason": reason, **(extra or {})},
        )
        obligation["last_signature"] = signature

    if asset.operating_cost_payee_id is None:
        obligation["status"] = "open"
        record_transition("transport_cost_payable", f"{asset.id} has an operating cost payable", reason="no payee configured")
        asset.accrued_operating_cost = 0.0
        return False
    try:
        payment = world.pay(
            asset.owner_id,
            asset.operating_cost_payee_id,
            asset.operating_cost_due,
            causes=causes,
            reason=f"{asset.id} operating cost",
        )
    except (KeyError, ValueError) as exc:
        obligation["status"] = "open"
        record_transition(
            "transport_cost_unpaid",
            f"{asset.id} could not settle its operating cost",
            reason=str(exc),
        )
        asset.accrued_operating_cost = 0.0
        return False
    amount = asset.operating_cost_due
    asset.operating_cost_due = 0.0
    asset.accrued_operating_cost = 0.0
    obligation["status"] = "settled"
    obligation["last_signature"] = ("transport_cost_settled", round(amount, 9), "settled")
    world.record(
        "transport_cost_settled",
        f"{asset.id} operating cost settled",
        actors=[asset.owner_id, asset.operating_cost_payee_id],
        entities=[asset.id],
        causes=(*causes, payment.id),
        data={"amount": amount},
    )
    return True


def advance_failed_cargo_recovery(world: World) -> None:
    """Start physical recovery for failed cargo during ordinary world time."""
    for shipment in tuple(world.shipments.values()):
        if shipment.status != "failed" or shipment.carrier_id is None:
            continue
        asset = world.transport_assets.get(shipment.carrier_id)
        contract = world.contracts.get(shipment.contract_id)
        if asset is None or contract is None or asset.assignment_kind == "cargo_recovery":
            continue
        if world.quantity_held(asset.id, contract.good_type_id) + 1e-9 < contract.quantity:
            continue
        try:
            resolve_failed_cargo(world, shipment.id)
        except (KeyError, ValueError):
            # The custody remains in place and the next world hour retries.
            continue


def add_asset(world: World, asset: TransportAsset) -> TransportAsset:
    for value, label in (
        (asset.capacity, "transport capacity"),
        (asset.wear_per_hour, "transport wear"),
        (asset.condition, "transport condition"),
        (asset.readiness, "transport readiness"),
        (asset.fuel, "transport fuel"),
        (asset.fuel_capacity, "transport fuel capacity"),
        (asset.fuel_burn_per_hour, "transport fuel burn"),
        (asset.operating_cost_per_hour, "transport operating cost"),
    ):
        require_finite(value, label)
    for supply, quantity in asset.supplies.items():
        require_finite(quantity, f"transport supply {supply}")
    for supply, quantity in asset.supply_capacity.items():
        require_finite(quantity, f"transport supply capacity {supply}")
    for supply, quantity in asset.supply_burn_per_hour.items():
        require_finite(quantity, f"transport supply burn {supply}")
    if asset.capacity <= 0:
        raise ValueError("transport capacity must be positive")
    if asset.wear_per_hour < 0:
        raise ValueError("transport wear cannot be negative")
    if not 0 <= asset.condition <= 1:
        raise ValueError("transport condition must be between zero and one")
    if not 0 <= asset.readiness <= 1:
        raise ValueError("transport readiness must be between zero and one")
    if asset.minimum_crew < 0:
        raise ValueError("transport minimum crew cannot be negative")
    if len(set(asset.crew_ids)) != len(asset.crew_ids):
        raise ValueError("transport crew cannot contain duplicates")
    if any(crew_id not in world.actors for crew_id in asset.crew_ids):
        raise KeyError("transport crew member is not an actor")
    for crew_id in asset.crew_ids:
        if any(crew_id in other.crew_ids for other in world.transport_assets.values() if other.id != asset.id):
            raise ValueError(f"actor {crew_id} is already assigned to another asset")
    for supply, quantity in asset.supplies.items():
        if quantity < 0 or quantity > asset.supply_capacity.get(supply, quantity) + 1e-9:
            raise ValueError(f"invalid starting supply for {supply}")
    world.add(asset)
    return asset


def _record_asset_wear(world: World, asset_id: str, hours: float, *, causes: tuple[str, ...] = ()) -> None:
    """Apply physical wear to a carrier after time spent operating it."""
    require_finite(hours, "asset operating hours")
    if hours <= 0:
        return
    asset = world.transport_assets[asset_id]
    if asset.wear_per_hour <= 0:
        return
    before = asset.condition
    asset.condition = max(0.0, asset.condition - asset.wear_per_hour * hours)
    if asset.condition <= 0:
        asset.available = False
        asset.unavailable_reason = "condition exhausted"
    if asset.condition != before:
        world.record(
            "asset_wear",
            f"{asset.id} lost condition through operation",
            entities=[asset.id],
            causes=causes,
            data={"hours": hours, "before": before, "after": asset.condition},
        )


def assign_crew(world: World, asset_id: str, crew_ids: tuple[str, ...]) -> TransportAsset:
    """Assign existing people to a vessel or cart without creating workers."""
    asset = world.transport_assets[asset_id]
    if asset.assigned_shipment_id is not None:
        raise ValueError("cannot change crew while the asset is assigned")
    if len(set(crew_ids)) != len(crew_ids):
        raise ValueError("transport crew cannot contain duplicates")
    if len(crew_ids) < asset.minimum_crew:
        raise ValueError(f"asset {asset_id} requires at least {asset.minimum_crew} crew")
    for crew_id in crew_ids:
        if crew_id not in world.actors:
            raise KeyError(crew_id)
        if any(crew_id in other.crew_ids for other in world.transport_assets.values() if other.id != asset_id):
            raise ValueError(f"actor {crew_id} is already assigned to another asset")
    asset.crew_ids = tuple(crew_ids)
    world.record("asset_crew_assigned", f"{asset.id} received its crew", actors=crew_ids, entities=[asset.id])
    return asset


def add_facility(world: World, facility: TransportFacility) -> TransportFacility:
    require_finite(facility.handling_capacity, "facility handling capacity")
    if facility.storage_capacity is not None:
        require_finite(facility.storage_capacity, "facility storage capacity")
    if facility.handling_capacity <= 0:
        raise ValueError("facility handling capacity must be positive")
    if facility.place_id not in world.places:
        raise KeyError(facility.place_id)
    if facility.storage_access_id is not None and not world._holder_exists(facility.storage_access_id):
        raise KeyError(facility.storage_access_id)
    if facility.storage_capacity is not None and facility.storage_capacity < 0:
        raise ValueError("facility storage capacity cannot be negative")
    world.add(facility)
    return facility


def add_service(world: World, service: TransportService) -> TransportService:
    """Register an ordered vehicle service against an existing asset."""
    if service.asset_id not in world.transport_assets:
        raise KeyError(service.asset_id)
    if len(service.stop_place_ids) < 2:
        raise ValueError("a transport service requires at least two stops")
    if any(place_id not in world.places for place_id in service.stop_place_ids):
        raise KeyError("service stop is not a world place")
    require_finite(service.dwell_hours, "service dwell hours")
    for hours in service.timetable_hours:
        require_finite(hours, "service timetable hours")
    if service.dwell_hours < 0 or any(hours <= 0 for hours in service.timetable_hours):
        raise ValueError("service timing must be non-negative and timetable hours positive")
    if service.timetable_hours and len(service.timetable_hours) not in {len(service.stop_place_ids) - 1, len(service.stop_place_ids)}:
        raise ValueError("timetable must describe each service leg")
    if any(existing.asset_id == service.asset_id for existing in world.transport_services.values()):
        raise ValueError(f"asset {service.asset_id} already has a transport service")
    asset = world.transport_assets[service.asset_id]
    if asset.assigned_shipment_id is not None:
        raise ValueError("service asset is already assigned")
    world.add(service)
    world.record(
        "transport_service_registered",
        f"{service.id} registered orders for {asset.id}",
        entities=[service.id, asset.id, *service.stop_place_ids],
        data={"stops": service.stop_place_ids, "timetable_hours": service.timetable_hours},
    )
    return service


def service_accepts(service: TransportService, good_type_id: str) -> bool:
    """Return whether the service has declared an order for this cargo."""
    return not service.accepted_good_type_ids or good_type_id in service.accepted_good_type_ids


def _service_next_stop(service: TransportService) -> str:
    return service.stop_place_ids[(service.current_stop_index + 1) % len(service.stop_place_ids)]


def _asset_is_stationary(world: World, asset_id: str, *, at_place_id: str | None = None) -> bool:
    """Return whether an asset is physically stopped and serviceable.

    ``location_id`` is the last reached waypoint, not a continuous position.
    A vehicle may therefore report the station it left while it is already in
    motion.  Every physical service path uses this predicate so freight,
    passengers, repositioning, recovery, and ordered services share one
    location rule.
    """
    asset = world.transport_assets[asset_id]
    if asset.assigned_shipment_id is not None:
        return False
    if asset.assignment_kind in {"freight", "passenger", "reposition", "cargo_recovery"}:
        return False
    if asset.return_route_ids and asset.return_route_index < len(asset.return_route_ids):
        return False
    if any(movement.transport_asset_id == asset_id for movement in world.movements.values()):
        return False
    if any(
        service.asset_id == asset_id and service.status == "in_transit"
        for service in world.transport_services.values()
    ):
        return False
    return at_place_id is None or asset.location_id == at_place_id


def _begin_service_leg(world: World, service: TransportService) -> bool:
    asset = world.transport_assets[service.asset_id]
    if asset.assigned_shipment_id is not None or not asset.available:
        service.status = "waiting_asset"
        return False
    current_stop = service.stop_place_ids[service.current_stop_index]
    if asset.location_id != current_stop:
        service.status = "waiting_asset"
        world.record(
            "transport_service_misaligned",
            f"{service.id} is not at its ordered stop",
            entities=[service.id, asset.id, current_stop, asset.location_id],
        )
        return False
    next_stop = _service_next_stop(service)
    path = route_path(world, current_stop, next_stop, mode=asset.asset_type)
    if not path:
        service.status = "blocked"
        world.record(
            "transport_service_blocked",
            f"{service.id} has no accessible route to {next_stop}",
            entities=[service.id, asset.id, current_stop, next_stop],
        )
        return False
    service.route_ids = tuple(route.id for route in path)
    service.route_index = 0
    service.elapsed_hours = 0.0
    service.journey_elapsed_hours = 0.0
    service.status = "in_transit"
    world.record(
        "transport_service_departed",
        f"{service.id} departed {current_stop} for {next_stop}",
        entities=[service.id, asset.id, *service.route_ids],
        data={"from": current_stop, "to": next_stop},
    )
    return True


def _advance_service(world: World, service: TransportService, hours: float) -> None:
    remaining = hours
    while remaining > 1e-9:
        asset = world.transport_assets[service.asset_id]
        if service.status == "waiting_asset":
            if asset.assigned_shipment_id is not None or not asset.available:
                return
            service.status = "ready"
        if service.status == "blocked":
            # A blocked multi-route leg may have already crossed one or more
            # intermediate waypoints.  Resume the preserved physical route
            # instead of restarting from the service's last named stop.
            if service.route_ids and service.route_index < len(service.route_ids):
                service.status = "in_transit"
                continue
            if _begin_service_leg(world, service):
                continue
            return
        if service.status == "ready":
            if not _begin_service_leg(world, service):
                return
        if service.status == "dwelling":
            step = min(remaining, service.dwell_remaining_hours)
            service.dwell_remaining_hours -= step
            remaining -= step
            if service.dwell_remaining_hours > 1e-9:
                return
            service.status = "ready"
            continue
        if service.status != "in_transit":
            return
        if asset.assigned_shipment_id is not None or not asset.available:
            service.status = "waiting_asset"
            return
        if service.route_index >= len(service.route_ids):
            service.status = "dwelling"
            service.dwell_remaining_hours = service.dwell_hours
            continue
        route = world.routes[service.route_ids[service.route_index]]
        if not route_is_accessible(world, route, mode=asset.asset_type):
            service.journey_elapsed_hours += remaining
            service.status = "blocked"
            world.record("transport_service_delayed", f"{service.id} waits on {route.id}", entities=[service.id, asset.id, route.id])
            return
        duration = effective_route_hours(world, route, mode=asset.asset_type)
        available = max(0.0, duration - service.elapsed_hours)
        if available <= 1e-9:
            service.route_index += 1
            service.elapsed_hours = 0.0
            asset.location_id = route.destination_id
            continue
        step = min(remaining, available)
        requirements = _asset_resource_requirements(asset, step)
        if not _consume_asset_bundle(world, asset.id, requirements):
            service.status = "waiting_asset"
            world.record("transport_service_unavailable", f"{service.id} stopped because {asset.id} lacks fuel", entities=[service.id, asset.id])
            return
        cost = asset.operating_cost_per_hour * step
        asset.accrued_operating_cost += cost
        asset.operating_cost_due += cost
        if cost > 0:
            world.record(
                "transport_cost_accrued",
                f"{asset.id} accrued scheduled-service cost",
                actors=[asset.owner_id],
                entities=[asset.id, service.id],
                data={"amount": cost, "outstanding": asset.operating_cost_due},
            )
        _record_asset_wear(world, asset.id, step)
        service.elapsed_hours += step
        service.journey_elapsed_hours += step
        remaining -= step
        if service.elapsed_hours + 1e-9 < duration:
            return
        asset.location_id = route.destination_id
        service.route_index += 1
        service.elapsed_hours = 0.0
        if service.route_index < len(service.route_ids):
            continue
        old_index = service.current_stop_index
        service.current_stop_index = (service.current_stop_index + 1) % len(service.stop_place_ids)
        if service.current_stop_index == 0:
            service.completed_cycles += 1
        service.dwell_remaining_hours = service.dwell_hours
        service.status = "dwelling"
        planned = service.timetable_hours[old_index % len(service.timetable_hours)] if service.timetable_hours else service.journey_elapsed_hours
        actual_hours = service.journey_elapsed_hours
        service.late_hours += max(0.0, actual_hours - planned)
        world.record(
            "transport_service_arrived",
            f"{service.id} arrived at {asset.location_id}",
            entities=[service.id, asset.id, asset.location_id],
            data={"planned_hours": planned, "actual_hours": actual_hours, "late_hours": max(0.0, actual_hours - planned)},
        )


def advance_services(world: World, hours: float = 1.0, *, excluded_asset_ids: set[str] | None = None) -> None:
    """Advance ordered services without changing the global clock."""
    require_finite(hours, "service time")
    if hours < 0:
        raise ValueError("service time cannot move backwards")
    excluded_asset_ids = excluded_asset_ids or set()
    remaining = float(hours)
    while remaining > 1e-9:
        step = min(1.0, remaining)
        for service in world.transport_services.values():
            if service.asset_id in excluded_asset_ids:
                continue
            _advance_service(world, service, step)
        remaining -= step


def board_passenger(world: World, actor_id: str, asset_id: str, destination_id: str) -> Movement:
    """Start one physical passenger movement aboard a persistent asset."""
    actor = world.actors[actor_id]
    asset = world.transport_assets[asset_id]
    if actor.traveling_to is not None:
        raise ValueError(f"{actor_id} is already travelling")
    if asset.location_id != actor.location_id:
        raise ValueError("passenger and carrier are not co-located")
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {asset_id} is unavailable")
    path = route_path(world, actor.location_id, destination_id, mode=asset.asset_type)
    if not path:
        raise ValueError("passenger has no accessible carrier route")
    if len(path) != 1:
        raise ValueError("passenger service requires one physical carrier leg")
    route = path[0]
    world._event_number += 1
    movement = Movement(
        id=f"movement-{world._event_number}",
        actor_id=actor.id,
        route_id=route.id,
        origin_id=route.origin_id,
        destination_id=route.destination_id,
        elapsed_hours=0.0,
        duration_hours=effective_route_hours(world, route, mode=asset.asset_type),
        transport_asset_id=asset.id,
        movement_mode=asset.asset_type,
    )
    world.add(movement)
    assign_asset(world, asset.id, movement.id, kind="passenger")
    actor.traveling_to = destination_id
    actor.position = (world.places[route.origin_id].x, world.places[route.origin_id].y)
    world.record(
        "passenger_boarded",
        f"{actor.id} boarded {asset.id}",
        actors=[actor.id],
        entities=[movement.id, asset.id, route.id],
        data={"destination": destination_id},
    )
    return movement


def _asset_load(world: World, asset_id: str) -> float:
    return sum(lot.quantity for lot in world.lots_held_by(asset_id))


def assign_asset(world: World, asset_id: str, assignment_id: str, *, kind: str) -> TransportAsset:
    """Reserve one persistent asset for exactly one current obligation."""
    asset = world.transport_assets[asset_id]
    _validate_asset_prerequisites(world, asset, assignment_id=assignment_id)
    asset.assigned_shipment_id = assignment_id
    asset.assignment_kind = kind
    asset.available = False
    asset.unavailable_reason = None
    world.record("asset_assigned", f"{asset.id} assigned to {assignment_id}", entities=[asset.id, assignment_id], data={"kind": kind})
    return asset


def _validate_asset_prerequisites(
    world: World,
    asset: TransportAsset,
    *,
    assignment_id: str | None = None,
    service_id: str | None = None,
) -> None:
    """Pure preflight used before a contract or relay can mutate the world."""
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {asset.id} is unavailable")
    if asset.reserved_for_shipment_id not in {None, assignment_id}:
        raise ValueError(f"carrier {asset.id} is reserved for another shipment")
    if asset.cargo_clearance_pending or _asset_load(world, asset.id) > 1e-9:
        raise ValueError(f"carrier {asset.id} still holds unresolved cargo")
    if asset.condition <= 0 or asset.readiness <= 0:
        raise ValueError(f"carrier {asset.id} is not operational")
    for service in world.transport_services.values():
        if service.asset_id == asset.id and service.id != service_id and service.status not in {"ready", "waiting_asset"}:
            raise ValueError(f"carrier {asset.id} is committed to service {service.id}")
    if len(asset.crew_ids) < asset.minimum_crew:
        raise ValueError(f"carrier {asset.id} lacks its required crew")
    horse = world.horses.get(asset.id)
    if asset.asset_type == "horse" and horse is not None and horse.injury > 0:
        raise ValueError(f"horse {asset.id} is injured")


def release_asset(
    world: World,
    asset_id: str,
    *,
    available: bool = True,
    reason: str | None = None,
    start_reposition: bool = True,
) -> TransportAsset:
    asset = world.transport_assets[asset_id]
    previous_kind = asset.assignment_kind
    asset.assigned_shipment_id = None
    asset.assignment_kind = None
    asset.cargo_clearance_pending = _asset_load(world, asset.id) > 1e-9
    asset.available = available and asset.condition > 0 and asset.readiness > 0
    asset.unavailable_reason = None if asset.available else reason
    # Cargo custody is deliberately separate from mechanical readiness.  A
    # carrier may be refuelled while still blocked from a new assignment until
    # its failed cargo is physically recovered.
    managed_by_service = any(service.asset_id == asset.id for service in world.transport_services.values())
    if previous_kind == "freight" and start_reposition and asset.available and not asset.cargo_clearance_pending and not managed_by_service:
        _begin_reposition(world, asset)
    return asset


def replenish_asset(
    world: World,
    asset_id: str,
    supply: str,
    quantity: float,
    *,
    source_id: str | None = None,
    source_kind: str = "administrative",
) -> float:
    """Add fuel or a named operational supply to a persistent asset.

    This remains the low-level provisioning primitive used by focused tests and
    initial provisioning.  Running worlds should use
    :func:`supply_asset_from_inventory`, which makes the same operation consume
    a co-located physical good and settle its supplier.
    """
    require_finite(quantity, "replenishment quantity")
    if quantity <= 0:
        raise ValueError("replenishment quantity must be positive")
    asset = world.transport_assets[asset_id]
    if supply == "fuel":
        before = asset.fuel
        asset.fuel = min(asset.fuel_capacity, asset.fuel + quantity) if asset.fuel_capacity > 0 else asset.fuel + quantity
        added = asset.fuel - before
    else:
        before = asset.supplies.get(supply, 0.0)
        capacity = asset.supply_capacity.get(supply, float("inf"))
        asset.supplies[supply] = min(capacity, before + quantity)
        added = asset.supplies[supply] - before
    if added > 0 and asset.condition > 0 and asset.readiness > 0 and (
        asset.assigned_shipment_id is None or asset.assignment_kind == "passenger"
    ):
        asset.available = True
        asset.unavailable_reason = None
    world.record(
        "asset_replenished",
        f"{asset.id} received {added} {supply}",
        entities=[asset.id, *([source_id] if source_id else [])],
        data={"supply": supply, "quantity": added, "source_kind": source_kind},
    )
    return added


def supply_asset_from_inventory(
    world: World,
    asset_id: str,
    supply: str,
    quantity: float,
    *,
    source_holder_id: str,
    good_type_id: str,
    unit_price: float = 0.0,
    payee_id: str | None = None,
    causes: tuple[str, ...] = (),
) -> float:
    """Purchase and consume a physical operating supply at the asset's place.

    Fuel and stores are represented as ordinary canonical goods while held by
    the service station.  The goods are transferred to the asset, consumed
    into its operating state, and paid for by the asset owner.  This preserves
    physical custody and money conservation without creating a second supply
    ledger.
    """
    for value, label in ((quantity, "supply quantity"), (unit_price, "supply unit price")):
        require_finite(value, label)
    if quantity <= 0 or unit_price < 0:
        raise ValueError("supply quantity must be positive and unit price non-negative")
    asset = world.transport_assets[asset_id]
    if source_holder_id == asset_id:
        raise ValueError("an asset cannot supply itself")
    if not _asset_is_stationary(world, asset_id):
        raise ValueError("moving or assigned asset cannot be supplied")
    if world.location_of(source_holder_id) != asset.location_id:
        raise ValueError("supply source is not co-located with the asset")
    if good_type_id not in world.goods:
        raise KeyError(good_type_id)
    if supply == "fuel":
        room = float("inf") if asset.fuel_capacity <= 0 else max(0.0, asset.fuel_capacity - asset.fuel)
    else:
        room = max(0.0, asset.supply_capacity.get(supply, float("inf")) - asset.supplies.get(supply, 0.0))
    added = min(quantity, room)
    if added <= 1e-9:
        return 0.0
    if world.quantity_held(source_holder_id, good_type_id) + 1e-9 < added:
        raise ValueError(f"{source_holder_id} lacks {good_type_id} for {asset_id}")
    payee = payee_id or source_holder_id
    total = added * unit_price
    payer = asset.owner_id
    if total > 1e-9 and payer != payee:
        payer_obj = world.actors.get(payer) or world.businesses.get(payer) or world.households.get(payer)
        if payer_obj is None or getattr(payer_obj, "cash", getattr(payer_obj, "money", 0.0)) < total - 1e-9:
            raise ValueError(f"{payer} cannot afford {asset_id} {supply}")
    payment = None
    if total > 1e-9 and payer != payee:
        payment = world.pay(payer, payee, total, causes=causes, reason=f"{asset.id} purchased {supply}")
    payment_causes = (*causes, payment.id) if payment is not None else tuple(causes)
    transferred = world.transfer_goods(
        good_type_id,
        added,
        from_holder=source_holder_id,
        to_holder=asset.id,
        to_owner=asset.owner_id,
        causes=payment_causes,
        reason=f"{asset.id} received physical {supply} from {source_holder_id}",
    )
    transfer_event = world.events[-1]
    consumed = world.consume_goods(
        asset.id,
        good_type_id,
        added,
        causes=(transfer_event.id,),
        reason=f"{asset.id} consumed purchased {supply}",
    )
    consumption_event = world.events[-1]
    if supply == "fuel":
        asset.fuel += added
    else:
        asset.supplies[supply] = asset.supplies.get(supply, 0.0) + added
    if asset.condition > 0 and asset.readiness > 0 and asset.assigned_shipment_id is None:
        asset.available = True
        asset.unavailable_reason = None
    world.record(
        "asset_supply_purchased",
        f"{asset.id} purchased {added:g} {supply}",
        actors=[asset.owner_id, payee],
        entities=[asset.id, source_holder_id, good_type_id, *consumed],
        causes=(*payment_causes, transfer_event.id, consumption_event.id),
        data={"supply": supply, "quantity": added, "unit_price": unit_price, "total": total},
    )
    return added


def service_asset_from_inventory(
    world: World,
    asset_id: str,
    *,
    source_holder_id: str,
    parts_good_type_id: str,
    parts_quantity: float,
    worker_id: str,
    repair_amount: float = 1.0,
    unit_price: float = 0.0,
    labor_price: float = 0.0,
    payee_id: str | None = None,
    causes: tuple[str, ...] = (),
) -> float:
    """Repair a carrier with physical parts and a qualifying worker hour."""
    for value, label in (
        (parts_quantity, "maintenance parts quantity"),
        (repair_amount, "repair amount"),
        (unit_price, "maintenance unit price"),
        (labor_price, "maintenance labor price"),
    ):
        require_finite(value, label)
    if parts_quantity <= 0 or repair_amount <= 0 or unit_price < 0 or labor_price < 0:
        raise ValueError("maintenance quantities and prices are invalid")
    asset = world.transport_assets[asset_id]
    worker = world.actors[worker_id]
    if not _asset_is_stationary(world, asset_id) or asset.cargo_clearance_pending:
        raise ValueError("assigned or uncleared asset cannot be serviced")
    if asset.condition >= 1.0 - 1e-9:
        return 0.0
    if worker.location_id != asset.location_id or worker.traveling_to is not None:
        raise ValueError("maintenance worker is not physically present")
    if not worker.current_activity or not worker.current_activity.startswith("work"):
        raise ValueError("maintenance requires a worker on shift")
    worker_usage = world.runtime.setdefault("_asset_service_worker_hours", {})
    worker_key = (worker_id, world.now.isoformat())
    if worker_usage.get(worker_key, 0.0) >= 1.0 - 1e-9:
        raise ValueError("maintenance worker has no remaining service capacity")
    if world.location_of(source_holder_id) != asset.location_id:
        raise ValueError("maintenance source is not co-located with the asset")
    if world.quantity_held(source_holder_id, parts_good_type_id) + 1e-9 < parts_quantity:
        raise ValueError(f"{source_holder_id} lacks maintenance parts")
    payee = payee_id or source_holder_id
    total = parts_quantity * unit_price + labor_price
    payer = asset.owner_id
    if total > 1e-9 and payer != payee:
        payer_obj = world.actors.get(payer) or world.businesses.get(payer) or world.households.get(payer)
        if payer_obj is None or getattr(payer_obj, "cash", getattr(payer_obj, "money", 0.0)) < total - 1e-9:
            raise ValueError(f"{payer} cannot afford maintenance for {asset_id}")
    payment = None
    if total > 1e-9 and payer != payee:
        payment = world.pay(payer, payee, total, causes=causes, reason=f"{asset.id} maintenance")
    payment_causes = (*causes, payment.id) if payment is not None else tuple(causes)
    transferred = world.transfer_goods(
        parts_good_type_id,
        parts_quantity,
        from_holder=source_holder_id,
        to_holder=asset.id,
        to_owner=asset.owner_id,
        causes=payment_causes,
        reason=f"{asset.id} received maintenance parts",
    )
    transfer_event = world.events[-1]
    consumed = world.consume_goods(
        asset.id,
        parts_good_type_id,
        parts_quantity,
        causes=(transfer_event.id,),
        reason=f"{asset.id} consumed maintenance parts",
    )
    consumption_event = world.events[-1]
    before = asset.condition
    asset.condition = min(1.0, asset.condition + repair_amount)
    if asset.condition > 0 and asset.readiness > 0 and asset.assigned_shipment_id is None:
        asset.available = True
        asset.unavailable_reason = None
    worker_usage[worker_key] = worker_usage.get(worker_key, 0.0) + 1.0
    world.record(
        "asset_maintenance",
        f"{asset.id} was repaired by {worker_id}",
        actors=[asset.owner_id, worker_id, payee],
        entities=[asset.id, source_holder_id, parts_good_type_id, *consumed],
        causes=(*payment_causes, transfer_event.id, consumption_event.id),
        data={"condition_before": before, "condition_after": asset.condition, "parts": parts_quantity, "labor_hours": 1.0, "total": total},
    )
    return asset.condition - before


def advance_asset_services(world: World) -> None:
    """Run declarative, physical refuelling and maintenance plans."""
    for plan in world.runtime.get("asset_service_plans", ()):
        asset = world.transport_assets.get(plan["asset_id"])
        if asset is None or not _asset_is_stationary(world, asset.id, at_place_id=plan["service_location_id"]):
            continue
        supply_plans = []
        if plan.get("supply"):
            supply_plans.append(plan)
        supply_plans.extend(plan.get("supply_plans", ()))
        for supply_plan in supply_plans:
            supply = supply_plan["supply"]
            capacity = asset.fuel_capacity if supply == "fuel" else asset.supply_capacity.get(supply, 0.0)
            current = asset.fuel if supply == "fuel" else asset.supplies.get(supply, 0.0)
            target = capacity * float(supply_plan.get("target_fraction", 0.75))
            if capacity > 0 and current + 1e-9 < target:
                try:
                    supply_asset_from_inventory(
                        world,
                        asset.id,
                        supply,
                        target - current,
                        source_holder_id=supply_plan.get("source_holder_id", plan["source_holder_id"]),
                        good_type_id=supply_plan["good_type_id"],
                        unit_price=float(supply_plan.get("unit_price", 0.0)),
                        payee_id=supply_plan.get("payee_id"),
                    )
                except (KeyError, ValueError):
                    pass
        if asset.condition < float(plan.get("maintenance_threshold", 0.85)):
            try:
                service_asset_from_inventory(
                    world,
                    asset.id,
                    source_holder_id=plan["maintenance_source_holder_id"],
                    parts_good_type_id=plan["maintenance_good_type_id"],
                    parts_quantity=float(plan.get("maintenance_parts", 1.0)),
                    worker_id=plan["maintenance_worker_id"],
                    repair_amount=float(plan.get("repair_amount", 0.25)),
                    unit_price=float(plan.get("maintenance_unit_price", 0.0)),
                    labor_price=float(plan.get("maintenance_labor_price", 0.0)),
                    payee_id=plan.get("maintenance_payee_id"),
                )
            except (KeyError, ValueError):
                pass


def repair_asset(world: World, asset_id: str, amount: float = 1.0, *, source_kind: str = "administrative") -> float:
    require_finite(amount, "repair amount")
    if amount <= 0:
        raise ValueError("repair amount must be positive")
    asset = world.transport_assets[asset_id]
    repaired = min(amount, 1.0 - asset.condition)
    asset.condition += repaired
    if asset.condition > 0 and asset.readiness > 0 and asset.assigned_shipment_id is None:
        asset.available = True
        asset.unavailable_reason = None
    world.record("asset_repaired", f"{asset.id} repaired", entities=[asset.id], data={"amount": repaired, "source_kind": source_kind})
    return repaired


def consume_asset_supply(world: World, asset_id: str, supply: str, quantity: float, *, causes: tuple[str, ...] = ()) -> bool:
    require_finite(quantity, "supply consumption")
    if quantity < 0:
        raise ValueError("supply consumption cannot be negative")
    asset = world.transport_assets[asset_id]
    if supply == "fuel":
        available = asset.fuel
        if available + 1e-9 < quantity:
            asset.available = False
            asset.unavailable_reason = f"{supply} exhausted"
            world.record("asset_unavailable", f"{asset.id} lacks {supply}", entities=[asset.id], causes=causes, data={"supply": supply, "required": quantity, "available": available})
            return False
        asset.fuel -= quantity
    else:
        available = asset.supplies.get(supply, 0.0)
        if available + 1e-9 < quantity:
            asset.available = False
            asset.unavailable_reason = f"{supply} exhausted"
            world.record("asset_unavailable", f"{asset.id} lacks {supply}", entities=[asset.id], causes=causes, data={"supply": supply, "required": quantity, "available": available})
            return False
        asset.supplies[supply] = available - quantity
    world.record("asset_supply_consumed", f"{asset.id} consumed {quantity} {supply}", entities=[asset.id], causes=causes, data={"supply": supply, "quantity": quantity})
    return True


def _asset_resource_requirements(asset: TransportAsset, hours: float) -> tuple[tuple[str, float], ...]:
    require_finite(hours, "asset operating hours")
    if hours <= 0:
        return ()
    requirements: list[tuple[str, float]] = []
    if asset.fuel_capacity > 0:
        requirements.append(("fuel", asset.fuel_burn_per_hour * hours))
    requirements.extend((supply, burn_rate * hours) for supply, burn_rate in asset.supply_burn_per_hour.items())
    return tuple((supply, quantity) for supply, quantity in requirements if quantity > 1e-12)


def _consume_asset_bundle(
    world: World,
    asset_id: str,
    requirements: tuple[tuple[str, float], ...],
    *,
    causes: tuple[str, ...] = (),
) -> bool:
    """Preflight and consume all operating resources as one step.

    No resource is debited until every required resource is available.  This
    is intentionally shared by freight, ordered services, repositioning and
    passenger movement so a failed step cannot burn fuel without advancing.
    """
    asset = world.transport_assets[asset_id]
    for supply, quantity in requirements:
        require_finite(quantity, f"{supply} operating requirement")
        if quantity < 0:
            raise ValueError("operating requirements cannot be negative")
        available = asset.fuel if supply == "fuel" else asset.supplies.get(supply, 0.0)
        if available + 1e-9 < quantity:
            asset.available = False
            asset.unavailable_reason = f"{supply} exhausted"
            world.record(
                "asset_unavailable",
                f"{asset.id} lacks {supply}",
                entities=[asset.id],
                causes=causes,
                data={"supply": supply, "required": quantity, "available": available},
            )
            return False
    for supply, quantity in requirements:
        if not consume_asset_supply(world, asset_id, supply, quantity, causes=causes):
            raise RuntimeError("asset resource bundle changed during atomic consumption")
    return True


def dispatch_freight(
    world: World,
    contract_id: str,
    *,
    carrier_id: str,
    origin_facility_id: str,
    destination_facility_id: str,
    loading_hours: float = 1.0,
    unloading_hours: float = 1.0,
    pace: str = "steady",
    carrier_plan: tuple[str, ...] | None = None,
    relay_leg_counts: tuple[int, ...] | None = None,
    service_id: str | None = None,
    route_ids: tuple[str, ...] | None = None,
) -> Shipment:
    """Create a queued physical freight journey without moving the clock."""
    for value, label in ((loading_hours, "loading hours"), (unloading_hours, "unloading hours")):
        require_finite(value, label)
    if loading_hours <= 0 or unloading_hours <= 0:
        raise ValueError("handling times must be positive")
    if pace not in PACE_MULTIPLIERS:
        raise ValueError(f"unknown freight pace {pace!r}")
    contract = world.contracts[contract_id]
    if contract.shipment_id is not None or contract.status not in {"open", "allocated"}:
        raise ValueError(f"contract {contract_id} is already dispatched or not dispatchable")
    asset = world.transport_assets[carrier_id]
    origin = world.transport_facilities[origin_facility_id]
    destination = world.transport_facilities[destination_facility_id]
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {carrier_id} is unavailable")
    if asset.cargo_clearance_pending or _asset_load(world, asset.id) > 1e-9:
        raise ValueError(f"carrier {carrier_id} still holds unresolved cargo")
    if asset.condition <= 0 or asset.readiness <= 0:
        raise ValueError(f"carrier {carrier_id} is not operational")
    if asset.location_id != origin.place_id or origin.place_id != contract.origin_id:
        raise ValueError("carrier and origin facility are not at the contract origin")
    if destination.place_id != contract.destination_id:
        raise ValueError("destination facility is not at the contract destination")
    service = world.transport_services.get(service_id or "") if service_id else None
    if service_id and service is None:
        raise KeyError(service_id)
    if service is not None:
        if service.asset_id != carrier_id or service.status not in {"ready", "waiting_asset"}:
            raise ValueError("service is not ready for this carrier")
        if service.stop_place_ids[service.current_stop_index] != contract.origin_id:
            raise ValueError("contract origin is not the service's current stop")
        if _service_next_stop(service) != contract.destination_id:
            raise ValueError("contract destination is not the service's next stop")
        if not service_accepts(service, contract.good_type_id):
            raise ValueError("service does not accept this cargo")
    if _asset_load(world, asset.id) + contract.quantity > asset.capacity + 1e-9:
        raise ValueError("carrier capacity exceeded")
    planned_carriers = tuple(carrier_plan or (carrier_id,))
    if not planned_carriers or planned_carriers[0] != carrier_id:
        raise ValueError("carrier plan must begin with the dispatch carrier")
    if len(set(planned_carriers)) != len(planned_carriers):
        raise ValueError("relay carrier plan cannot reuse one asset")
    if route_ids is not None:
        if not route_ids:
            raise ValueError("explicit route cannot be empty")
        path = [world.routes[route_id] for route_id in route_ids]
        previous = contract.origin_id
        for route in path:
            if route.origin_id != previous:
                raise ValueError("explicit route is not a contiguous accessible carrier path")
            previous = route.destination_id
        if previous != contract.destination_id:
            raise ValueError("explicit route does not reach the contract destination")
    else:
        path = best_route(world, contract.origin_id, contract.destination_id, mode=None if carrier_plan else asset.asset_type)
    if not path:
        raise ValueError("contract has no physical route")
    planned_legs = tuple(relay_leg_counts or (len(path),))
    if len(planned_carriers) != len(planned_legs) or any(count <= 0 for count in planned_legs) or sum(planned_legs) != len(path):
        raise ValueError("relay carrier plan must partition the physical route")
    route_offset = 0
    for plan_index, planned_id in enumerate(planned_carriers):
        planned_asset = world.transport_assets.get(planned_id)
        if planned_asset is None:
            raise KeyError(planned_id)
        _validate_asset_prerequisites(
            world,
            planned_asset,
            assignment_id=None if plan_index == 0 else f"shipment-{len(world.shipments) + 1}",
            service_id=service_id if plan_index == 0 else None,
        )
        if contract.quantity > planned_asset.capacity + 1e-9:
            raise ValueError(f"carrier {planned_id} capacity exceeded")
        if plan_index > 0:
            if planned_asset.location_id != path[route_offset].origin_id:
                raise ValueError(f"relay carrier {planned_id} is not at its handoff point")
        for route in path[route_offset:route_offset + planned_legs[plan_index]]:
            if not route_is_accessible(world, route, mode=planned_asset.asset_type):
                raise ValueError(f"carrier {planned_id} cannot use route {route.id}")
        route_offset += planned_legs[plan_index]
    # Preflight the same physical stock rule used by allocation.  This keeps
    # an invalid dispatch attempt from changing an open contract to failed
    # merely because the caller discovered missing cargo too late.
    seller = world.businesses[contract.seller_id]
    reserved = sum(
        other.quantity
        for other in world.contracts.values()
        if other.id != contract.id
        and other.seller_id == seller.id
        and other.good_type_id == contract.good_type_id
        and other.status in {"allocated", "in_transit"}
    )
    available = world.quantity_held(seller.id, contract.good_type_id)
    available = max(available, world.quantity_owned_at(seller.id, origin.place_id, contract.good_type_id))
    if available - reserved + 1e-9 < contract.quantity:
        raise ValueError("goods unavailable at dispatch")
    if contract.status == "open":
        allocate_contract(world, contract_id, source_place_id=origin.place_id)
    if contract.status != "allocated":
        raise ValueError(f"contract {contract_id} is not allocated")
    shipment = Shipment(
        id=f"shipment-{len(world.shipments) + 1}",
        contract_id=contract.id,
        origin_id=contract.origin_id,
        destination_id=contract.destination_id,
        route_ids=tuple(route.id for route in path),
        status="queued",
        carrier_id=asset.id,
        origin_facility_id=origin.id,
        destination_facility_id=destination.id,
        loading_remaining_hours=loading_hours,
        unloading_remaining_hours=unloading_hours,
        pace=pace,
        carrier_plan=planned_carriers,
        relay_leg_counts=planned_legs,
        service_id=service_id,
    )
    world.add(shipment)
    # Reserve at assignment time, not when loading eventually begins.
    assign_asset(world, asset.id, shipment.id, kind="freight")
    if service is not None:
        service.status = "waiting_asset"
        world.record("transport_service_cargo_assigned", f"{service.id} assigned {shipment.id}", entities=[service.id, shipment.id, asset.id])
    for relay_asset_id in planned_carriers[1:]:
        relay_asset = world.transport_assets[relay_asset_id]
        relay_asset.reserved_for_shipment_id = shipment.id
        world.record(
            "asset_relay_reserved",
            f"{relay_asset.id} reserved for {shipment.id}",
            entities=[relay_asset.id, shipment.id],
            data={"handoff_place": relay_asset.location_id},
        )
    origin.queue.append(shipment.id)
    contract.shipment_id = shipment.id
    queued = world.record(
        "freight_queued",
        f"{contract.id} queued for loading at {origin.id}",
        actors=[contract.seller_id, asset.owner_id],
        entities=[contract.id, shipment.id, origin.id],
        causes=contract.causal_event_ids[-1:],
    )
    contract.causal_event_ids.append(queued.id)
    return shipment


def interrupt_freight(world: World, shipment_id: str, hours: float, *, reason: str, causes: tuple[str, ...] = ()) -> Shipment:
    """Pause a physical journey without releasing its cargo or carrier."""
    require_finite(hours, "journey interruption hours")
    if hours <= 0:
        raise ValueError("journey interruption must last at least one hour")
    shipment = world.shipments[shipment_id]
    if shipment.status in {"delivered", "failed"}:
        raise ValueError("terminal journey cannot be interrupted")
    shipment.delay_remaining_hours += hours
    shipment.interruption_reason = reason
    event = world.record(
        "freight_interrupted",
        f"{shipment.id} interrupted for {hours:g} hours",
        entities=[shipment.id, *( [shipment.carrier_id] if shipment.carrier_id else [])],
        causes=causes,
        data={"hours": hours, "reason": reason},
    )
    world.contracts[shipment.contract_id].causal_event_ids.append(event.id)
    return shipment


def divert_freight(world: World, shipment_id: str, route_ids: tuple[str, ...], *, reason: str, causes: tuple[str, ...] = ()) -> Shipment:
    """Replace the remaining route only at a physical route boundary."""
    shipment = world.shipments[shipment_id]
    if shipment.status in {"delivered", "failed", "unloading", "arrived_queue"}:
        raise ValueError("journey cannot be diverted in its current state")
    if not route_ids:
        raise ValueError("diversion requires at least one route")
    asset = world.transport_assets[shipment.carrier_id or ""]
    if shipment.status == "in_transit" and shipment.elapsed_hours > 1e-9:
        raise ValueError("journey can only divert between route legs")
    start = asset.location_id
    previous = start
    for route_id in route_ids:
        route = world.routes[route_id]
        if route.origin_id != previous or not route_is_accessible(world, route, mode=asset.asset_type):
            raise ValueError("diversion route is not physically available from the carrier")
        previous = route.destination_id
    if previous != shipment.destination_id:
        raise ValueError("diversion must still reach the contracted destination")
    prefix = shipment.route_ids[:shipment.current_route_index]
    if len(shipment.carrier_plan) > 1:
        # The diverted remaining path is explicitly carried by the current
        # asset.  Release future relay reservations only after the replacement
        # path has been fully validated above.
        for future_id in shipment.carrier_plan[shipment.carrier_plan_index + 1:]:
            future = world.transport_assets.get(future_id)
            if future is not None and future.reserved_for_shipment_id == shipment.id:
                future.reserved_for_shipment_id = None
                world.record("asset_relay_reservation_cleared", f"{future.id} released from diverted {shipment.id}", entities=[future.id, shipment.id])
        shipment.carrier_plan = shipment.carrier_plan[:shipment.carrier_plan_index + 1]
        shipment.relay_leg_counts = (*shipment.relay_leg_counts[:shipment.carrier_plan_index], len(route_ids))
    shipment.route_ids = tuple([*prefix, *route_ids])
    shipment.current_route_index = len(prefix)
    event = world.record(
        "freight_diverted",
        f"{shipment.id} diverted toward {shipment.destination_id}",
        entities=[shipment.id, asset.id, *route_ids],
        causes=causes,
        data={"reason": reason},
    )
    world.contracts[shipment.contract_id].causal_event_ids.append(event.id)
    return shipment


def abandon_freight(world: World, shipment_id: str, *, reason: str, causes: tuple[str, ...] = ()) -> Shipment:
    """Fail a journey while retaining an auditable physical cargo holder."""
    shipment = world.shipments[shipment_id]
    if shipment.status in {"delivered", "failed"}:
        raise ValueError("terminal journey cannot be abandoned")
    event = world.record(
        "freight_abandoned",
        f"{shipment.id} abandoned: {reason}",
        entities=[shipment.id, *( [shipment.carrier_id] if shipment.carrier_id else [])],
        causes=causes,
        data={"reason": reason},
    )
    world.contracts[shipment.contract_id].causal_event_ids.append(event.id)
    _fail(world, shipment, f"journey abandoned: {reason}")
    return shipment


def _remove_active(facility: TransportFacility, shipment_id: str) -> None:
    if shipment_id in facility.active_shipments:
        facility.active_shipments.remove(shipment_id)


def _clear_relay_reservations(world: World, shipment: Shipment) -> None:
    for asset_id in shipment.carrier_plan[shipment.carrier_plan_index + 1:]:
        asset = world.transport_assets.get(asset_id)
        if asset is not None and asset.reserved_for_shipment_id == shipment.id:
            asset.reserved_for_shipment_id = None
            world.record("asset_relay_reservation_cleared", f"{asset.id} released from {shipment.id}", entities=[asset.id, shipment.id])


def _relay_boundary_reached(shipment: Shipment) -> bool:
    if shipment.carrier_plan_index + 1 >= len(shipment.carrier_plan):
        return False
    boundary = sum(shipment.relay_leg_counts[:shipment.carrier_plan_index + 1])
    return shipment.current_route_index >= boundary


def _try_relay_handoff(world: World, shipment: Shipment) -> bool:
    if not _relay_boundary_reached(shipment):
        return True
    current_asset = world.transport_assets[shipment.carrier_id or ""]
    next_asset_id = shipment.carrier_plan[shipment.carrier_plan_index + 1]
    next_asset = world.transport_assets[next_asset_id]
    if (
        next_asset.reserved_for_shipment_id != shipment.id
        or not next_asset.available
        or next_asset.assigned_shipment_id is not None
        or next_asset.location_id != current_asset.location_id
    ):
        return False
    contract = world.contracts[shipment.contract_id]
    _validate_asset_prerequisites(world, next_asset, assignment_id=shipment.id)
    quantity = world.quantity_held(current_asset.id, contract.good_type_id)
    if quantity + 1e-9 < contract.quantity:
        _fail(world, shipment, "relay handoff cargo unavailable")
        return False
    if quantity > next_asset.capacity + 1e-9:
        _fail(world, shipment, f"relay carrier {next_asset.id} capacity exceeded")
        return False
    snapshot = {
        "current": (current_asset.assigned_shipment_id, current_asset.assignment_kind, current_asset.available, current_asset.unavailable_reason, current_asset.cargo_clearance_pending),
        "next": (next_asset.assigned_shipment_id, next_asset.assignment_kind, next_asset.available, next_asset.unavailable_reason, next_asset.reserved_for_shipment_id, next_asset.cargo_clearance_pending),
        "shipment": (shipment.carrier_id, shipment.carrier_plan_index, shipment.status),
        "lots": copy.deepcopy(world.lots),
        "lot_number": world._lot_number,
        "lot_original": copy.deepcopy(world._lot_original_quantity),
        "lot_creation": copy.deepcopy(world._lot_counts_as_creation),
        "events": len(world.events),
        "event_number": world._event_number,
        "causes": list(contract.causal_event_ids),
    }
    try:
        release_asset(world, current_asset.id)
        next_asset.reserved_for_shipment_id = None
        assign_asset(world, next_asset.id, shipment.id, kind="freight")
        world.transfer_goods(
            contract.good_type_id,
            contract.quantity,
            from_holder=current_asset.id,
            to_holder=next_asset.id,
            to_owner=contract.seller_id,
            causes=contract.causal_event_ids[-1:],
            reason=f"{shipment.id} cargo handed off at {current_asset.location_id}",
        )
    except Exception:
        current_asset.assigned_shipment_id, current_asset.assignment_kind, current_asset.available, current_asset.unavailable_reason, current_asset.cargo_clearance_pending = snapshot["current"]
        next_asset.assigned_shipment_id, next_asset.assignment_kind, next_asset.available, next_asset.unavailable_reason, next_asset.reserved_for_shipment_id, next_asset.cargo_clearance_pending = snapshot["next"]
        shipment.carrier_id, shipment.carrier_plan_index, shipment.status = snapshot["shipment"]
        world.lots = snapshot["lots"]
        world._lot_number = snapshot["lot_number"]
        world._lot_original_quantity = snapshot["lot_original"]
        world._lot_counts_as_creation = snapshot["lot_creation"]
        del world.events[snapshot["events"]:]
        world._event_number = snapshot["event_number"]
        contract.causal_event_ids[:] = snapshot["causes"]
        raise
    # Releasing the old carrier while it still held cargo marks it as awaiting
    # clearance.  The physical handoff has now completed, so it is safe to
    # make that carrier available for another assignment.
    current_asset.cargo_clearance_pending = _asset_load(world, current_asset.id) > 1e-9
    if (
        not current_asset.cargo_clearance_pending
        and current_asset.assigned_shipment_id is None
        and current_asset.available
        and current_asset.home_location_id is not None
        and current_asset.location_id != current_asset.home_location_id
    ):
        _begin_reposition(world, current_asset)
    shipment.carrier_id = next_asset.id
    shipment.carrier_plan_index += 1
    shipment.status = "in_transit"
    event = world.record(
        "freight_handoff",
        f"{shipment.id} changed carriers at {current_asset.location_id}",
        entities=[shipment.id, current_asset.id, next_asset.id, current_asset.location_id],
        causes=contract.causal_event_ids[-1:],
        data={"from_carrier": current_asset.id, "to_carrier": next_asset.id},
    )
    contract.causal_event_ids.append(event.id)
    return True


def _fail(world: World, shipment: Shipment, reason: str) -> None:
    contract = world.contracts[shipment.contract_id]
    contract.status = "failed"
    contract.failure_reason = reason
    failed = world.record(
        "freight_failed",
        f"{shipment.id} failed: {reason}",
        actors=[contract.seller_id, contract.buyer_id],
        entities=[contract.id, shipment.id],
        causes=contract.causal_event_ids[-1:],
        data={"reason": reason},
    )
    contract.causal_event_ids.append(failed.id)
    shipment.status = "failed"
    _clear_relay_reservations(world, shipment)
    if shipment.carrier_id is not None and shipment.carrier_id in world.transport_assets:
        asset = world.transport_assets[shipment.carrier_id]
        hold = "fuel" in reason or "condition" in reason or "supply" in reason or "exhausted" in reason
        release_asset(world, asset.id, available=not hold, reason=reason if hold else None)
    for facility in world.transport_facilities.values():
        if shipment.id in facility.queue:
            facility.queue.remove(shipment.id)
        if shipment.id in facility.arrival_queue:
            facility.arrival_queue.remove(shipment.id)
        _remove_active(facility, shipment.id)


def _begin_unloading(world: World, shipment: Shipment) -> bool:
    facility = world.transport_facilities[shipment.destination_facility_id or ""]
    if len(facility.active_shipments) >= facility.handling_capacity:
        if shipment.id not in facility.arrival_queue:
            facility.arrival_queue.append(shipment.id)
            facility.peak_queue_length = max(facility.peak_queue_length, len(facility.arrival_queue))
        shipment.status = "arrived_queue"
        return False
    facility.active_shipments.append(shipment.id)
    shipment.status = "unloading"
    world.record(
        "unloading_started",
        f"{shipment.id} began unloading at {facility.id}",
        entities=[shipment.id, facility.id],
    )
    return True


def _admit_arrivals(world: World) -> None:
    for facility in world.transport_facilities.values():
        while facility.arrival_queue and len(facility.active_shipments) < facility.handling_capacity:
            shipment_id = facility.arrival_queue.pop(0)
            shipment = world.shipments[shipment_id]
            if shipment.status == "arrived_queue":
                _begin_unloading(world, shipment)


def _admit_loads(world: World) -> None:
    """Start only the work that was admitted at the beginning of this step."""
    for facility in world.transport_facilities.values():
        while facility.queue and len(facility.active_shipments) < facility.handling_capacity:
            facility.peak_queue_length = max(facility.peak_queue_length, len(facility.queue))
            shipment_id = facility.queue.pop(0)
            shipment = world.shipments[shipment_id]
            if shipment.status != "queued":
                continue
            facility.active_shipments.append(shipment.id)
            shipment.status = "loading"
            facility.peak_queue_length = max(facility.peak_queue_length, len(facility.queue))
            world.record("loading_started", f"{shipment.id} began loading at {facility.id}", entities=[shipment.id, facility.id])


def _begin_reposition(world: World, asset: TransportAsset) -> None:
    """Start an empty physical return to an asset's declared home."""
    if asset.home_location_id is None or asset.location_id == asset.home_location_id:
        return
    path = route_path(world, asset.location_id, asset.home_location_id, mode=asset.asset_type)
    if not path:
        asset.available = False
        asset.unavailable_reason = "no physical return route"
        return
    world._event_number += 1
    assignment_id = f"reposition-{world._event_number}"
    asset.assigned_shipment_id = assignment_id
    asset.assignment_kind = "reposition"
    asset.available = False
    asset.unavailable_reason = None
    asset.return_route_ids = tuple(route.id for route in path)
    asset.return_route_index = 0
    asset.return_elapsed_hours = 0.0
    world.record(
        "asset_reposition_started",
        f"{asset.id} began empty return to {asset.home_location_id}",
        entities=[asset.id, *asset.return_route_ids],
        data={"destination": asset.home_location_id},
    )


def _begin_cargo_recovery(world: World, shipment: Shipment, asset: TransportAsset, seller_location_id: str) -> bool:
    """Start an empty-handed-by-person, cargo-bearing physical return.

    The cargo stays on the failed carrier until this route reaches the
    seller.  Recovery never uses ``transfer_goods`` merely because a holder's
    last waypoint happens to equal the seller's place.
    """
    initial_elapsed = 0.0
    if shipment.current_route_index < len(shipment.route_ids) and shipment.elapsed_hours > 1e-9:
        current_route = world.routes[shipment.route_ids[shipment.current_route_index]]
        forward_duration = effective_route_hours(world, current_route, mode=asset.asset_type)
        reverse_candidates = [
            route
            for route in world.routes.values()
            if route.origin_id == current_route.destination_id
            and route.destination_id == current_route.origin_id
            and route_is_accessible(world, route, mode=asset.asset_type)
        ]
        if not reverse_candidates:
            asset.available = False
            asset.unavailable_reason = "no physical reverse route for cargo recovery"
            return False
        reverse_route = min(
            reverse_candidates,
            key=lambda route: effective_route_hours(world, route, mode=asset.asset_type),
        )
        reverse_duration = effective_route_hours(world, reverse_route, mode=asset.asset_type)
        initial_elapsed = reverse_duration * max(0.0, 1.0 - shipment.elapsed_hours / forward_duration)
        onward = route_path(world, current_route.origin_id, seller_location_id, mode=asset.asset_type)
        path = [reverse_route, *onward]
    else:
        path = route_path(world, asset.location_id, seller_location_id, mode=asset.asset_type)
    if not path:
        asset.available = False
        asset.unavailable_reason = "no physical cargo recovery route"
        return False
    asset.assigned_shipment_id = f"cargo-recovery:{shipment.id}"
    asset.assignment_kind = "cargo_recovery"
    asset.available = False
    asset.unavailable_reason = None
    asset.return_route_ids = tuple(route.id for route in path)
    asset.return_route_index = 0
    asset.return_elapsed_hours = initial_elapsed
    world.record(
        "cargo_recovery_started",
        f"{shipment.id} cargo began physical recovery",
        entities=[shipment.id, asset.id, *asset.return_route_ids],
        data={"destination": seller_location_id, "mid_route": initial_elapsed > 0},
    )
    return True


def _advance_asset_reposition(world: World, asset: TransportAsset, hours: float) -> None:
    remaining = hours
    while remaining > 1e-9 and asset.assignment_kind in {"reposition", "cargo_recovery"}:
        if asset.return_route_index >= len(asset.return_route_ids):
            destination_id = asset.home_location_id or asset.location_id
            if asset.assignment_kind == "cargo_recovery":
                shipment_id = asset.assigned_shipment_id.split(":", 1)[1] if asset.assigned_shipment_id else ""
                shipment = world.shipments.get(shipment_id)
                if shipment is None or shipment.status != "failed":
                    asset.available = False
                    asset.unavailable_reason = "cargo recovery has no failed shipment"
                    return
                contract = world.contracts[shipment.contract_id]
                destination_id = world.businesses[contract.seller_id].location_id
                asset.location_id = destination_id
                quantity = world.quantity_held(asset.id, contract.good_type_id)
                if quantity + 1e-9 < contract.quantity:
                    asset.available = False
                    asset.unavailable_reason = "failed cargo missing during recovery"
                    return
                world.transfer_goods(
                    contract.good_type_id,
                    contract.quantity,
                    from_holder=asset.id,
                    to_holder=contract.seller_id,
                    to_owner=contract.seller_id,
                    causes=contract.causal_event_ids[-1:],
                    reason=f"{contract.id} failed cargo recovered after physical return",
                )
                asset.cargo_clearance_pending = False
                asset.return_route_ids = ()
                asset.return_route_index = 0
                asset.return_elapsed_hours = 0.0
                release_asset(world, asset.id, start_reposition=False)
                world.record(
                    "failed_cargo_recovered",
                    f"{contract.id} cargo recovered after physical return",
                    entities=[contract.id, shipment.id, asset.id],
                )
                return
            asset.location_id = destination_id
            asset.return_route_ids = ()
            asset.return_route_index = 0
            asset.return_elapsed_hours = 0.0
            release_asset(world, asset.id, start_reposition=False)
            world.record("asset_reposition_arrived", f"{asset.id} returned to home", entities=[asset.id, asset.location_id])
            return
        route = world.routes[asset.return_route_ids[asset.return_route_index]]
        if not route_is_accessible(world, route, mode=asset.asset_type):
            asset.unavailable_reason = "return route blocked"
            world.record("asset_reposition_delayed", f"{asset.id} waiting on return route", entities=[asset.id, route.id])
            return
        duration = effective_route_hours(world, route, mode=asset.asset_type)
        available = max(0.0, duration - asset.return_elapsed_hours)
        if available <= 1e-9:
            asset.return_route_index += 1
            asset.return_elapsed_hours = 0.0
            asset.location_id = route.destination_id
            continue
        step = min(remaining, available)
        if not _consume_asset_bundle(world, asset.id, _asset_resource_requirements(asset, step)):
            asset.unavailable_reason = "fuel exhausted during return"
            return
        asset.accrued_operating_cost += asset.operating_cost_per_hour * step
        asset.operating_cost_due += asset.operating_cost_per_hour * step
        if asset.operating_cost_per_hour > 0:
            cost = asset.operating_cost_per_hour * step
            cost_event = world.record(
                "transport_cost_accrued",
                f"{asset.id} accrued repositioning cost",
                actors=[asset.owner_id],
                entities=[asset.id, route.id],
                data={"amount": cost, "outstanding": asset.operating_cost_due},
            )
            settle_operating_cost(world, asset.id, causes=(cost_event.id,))
        _record_asset_wear(world, asset.id, step)
        asset.return_elapsed_hours += step
        remaining -= step
        if asset.return_elapsed_hours + 1e-9 >= duration:
            asset.location_id = route.destination_id
            asset.return_route_index += 1
            asset.return_elapsed_hours = 0.0
            world.record("asset_reposition_leg_arrived", f"{asset.id} reached {route.destination_id}", entities=[asset.id, route.id])


def _settle_arrival(world: World, shipment: Shipment) -> None:
    contract = world.contracts[shipment.contract_id]
    asset = world.transport_assets[shipment.carrier_id or ""]
    buyer = world.businesses[contract.buyer_id]
    seller = world.businesses[contract.seller_id]
    destination = world.transport_facilities[shipment.destination_facility_id or ""]
    total = contract.quantity * contract.unit_price
    if contract.due_at is not None and world.now > contract.due_at and not contract.late_reported:
        late = world.record(
            "contract_late",
            f"{contract.id} missed its delivery deadline",
            actors=[contract.seller_id, contract.buyer_id],
            entities=[contract.id, shipment.id],
            causes=contract.causal_event_ids[-1:],
            data={"due_at": contract.due_at.isoformat(), "arrived_at": world.now.isoformat()},
        )
        contract.causal_event_ids.append(late.id)
        contract.late_reported = True
    # Validate both sides before mutating either side.  Failed settlement
    # leaves the cargo aboard the carrier and never gives it to an insolvent
    # buyer.
    if buyer.cash + 1e-9 < total:
        _fail(world, shipment, "buyer insolvent at delivery")
        return
    if world.quantity_held(asset.id, contract.good_type_id) + 1e-9 < contract.quantity:
        _fail(world, shipment, "carrier cargo unavailable at unloading")
        return
    # A market's place is the canonical public stock holder.  Delivering to
    # its cashier business would reduce demand while making the goods
    # invisible to market purchases.
    if buyer.kind == "market":
        delivery_holder = destination.place_id
    else:
        storage_holder = destination.storage_access_id if destination.storage_access_id == buyer.id else None
        delivery_holder = storage_holder or (buyer.location_id if buyer.kind == "shop" else buyer.id)
    if destination.storage_capacity is not None:
        stored = sum(lot.quantity for lot in world.lots_held_by(delivery_holder))
        if stored + contract.quantity > destination.storage_capacity + 1e-9:
            _fail(world, shipment, "destination storage capacity exceeded")
            return
    payment = None
    try:
        payment = world.pay(
            buyer.id,
            seller.id,
            total,
            causes=contract.causal_event_ids[-1:],
            reason=f"{contract.id} freight settlement",
        )
        world.transfer_goods(
            contract.good_type_id,
            contract.quantity,
            from_holder=asset.id,
            to_holder=delivery_holder,
            to_owner=buyer.id,
            causes=contract.causal_event_ids[-1:],
            reason=f"{contract.id} goods unloaded at destination",
        )
        delivered = world.record(
            "contract_delivered",
            f"{contract.id} delivered after carrier unloading",
            actors=[buyer.id, seller.id],
            entities=[contract.id, shipment.id, asset.id],
            causes=contract.causal_event_ids[-1:],
        )
        contract.causal_event_ids.append(delivered.id)
        if buyer.kind == "market":
            from .market import accept_market_delivery

            market_id = next(
                (market.id for market in world.markets.values() if market.place_id == buyer.location_id),
                None,
            )
            if market_id is not None:
                accept_market_delivery(world, market_id, contract.good_type_id, contract.quantity, causes=contract.causal_event_ids[-1:])
    except (KeyError, ValueError) as exc:
        # The preflight above makes this path defensive.  If a future
        # mutation fails after payment, reverse it before recording failure.
        if payment is not None:
            world.pay(seller.id, buyer.id, total, reason=f"reverse failed {contract.id} settlement")
        _fail(world, shipment, f"settlement unavailable: {exc}")
        return
    contract.status = "settled"
    contract.delivered_at = world.now
    settled = world.record(
        "contract_settled",
        f"{contract.id} settled after physical delivery",
        actors=[seller.id, buyer.id],
        entities=[contract.id],
        causes=[payment.id, delivered.id],
    )
    contract.causal_event_ids.append(settled.id)
    shipment.status = "delivered"
    _clear_relay_reservations(world, shipment)
    if shipment.service_id is not None:
        service = world.transport_services[shipment.service_id]
        if _service_next_stop(service) == contract.destination_id:
            previous_index = service.current_stop_index
            service.current_stop_index = (service.current_stop_index + 1) % len(service.stop_place_ids)
            if service.current_stop_index == 0:
                service.completed_cycles += 1
            service.status = "waiting_asset"
            world.record(
                "transport_service_cargo_arrived",
                f"{service.id} completed its cargo leg",
                entities=[service.id, shipment.id, asset.id, contract.destination_id],
                data={"from_stop_index": previous_index, "to_stop_index": service.current_stop_index},
            )
    release_asset(world, asset.id)


def _advance_freight_step(world: World, hours: float) -> list[str]:
    """Advance one shared handling/movement interval without changing time."""
    freight_assets = world.runtime.setdefault("_freight_advanced_assets", set())
    for asset in list(world.transport_assets.values()):
        if asset.assignment_kind in {"reposition", "cargo_recovery"}:
            freight_assets.add(asset.id)
            _advance_asset_reposition(world, asset, hours)
    _admit_arrivals(world)
    _admit_loads(world)
    settled: list[str] = []
    for shipment in list(world.shipments.values()):
        if shipment.carrier_id is None or shipment.status in {"delivered", "failed"}:
            continue
        asset = world.transport_assets[shipment.carrier_id]
        freight_assets.add(asset.id)
        origin = world.transport_facilities[shipment.origin_facility_id or ""]
        destination = world.transport_facilities[shipment.destination_facility_id or ""]
        remaining = float(hours)
        if shipment.status == "handoff_wait":
            if not _try_relay_handoff(world, shipment):
                if shipment.status == "failed":
                    continue
                continue
            asset = world.transport_assets[shipment.carrier_id or ""]
        if shipment.delay_remaining_hours > 0:
            step = min(remaining, shipment.delay_remaining_hours)
            shipment.delay_remaining_hours -= step
            remaining -= step
            if remaining <= 1e-9:
                continue
        if shipment.status == "loading":
            step = min(remaining, shipment.loading_remaining_hours)
            shipment.loading_remaining_hours -= step
            origin.handling_hours += step
            remaining -= step
            if shipment.loading_remaining_hours > 1e-9:
                continue
            contract = world.contracts[shipment.contract_id]
            held_by_seller = world.quantity_held(contract.seller_id, contract.good_type_id)
            if held_by_seller + 1e-9 < contract.quantity:
                world.transfer_owned_goods_at(
                    contract.seller_id,
                    origin.place_id,
                    contract.good_type_id,
                    contract.quantity - held_by_seller,
                    to_holder=contract.seller_id,
                    causes=contract.causal_event_ids[-1:],
                    reason=f"{contract.id} market custody made available for loading",
                )
            loaded = world.transfer_goods(
                contract.good_type_id,
                contract.quantity,
                from_holder=contract.seller_id,
                to_holder=asset.id,
                to_owner=contract.seller_id,
                causes=contract.causal_event_ids[-1:],
                reason=f"{contract.id} cargo loaded onto {asset.id}",
            )
            shipment.cargo_lot_ids = [lot.id for lot in loaded]
            origin.completed_operations += 1
            shipment.status = "in_transit"
            contract.status = "in_transit"
            _remove_active(origin, shipment.id)
            departed = world.record("freight_departed", f"{shipment.id} departed {origin.id}", entities=[shipment.id, asset.id, origin.id], causes=contract.causal_event_ids[-1:])
            contract.causal_event_ids.append(departed.id)
        if shipment.status == "in_transit":
            while remaining > 1e-9 and shipment.current_route_index < len(shipment.route_ids):
                if not _try_relay_handoff(world, shipment):
                    if shipment.status == "failed":
                        break
                    shipment.status = "handoff_wait"
                    world.record(
                        "freight_handoff_waiting",
                        f"{shipment.id} waiting for its next carrier",
                        entities=[shipment.id, shipment.carrier_id or ""],
                    )
                    break
                asset = world.transport_assets[shipment.carrier_id or ""]
                if asset.condition <= 0:
                    _fail(world, shipment, "carrier condition unavailable")
                    break
                route = world.routes[shipment.route_ids[shipment.current_route_index]]
                if not route_is_accessible(world, route, mode=asset.asset_type):
                    condition_event_id = next(
                        (
                            event.id
                            for event in reversed(world.events)
                            if event.kind == "route_condition_changed" and route.id in event.entities
                        ),
                        None,
                    )
                    if shipment.interruption_reason != f"route:{condition_event_id}":
                        condition_causes = tuple(
                            event.id
                            for event in reversed(world.events)
                            if event.kind == "route_condition_changed" and route.id in event.entities
                        )[:1]
                        world.record(
                            "freight_delayed",
                            f"{shipment.id} delayed by route conditions",
                            entities=[shipment.id, asset.id, route.id],
                            causes=tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:]) + condition_causes,
                            data={"hazard": world.route_conditions.get(route.id).hazard if route.id in world.route_conditions else None},
                        )
                        shipment.interruption_reason = f"route:{condition_event_id}"
                    break
                if shipment.interruption_reason and shipment.interruption_reason.startswith("route:"):
                    shipment.interruption_reason = None
                duration = effective_route_hours(world, route, mode=asset.asset_type) * PACE_MULTIPLIERS[shipment.pace]
                available = max(0.0, duration - shipment.elapsed_hours)
                if available <= 1e-9:
                    if shipment.elapsed_hours > duration + 1e-9:
                        world.record(
                            "freight_progress_normalized",
                            f"{shipment.id} completed a shortened route leg",
                            entities=[shipment.id, asset.id, route.id],
                            data={"previous_elapsed": shipment.elapsed_hours, "new_duration": duration},
                        )
                    shipment.current_route_index += 1
                    shipment.elapsed_hours = 0.0
                    asset.location_id = route.destination_id
                    world.record("freight_arrived_leg", f"{shipment.id} reached {route.destination_id}", entities=[shipment.id, asset.id, route.id])
                    continue
                step = min(remaining, available)
                causes = tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:])
                requirements = _asset_resource_requirements(asset, step)
                if not _consume_asset_bundle(world, asset.id, requirements, causes=causes):
                    missing = next(
                        (
                            supply
                            for supply, quantity in requirements
                            if (asset.fuel if supply == "fuel" else asset.supplies.get(supply, 0.0)) + 1e-9 < quantity
                        ),
                        "operating resource",
                    )
                    _fail(world, shipment, f"carrier {missing} exhausted")
                    break
                cost = asset.operating_cost_per_hour * step
                asset.accrued_operating_cost += cost
                asset.operating_cost_due += cost
                _record_asset_wear(
                    world,
                    asset.id,
                    step,
                    causes=tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:]),
                )
                shipment.elapsed_hours += step
                remaining -= step
                if shipment.elapsed_hours + 1e-9 < duration:
                    break
                shipment.current_route_index += 1
                shipment.elapsed_hours = 0.0
                asset.location_id = route.destination_id
                world.record("freight_arrived_leg", f"{shipment.id} reached {route.destination_id}", entities=[shipment.id, asset.id, route.id])
            if shipment.status == "in_transit" and shipment.current_route_index >= len(shipment.route_ids):
                shipment.status = "arrived"
                _begin_unloading(world, shipment)
        if shipment.status == "unloading" and remaining > 1e-9:
            step = min(remaining, shipment.unloading_remaining_hours)
            shipment.unloading_remaining_hours -= step
            destination.handling_hours += step
            if shipment.unloading_remaining_hours <= 1e-9:
                destination.completed_operations += 1
                _settle_arrival(world, shipment)
                if shipment.status == "delivered":
                    settled.append(shipment.contract_id)
                destination = world.transport_facilities[shipment.destination_facility_id or ""]
                _remove_active(destination, shipment.id)
        if asset.accrued_operating_cost > 0:
            world.record(
                "transport_cost_accrued",
                f"{asset.id} accrued operating cost",
                actors=[asset.owner_id],
                entities=[asset.id, shipment.id],
                data={"amount": asset.accrued_operating_cost, "outstanding": asset.operating_cost_due},
            )
            settle_operating_cost(world, asset.id)
    _admit_arrivals(world)
    return settled


def resolve_failed_cargo(world: World, shipment_id: str) -> bool:
    """Recover failed cargo only when the carrier is physically at the seller."""
    shipment = world.shipments[shipment_id]
    if shipment.status != "failed" or shipment.carrier_id is None:
        raise ValueError("only failed carrier shipments can be recovered")
    contract = world.contracts[shipment.contract_id]
    asset = world.transport_assets[shipment.carrier_id]
    seller = world.businesses[contract.seller_id]
    quantity = world.quantity_held(asset.id, contract.good_type_id)
    if quantity + 1e-9 < contract.quantity:
        raise ValueError("failed cargo is not present on carrier")
    if asset.assignment_kind == "cargo_recovery":
        return False
    mid_route = shipment.current_route_index < len(shipment.route_ids) and shipment.elapsed_hours > 1e-9
    if asset.location_id != seller.location_id or mid_route:
        return _begin_cargo_recovery(world, shipment, asset, seller.location_id)
    world.transfer_goods(
        contract.good_type_id,
        contract.quantity,
        from_holder=asset.id,
        to_holder=seller.id,
        to_owner=seller.id,
        causes=contract.causal_event_ids[-1:],
        reason=f"{contract.id} failed cargo recovered",
    )
    asset.cargo_clearance_pending = _asset_load(world, asset.id) > 1e-9
    release_asset(world, asset.id)
    world.record("failed_cargo_recovered", f"{contract.id} cargo recovered by seller", entities=[contract.id, shipment.id, asset.id])
    return True


def advance_freight(world: World, hours: float = 1.0, *, preserve_runtime_exclusions: bool = False) -> list[str]:
    """Advance freight on a shared facility timeline without changing time."""
    require_finite(hours, "freight time")
    if hours < 0:
        raise ValueError("freight time cannot move backwards")
    world.runtime.pop("_freight_advanced_assets", None)
    settled: list[str] = []
    remaining = float(hours)
    while remaining > 1e-9:
        step = min(1.0, remaining)
        settled.extend(_advance_freight_step(world, step))
        remaining -= step
    if not preserve_runtime_exclusions:
        world.runtime.pop("_freight_advanced_assets", None)
    return settled
