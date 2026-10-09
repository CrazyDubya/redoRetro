"""Persistent freight carriers and facility handling for the harbor slice.

This is the first Ports of Call kernel: a charter is assigned to a persistent
carrier, cargo is loaded at a facility, the carrier travels on canonical
routes, and unloading/settlement occur only after physical arrival.
"""

from __future__ import annotations

from .enterprise import allocate_contract
from .model import Movement, Shipment, TransportAsset, TransportFacility, World
from .simulation import effective_route_hours, route_is_accessible, route_path


PACE_MULTIPLIERS = {
    "slow": 1.25,
    "steady": 1.0,
    "urgent": 0.85,
}


def add_asset(world: World, asset: TransportAsset) -> TransportAsset:
    if asset.capacity <= 0:
        raise ValueError("transport capacity must be positive")
    if not 0 <= asset.condition <= 1:
        raise ValueError("transport condition must be between zero and one")
    if not 0 <= asset.readiness <= 1:
        raise ValueError("transport readiness must be between zero and one")
    for supply, quantity in asset.supplies.items():
        if quantity < 0 or quantity > asset.supply_capacity.get(supply, quantity) + 1e-9:
            raise ValueError(f"invalid starting supply for {supply}")
    world.add(asset)
    return asset


def add_facility(world: World, facility: TransportFacility) -> TransportFacility:
    if facility.handling_capacity <= 0:
        raise ValueError("facility handling capacity must be positive")
    if facility.place_id not in world.places:
        raise KeyError(facility.place_id)
    world.add(facility)
    return facility


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
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {asset_id} is unavailable")
    if asset.reserved_for_shipment_id not in {None, assignment_id}:
        raise ValueError(f"carrier {asset_id} is reserved for another shipment")
    if asset.cargo_clearance_pending or _asset_load(world, asset.id) > 1e-9:
        raise ValueError(f"carrier {asset_id} still holds unresolved cargo")
    if asset.condition <= 0 or asset.readiness <= 0:
        raise ValueError(f"carrier {asset_id} is not operational")
    horse = world.horses.get(asset.id)
    if asset.asset_type == "horse" and horse is not None and horse.injury > 0:
        raise ValueError(f"horse {asset_id} is injured")
    asset.assigned_shipment_id = assignment_id
    asset.assignment_kind = kind
    asset.available = False
    asset.unavailable_reason = None
    world.record("asset_assigned", f"{asset.id} assigned to {assignment_id}", entities=[asset.id, assignment_id], data={"kind": kind})
    return asset


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
    if previous_kind == "freight" and start_reposition and asset.available and not asset.cargo_clearance_pending:
        _begin_reposition(world, asset)
    return asset


def replenish_asset(world: World, asset_id: str, supply: str, quantity: float, *, source_id: str | None = None) -> float:
    """Add fuel or a named operational supply to a persistent asset."""
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
    world.record("asset_replenished", f"{asset.id} received {added} {supply}", entities=[asset.id, *( [source_id] if source_id else [])], data={"supply": supply, "quantity": added})
    return added


def repair_asset(world: World, asset_id: str, amount: float = 1.0) -> float:
    if amount <= 0:
        raise ValueError("repair amount must be positive")
    asset = world.transport_assets[asset_id]
    repaired = min(amount, 1.0 - asset.condition)
    asset.condition += repaired
    if asset.condition > 0 and asset.readiness > 0 and asset.assigned_shipment_id is None:
        asset.available = True
        asset.unavailable_reason = None
    world.record("asset_repaired", f"{asset.id} repaired", entities=[asset.id], data={"amount": repaired})
    return repaired


def consume_asset_supply(world: World, asset_id: str, supply: str, quantity: float, *, causes: tuple[str, ...] = ()) -> bool:
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
) -> Shipment:
    """Create a queued physical freight journey without moving the clock."""
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
    if _asset_load(world, asset.id) + contract.quantity > asset.capacity + 1e-9:
        raise ValueError("carrier capacity exceeded")
    planned_carriers = tuple(carrier_plan or (carrier_id,))
    if not planned_carriers or planned_carriers[0] != carrier_id:
        raise ValueError("carrier plan must begin with the dispatch carrier")
    path = route_path(world, contract.origin_id, contract.destination_id, mode=None if carrier_plan else asset.asset_type)
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
        if plan_index > 0:
            if not planned_asset.available or planned_asset.assigned_shipment_id is not None or planned_asset.reserved_for_shipment_id is not None:
                raise ValueError(f"relay carrier {planned_id} is unavailable")
            if planned_asset.location_id != path[route_offset].origin_id:
                raise ValueError(f"relay carrier {planned_id} is not at its handoff point")
        for route in path[route_offset:route_offset + planned_legs[plan_index]]:
            if not route_is_accessible(world, route, mode=planned_asset.asset_type):
                raise ValueError(f"carrier {planned_id} cannot use route {route.id}")
        route_offset += planned_legs[plan_index]
    if contract.status == "open":
        allocate_contract(world, contract_id)
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
    )
    world.add(shipment)
    # Reserve at assignment time, not when loading eventually begins.
    assign_asset(world, asset.id, shipment.id, kind="freight")
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
    quantity = world.quantity_held(current_asset.id, contract.good_type_id)
    if quantity > next_asset.capacity + 1e-9:
        _fail(world, shipment, f"relay carrier {next_asset.id} capacity exceeded")
        return False
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
    # Releasing the old carrier while it still held cargo marks it as awaiting
    # clearance.  The physical handoff has now completed, so it is safe to
    # make that carrier available for another assignment.
    current_asset.cargo_clearance_pending = _asset_load(world, current_asset.id) > 1e-9
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


