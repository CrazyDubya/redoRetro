"""Persistent freight carriers and facility handling for the harbor slice.

This is the first Ports of Call kernel: a charter is assigned to a persistent
carrier, cargo is loaded at a facility, the carrier travels on canonical
routes, and unloading/settlement occur only after physical arrival.
"""

from __future__ import annotations

from .enterprise import allocate_contract
from .model import Shipment, TransportAsset, TransportFacility, World
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


def _asset_load(world: World, asset_id: str) -> float:
    return sum(lot.quantity for lot in world.lots_held_by(asset_id))


def assign_asset(world: World, asset_id: str, assignment_id: str, *, kind: str) -> TransportAsset:
    """Reserve one persistent asset for exactly one current obligation."""
    asset = world.transport_assets[asset_id]
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {asset_id} is unavailable")
    if asset.condition <= 0 or asset.readiness <= 0:
        raise ValueError(f"carrier {asset_id} is not operational")
    asset.assigned_shipment_id = assignment_id
    asset.assignment_kind = kind
    asset.available = False
    asset.unavailable_reason = None
    world.record("asset_assigned", f"{asset.id} assigned to {assignment_id}", entities=[asset.id, assignment_id], data={"kind": kind})
    return asset


def release_asset(world: World, asset_id: str, *, available: bool = True, reason: str | None = None) -> TransportAsset:
    asset = world.transport_assets[asset_id]
    asset.assigned_shipment_id = None
    asset.assignment_kind = None
    asset.available = available and asset.condition > 0 and asset.readiness > 0
    asset.unavailable_reason = None if asset.available else reason
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
    if added > 0 and asset.condition > 0 and asset.readiness > 0 and asset.assigned_shipment_id is None:
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
) -> Shipment:
    """Create a queued physical freight journey without moving the clock."""
    if loading_hours <= 0 or unloading_hours <= 0:
        raise ValueError("handling times must be positive")
    if pace not in PACE_MULTIPLIERS:
        raise ValueError(f"unknown freight pace {pace!r}")
    contract = world.contracts[contract_id]
    asset = world.transport_assets[carrier_id]
    origin = world.transport_facilities[origin_facility_id]
    destination = world.transport_facilities[destination_facility_id]
    if not asset.available or asset.assigned_shipment_id is not None:
        raise ValueError(f"carrier {carrier_id} is unavailable")
    if asset.location_id != origin.place_id or origin.place_id != contract.origin_id:
        raise ValueError("carrier and origin facility are not at the contract origin")
    if destination.place_id != contract.destination_id:
        raise ValueError("destination facility is not at the contract destination")
    if _asset_load(world, asset.id) + contract.quantity > asset.capacity + 1e-9:
        raise ValueError("carrier capacity exceeded")
    path = route_path(world, contract.origin_id, contract.destination_id, mode=asset.asset_type)
    if not path:
        raise ValueError("contract has no physical route")
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
    )
    world.add(shipment)
    # Reserve at assignment time, not when loading eventually begins.
    assign_asset(world, asset.id, shipment.id, kind="freight")
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
            shipment_id = facility.queue.pop(0)
            shipment = world.shipments[shipment_id]
            if shipment.status != "queued":
                continue
            facility.active_shipments.append(shipment.id)
            shipment.status = "loading"
            world.record("loading_started", f"{shipment.id} began loading at {facility.id}", entities=[shipment.id, facility.id])


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
        world.transfer_goods(
            contract.good_type_id,
            contract.quantity,
            from_holder=asset.id,
            to_holder=buyer.id,
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
    release_asset(world, asset.id)


def _advance_freight_step(world: World, hours: float) -> list[str]:
    """Advance one shared handling/movement interval without changing time."""
    _admit_arrivals(world)
    _admit_loads(world)
    settled: list[str] = []
    for shipment in list(world.shipments.values()):
        if shipment.carrier_id is None or shipment.status in {"delivered", "failed"}:
            continue
        asset = world.transport_assets[shipment.carrier_id]
        origin = world.transport_facilities[shipment.origin_facility_id or ""]
        remaining = float(hours)
        if shipment.delay_remaining_hours > 0:
            step = min(remaining, shipment.delay_remaining_hours)
            shipment.delay_remaining_hours -= step
            remaining -= step
            if remaining <= 1e-9:
                continue
        if shipment.status == "loading":
            step = min(remaining, shipment.loading_remaining_hours)
            shipment.loading_remaining_hours -= step
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
            shipment.status = "in_transit"
            contract.status = "in_transit"
            _remove_active(origin, shipment.id)
            departed = world.record("freight_departed", f"{shipment.id} departed {origin.id}", entities=[shipment.id, asset.id, origin.id], causes=contract.causal_event_ids[-1:])
            contract.causal_event_ids.append(departed.id)
        if shipment.status == "in_transit":
            while remaining > 1e-9 and shipment.current_route_index < len(shipment.route_ids):
                if asset.condition <= 0:
                    _fail(world, shipment, "carrier condition unavailable")
                    break
                route = world.routes[shipment.route_ids[shipment.current_route_index]]
                if not route_is_accessible(world, route, mode=asset.asset_type):
                    if not any(
                        event.kind == "freight_delayed"
                        and shipment.id in event.entities
                        and event.at == world.now
                        for event in world.events
                    ):
                        world.record(
                            "freight_delayed",
                            f"{shipment.id} delayed by route conditions",
                            entities=[shipment.id, asset.id, route.id],
                            causes=tuple(world.contracts[shipment.contract_id].causal_event_ids[-1:]),
                            data={"hazard": world.route_conditions.get(route.id).hazard if route.id in world.route_conditions else None},
                        )
                    break
                duration = effective_route_hours(world, route, mode=asset.asset_type) * PACE_MULTIPLIERS[shipment.pace]
                available = duration - shipment.elapsed_hours
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
