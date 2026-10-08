"""Persistent freight carriers and facility handling for the harbor slice.

This is the first Ports of Call kernel: a charter is assigned to a persistent
carrier, cargo is loaded at a facility, the carrier travels on canonical
routes, and unloading/settlement occur only after physical arrival.
"""

from __future__ import annotations

from .enterprise import allocate_contract
from .model import Shipment, TransportAsset, TransportFacility, World
from .simulation import route_path


def add_asset(world: World, asset: TransportAsset) -> TransportAsset:
    if asset.capacity <= 0:
        raise ValueError("transport capacity must be positive")
    if not 0 <= asset.condition <= 1:
        raise ValueError("transport condition must be between zero and one")
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


def dispatch_freight(
    world: World,
    contract_id: str,
    *,
    carrier_id: str,
    origin_facility_id: str,
    destination_facility_id: str,
    loading_hours: float = 1.0,
    unloading_hours: float = 1.0,
) -> Shipment:
    """Create a queued physical freight journey without moving the clock."""
    if loading_hours <= 0 or unloading_hours <= 0:
        raise ValueError("handling times must be positive")
    contract = world.contracts[contract_id]
    if contract.status == "open":
        allocate_contract(world, contract_id)
    if contract.status != "allocated":
        raise ValueError(f"contract {contract_id} is not allocated")
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
    path = route_path(world, contract.origin_id, contract.destination_id)
    if not path:
        raise ValueError("contract has no physical route")
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
    )
    world.add(shipment)
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


def _settle_arrival(world: World, shipment: Shipment) -> None:
    contract = world.contracts[shipment.contract_id]
    asset = world.transport_assets[shipment.carrier_id or ""]
    buyer = world.businesses[contract.buyer_id]
    seller = world.businesses[contract.seller_id]
    try:
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
        payment = world.pay(
            buyer.id,
            seller.id,
            contract.quantity * contract.unit_price,
            causes=[delivered.id],
            reason=f"{contract.id} freight settlement",
        )
    except (KeyError, ValueError) as exc:
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
    asset.assigned_shipment_id = None
    asset.available = True


def advance_freight(world: World, hours: float = 1.0) -> list[str]:
    """Advance queued/loading/sailing/unloading freight without changing time."""
    if hours < 0:
        raise ValueError("freight time cannot move backwards")
    _admit_arrivals(world)
    settled: list[str] = []
    for shipment in list(world.shipments.values()):
        if shipment.carrier_id is None or shipment.status in {"delivered", "failed"}:
            continue
        asset = world.transport_assets[shipment.carrier_id]
        origin = world.transport_facilities[shipment.origin_facility_id or ""]
        remaining = float(hours)
        if shipment.status == "queued":
            if len(origin.active_shipments) >= origin.handling_capacity:
                continue
            origin.queue.remove(shipment.id)
            origin.active_shipments.append(shipment.id)
            shipment.status = "loading"
            asset.assigned_shipment_id = shipment.id
            asset.available = False
            world.record("loading_started", f"{shipment.id} began loading at {origin.id}", entities=[shipment.id, origin.id])
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
                duration = max(1.0, route.travel_days * 24.0)
                available = duration - shipment.elapsed_hours
                step = min(remaining, available)
                if asset.fuel_capacity > 0:
                    fuel = asset.fuel_burn_per_hour * step
                    if asset.fuel + 1e-9 < fuel:
                        _fail(world, shipment, "carrier fuel exhausted")
                        break
                    asset.fuel -= fuel
                asset.accrued_operating_cost += asset.operating_cost_per_hour * step
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
                data={"amount": asset.accrued_operating_cost},
            )
            asset.accrued_operating_cost = 0.0
    _admit_arrivals(world)
    return settled