def _advance_asset_reposition(world: World, asset: TransportAsset, hours: float) -> None:
    remaining = hours
    while remaining > 1e-9 and asset.assignment_kind == "reposition":
        if asset.return_route_index >= len(asset.return_route_ids):
            asset.location_id = asset.home_location_id or asset.location_id
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
        if asset.fuel_capacity > 0 and not consume_asset_supply(world, asset.id, "fuel", asset.fuel_burn_per_hour * step):
            asset.unavailable_reason = "fuel exhausted during return"
            return
        for supply, burn_rate in asset.supply_burn_per_hour.items():
            if not consume_asset_supply(world, asset.id, supply, burn_rate * step):
                asset.unavailable_reason = f"{supply} exhausted during return"
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
            if asset.operating_cost_payee_id is not None:
                try:
                    world.pay(
                        asset.owner_id,
                        asset.operating_cost_payee_id,
                        asset.operating_cost_due,
                        causes=[cost_event.id],
                        reason=f"{asset.id} repositioning cost",
                    )
                    asset.operating_cost_due = 0.0
                except (KeyError, ValueError):
                    pass
            asset.accrued_operating_cost = 0.0
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
    payment = None
    try:
        payment = world.pay(
            buyer.id,
            seller.id,
            total,
            causes=contract.causal_event_ids[-1:],
            reason=f"{contract.id} freight settlement",
        )
        delivery_holder = buyer.location_id if buyer.kind in {"market", "shop"} else buyer.id
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
        causes=[payment.id],
    )
    contract.causal_event_ids.append(settled.id)
    shipment.status = "delivered"
    _clear_relay_reservations(world, shipment)
    release_asset(world, asset.id)


def _advance_freight_step(world: World, hours: float) -> list[str]:
    """Advance one shared handling/movement interval without changing time."""
    for asset in list(world.transport_assets.values()):
        if asset.assignment_kind == "reposition":
            _advance_asset_reposition(world, asset, hours)
    _admit_arrivals(world)
    _admit_loads(world)
    settled: list[str] = []
    for shipment in list(world.shipments.values()):
        if shipment.carrier_id is None or shipment.status in {"delivered", "failed"}:
            continue
        asset = world.transport_assets[shipment.carrier_id]
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
                if asset.fuel_capacity > 0 and not consume_asset_supply(
                    world,
                    asset.id,
                    "fuel",
                    asset.fuel_burn_per_hour * step,
                    causes=tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:]),
                ):
                    _fail(world, shipment, "carrier fuel exhausted")
                    break
                resource_failure = False
                for supply, burn_rate in asset.supply_burn_per_hour.items():
                    if not consume_asset_supply(world, asset.id, supply, burn_rate * step, causes=tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:])):
                        _fail(world, shipment, f"carrier {supply} exhausted")
                        resource_failure = True
                        break
                if resource_failure:
                    break
                cost = asset.operating_cost_per_hour * step
                asset.accrued_operating_cost += cost
                asset.operating_cost_due += cost
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
            if asset.operating_cost_payee_id is not None and asset.operating_cost_due > 0:
                try:
                    world.pay(
                        asset.owner_id,
                        asset.operating_cost_payee_id,
                        asset.operating_cost_due,
                        reason=f"{asset.id} operating cost",
                    )
                    asset.operating_cost_due = 0.0
                except (KeyError, ValueError):
                    pass
            asset.accrued_operating_cost = 0.0
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
    if asset.location_id != seller.location_id:
        raise ValueError("carrier must be physically co-located with seller")
    quantity = world.quantity_held(asset.id, contract.good_type_id)
    if quantity + 1e-9 < contract.quantity:
        raise ValueError("failed cargo is not present on carrier")
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


def advance_freight(world: World, hours: float = 1.0) -> list[str]:
    """Advance freight on a shared facility timeline without changing time."""
    if hours < 0:
        raise ValueError("freight time cannot move backwards")
    settled: list[str] = []
    remaining = float(hours)
    while remaining > 1e-9:
        step = min(1.0, remaining)
        settled.extend(_advance_freight_step(world, step))
        remaining -= step
    return settled
