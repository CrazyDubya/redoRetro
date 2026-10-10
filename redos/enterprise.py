"""Market, Cartels & Cutthroats, INTOPIA, and M.U.L.E. kernels."""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import Business, Contract, Shipment, World, require_finite
from .simulation import route_path


def business_quote(world: World, business_id: str, market_id: str, good_type_id: str) -> float:
    business = world.businesses[business_id]
    market = world.markets[market_id]
    reference = market.fixed_prices[good_type_id]
    markup = business.price_markup.get(good_type_id, 0.0)
    advertising_effect = min(0.15, max(0.0, business.advertising) * 0.01)
    return round(reference * (1.0 + markup - advertising_effect), 2)


def compete(world: World, market_id: str, good_type_id: str) -> dict[str, float]:
    """Compute observable market share from actual offers and inventory."""
    market = world.markets[market_id]
    def stock_for(business: Business) -> float:
        held = world.quantity_held(business.id, good_type_id)
        place_owned = sum(
            lot.quantity for lot in world.lots.values()
            if lot.holder_id == market.place_id and lot.owner_id == business.id and lot.good_type_id == good_type_id
        )
        return held + place_owned

    businesses = [business for business in world.businesses.values() if business.location_id == market.place_id and stock_for(business) > 0]
    if not businesses:
        return {}
    weights = {}
    for business in businesses:
        price = business_quote(world, business.id, market_id, good_type_id)
        weights[business.id] = stock_for(business) / max(price, 0.01)
    total = sum(weights.values())
    shares = {business_id: weight / total for business_id, weight in weights.items()}
    for business_id, share in shares.items():
        world.businesses[business_id].market_share[good_type_id] = share
    world.record("competition", f"firms competed for {good_type_id}", entities=[market_id, good_type_id], data={"shares": shares})
    return shares


def create_contract(
    world: World,
    seller_id: str,
    buyer_id: str,
    good_type_id: str,
    quantity: float,
    unit_price: float,
    *,
    origin_id: str,
    destination_id: str,
    due_days: int,
) -> Contract:
    require_finite(quantity, "contract quantity")
    require_finite(unit_price, "contract unit price")
    require_finite(due_days, "contract due days")
    if seller_id == buyer_id:
        raise ValueError("contract parties must be distinct")
    if quantity <= 0 or unit_price <= 0 or due_days < 0:
        raise ValueError("invalid contract terms")
    world._event_number += 1
    due_at = world.now + timedelta(days=due_days)
    contract = Contract(
        id=f"contract-{world._event_number}",
        seller_id=seller_id,
        buyer_id=buyer_id,
        good_type_id=good_type_id,
        quantity=quantity,
        unit_price=unit_price,
        origin_id=origin_id,
        destination_id=destination_id,
        due_day=(due_at - datetime(1770, 1, 1)).days,
        due_at=due_at,
        signed_at=world.now,
    )
    world.add(contract)
    signed = world.record("contract_signed", f"{seller_id} contracted to supply {buyer_id}", actors=[seller_id, buyer_id], entities=[contract.id, good_type_id])
    contract.causal_event_ids.append(signed.id)
    return contract


def allocate_contract(world: World, contract_id: str) -> Contract:
    contract = world.contracts[contract_id]
    if contract.status != "open":
        raise ValueError("contract is not open")
    seller = world.businesses[contract.seller_id]
    reserved = sum(
        other.quantity for other in world.contracts.values()
        if other.id != contract.id
        and other.seller_id == seller.id
        and other.good_type_id == contract.good_type_id
        and other.status in {"allocated", "in_transit"}
    )
    if world.quantity_held(seller.id, contract.good_type_id) - reserved + 1e-9 < contract.quantity:
        contract.status = "failed"
        contract.failure_reason = "goods unavailable at allocation"
        failed = world.record("contract_failed", f"{contract.id} could not allocate goods", actors=[seller.id], entities=[contract.id], data={"reason": contract.failure_reason})
        contract.causal_event_ids.append(failed.id)
        return contract
    contract.status = "allocated"
    contract.allocated_at = world.now
    allocated = world.record("contract_allocated", f"{contract.id} allocated physical goods", actors=[seller.id, contract.buyer_id], entities=[contract.id, contract.good_type_id])
    contract.causal_event_ids.append(allocated.id)
    return contract


def dispatch_contract(world: World, contract_id: str) -> Contract:
    contract = world.contracts[contract_id]
    if contract.shipment_id is not None or contract.status not in {"open", "allocated"}:
        raise ValueError(f"contract {contract_id} is already dispatched or not dispatchable")
    if contract.status == "open":
        allocate_contract(world, contract_id)
    if contract.status != "allocated":
        raise ValueError(f"contract {contract_id} is not allocated")
    path = route_path(world, contract.origin_id, contract.destination_id)
    if not path:
        raise ValueError("contract has no physical route")
    shipment = Shipment(
        id=f"shipment-{len(world.shipments) + 1}",
        contract_id=contract.id,
        origin_id=contract.origin_id,
        destination_id=contract.destination_id,
        route_ids=tuple(route.id for route in path),
    )
    world.add(shipment)
    world.transfer_goods(
        contract.good_type_id,
        contract.quantity,
        from_holder=contract.seller_id,
        to_holder=shipment.id,
        to_owner=contract.seller_id,
        reason=f"{contract.id} goods dispatched",
    )
    shipment.cargo_lot_ids = [lot.id for lot in world.lots_held_by(shipment.id, contract.good_type_id)]
    contract.shipment_id = shipment.id
    contract.status = "in_transit"
    contract.dispatched_at = world.now
    dispatched = world.record("contract_dispatched", f"{contract.id} dispatched through the world", actors=[contract.seller_id], entities=[contract.id, shipment.id], causes=contract.causal_event_ids[-1:])
    contract.causal_event_ids.append(dispatched.id)
    return contract


def advance_shipments(world: World, hours: float = 1.0) -> list[str]:
    """Move contract cargo along routes without changing the global clock."""
    if hours < 0:
        raise ValueError("shipment time cannot move backwards")
    # Carrier-backed shipments are owned by the Ports of Call transport
    # authority.  The runtime enters through this function, so a shipment
    # cannot be advanced once by the legacy holder-on-shipment engine and once
    # by the carrier engine.
    delivered: list[str] = []
    if (
        any(shipment.carrier_id is not None and shipment.status not in {"delivered", "failed"} for shipment in world.shipments.values())
        or any(asset.assignment_kind in {"reposition", "cargo_recovery"} for asset in world.transport_assets.values())
    ):
        from .transport import advance_freight

        delivered.extend(advance_freight(world, hours))
    for shipment in list(world.shipments.values()):
        if shipment.carrier_id is not None:
            continue
        if shipment.status not in {"dispatched", "in_transit", "returning"}:
            continue
        remaining = hours
        while remaining > 0 and shipment.current_route_index < len(shipment.route_ids):
            route = world.routes[shipment.route_ids[shipment.current_route_index]]
            duration = max(1.0, route.travel_days * 24.0)
            available = duration - shipment.elapsed_hours
            step = min(remaining, available)
            shipment.elapsed_hours += step
            remaining -= step
            if shipment.elapsed_hours + 1e-9 < duration:
                break
            shipment.current_route_index += 1
            shipment.elapsed_hours = 0.0
        if shipment.current_route_index < len(shipment.route_ids):
            # Preserve a failed shipment's return state while it is still
            # travelling back to the seller.  Reclassifying it as ordinary
            # transit here would make the next arrival attempt delivery
            # again, producing an endless return/failure cycle.
            if shipment.status != "returning":
                shipment.status = "in_transit"
            continue
        contract = world.contracts[shipment.contract_id]
        if shipment.status == "returning":
            seller = world.businesses[contract.seller_id]
            world.transfer_goods(
                contract.good_type_id,
                contract.quantity,
                from_holder=shipment.id,
                to_holder=seller.id,
                to_owner=seller.id,
                reason=f"{contract.id} cargo returned after failed settlement",
            )
            shipment.status = "returned"
            returned = world.record(
                "cargo_returned",
                f"{contract.id} cargo physically returned to seller",
                actors=[seller.id],
                entities=[contract.id, shipment.id],
                causes=contract.causal_event_ids[-1:],
            )
            contract.causal_event_ids.append(returned.id)
            continue
        if contract.due_at is not None and world.now > contract.due_at and not contract.late_reported:
            late = world.record("contract_late", f"{contract.id} missed its delivery deadline", actors=[contract.seller_id, contract.buyer_id], entities=[contract.id, shipment.id], causes=contract.causal_event_ids[-1:], data={"due_at": contract.due_at.isoformat(), "arrived_at": world.now.isoformat()})
            contract.causal_event_ids.append(late.id)
            contract.late_reported = True
        buyer = world.businesses[contract.buyer_id]
        seller = world.businesses[contract.seller_id]
        total = contract.quantity * contract.unit_price
        if buyer.cash + 1e-9 < total:
            contract.status = "failed"
            contract.failure_reason = "buyer insolvent at delivery"
            failed = world.record("contract_failed", f"{contract.id} failed at delivery", actors=[buyer.id, seller.id], entities=[contract.id, shipment.id], causes=contract.causal_event_ids[-1:], data={"reason": contract.failure_reason})
            contract.causal_event_ids.append(failed.id)
            return_path = route_path(world, contract.destination_id, seller.location_id)
            if seller.location_id == contract.destination_id:
                world.transfer_goods(
                    contract.good_type_id,
                    contract.quantity,
                    from_holder=shipment.id,
                    to_holder=seller.id,
                    to_owner=seller.id,
                    reason=f"{contract.id} cargo returned to co-located seller",
                )
                shipment.destination_id = seller.location_id
                shipment.status = "returned"
                world.record("cargo_returned", f"{contract.id} cargo returned to co-located seller", actors=[seller.id], entities=[contract.id, shipment.id], causes=[failed.id])
            elif return_path:
                shipment.origin_id = contract.destination_id
                shipment.destination_id = seller.location_id
                shipment.route_ids = tuple(route.id for route in return_path)
                shipment.current_route_index = 0
                shipment.elapsed_hours = 0.0
                shipment.status = "returning"
                world.record("cargo_return_started", f"{contract.id} cargo began its physical return", actors=[seller.id], entities=[contract.id, shipment.id], causes=[failed.id])
            else:
                shipment.origin_id = contract.destination_id
                shipment.destination_id = contract.destination_id
                shipment.status = "lost"
                world.record("cargo_lost", f"{contract.id} cargo could not return to seller", actors=[seller.id], entities=[contract.id, shipment.id], causes=[failed.id])
            continue
        if buyer.cash + 1e-9 < total:
            raise ValueError(f"{buyer.id} cannot pay {total}")
        if world.quantity_held(shipment.id, contract.good_type_id) + 1e-9 < contract.quantity:
            raise ValueError(f"{shipment.id} does not hold the contracted cargo")
        payment = world.pay(buyer.id, seller.id, total, causes=contract.causal_event_ids[-1:], reason=f"{contract.id} settlement")
        delivery_holder = buyer.location_id if buyer.kind in {"market", "shop"} else buyer.id
        try:
            world.transfer_goods(contract.good_type_id, contract.quantity, from_holder=shipment.id, to_holder=delivery_holder, to_owner=buyer.id, causes=[payment.id], reason=f"{contract.id} goods delivered")
        except (KeyError, ValueError):
            world.pay(seller.id, buyer.id, total, reason=f"reverse failed {contract.id} settlement")
            raise
        if buyer.kind == "market":
            from .market import accept_market_delivery

            market_id = next((market.id for market in world.markets.values() if market.place_id == buyer.location_id), None)
            if market_id is not None:
                accept_market_delivery(world, market_id, contract.good_type_id, contract.quantity, causes=contract.causal_event_ids[-1:])
        shipment.status = "delivered"
        contract.status = "delivered"
        contract.delivered_at = world.now
        delivered_event = world.record("contract_delivered", f"{contract.id} delivered physical goods", actors=[buyer.id, seller.id], entities=[contract.id, shipment.id], causes=[payment.id])
        contract.causal_event_ids.append(delivered_event.id)
        contract.status = "settled"
        settled = world.record("contract_settled", f"{contract.id} settled", actors=[seller.id, buyer.id], entities=[contract.id], causes=[payment.id])
        contract.causal_event_ids.append(settled.id)
        delivered.append(contract.id)
    return delivered


def settle_contract(world: World, contract_id: str) -> None:
    contract = world.contracts[contract_id]
    if contract.status != "delivered":
        raise ValueError(f"contract {contract_id} has not physically delivered")
    buyer = world.businesses[contract.buyer_id]
    seller = world.businesses[contract.seller_id]
    payment = world.pay(buyer.id, seller.id, contract.quantity * contract.unit_price, causes=contract.causal_event_ids[-1:], reason=f"{contract.id} settlement")
    contract.status = "settled"
    settled = world.record("contract_settled", f"{contract.id} settled", actors=[seller.id, buyer.id], entities=[contract.id], causes=[payment.id])
    contract.causal_event_ids.append(settled.id)


def borrow(world: World, borrower_id: str, lender_id: str, amount: float) -> None:
    if amount <= 0:
        raise ValueError("loan must be positive")
    world.pay(lender_id, borrower_id, amount, reason="business loan")
    world.businesses[borrower_id].debt += amount
    world.record("loan", f"{borrower_id} borrowed from {lender_id}", actors=[borrower_id, lender_id], data={"amount": amount})


def repay(world: World, borrower_id: str, lender_id: str, amount: float) -> None:
    borrower = world.businesses[borrower_id]
    amount = min(amount, borrower.debt)
    if amount <= 0:
        return
    world.pay(borrower_id, lender_id, amount, reason="business loan repayment")
    borrower.debt -= amount
    world.record("loan_repayment", f"{borrower_id} repaid {lender_id}", actors=[borrower_id, lender_id], data={"amount": amount})


def invest_in_research(world: World, business_id: str, amount: float) -> None:
    if amount <= 0:
        raise ValueError("research investment must be positive")
    business = world.businesses[business_id]
    if business.cash < amount:
        raise ValueError("business cannot fund research")
    business.cash -= amount
    business.research += amount
    world.record("research", f"{business_id} invested in research", actors=[business_id], data={"amount": amount})


def invest_in_capacity(world: World, business_id: str, recipe_id: str, amount: float, capacity_gain: float = 1.0) -> float:
    """Convert a business cash outlay into usable recipe capacity."""
    if amount <= 0 or capacity_gain <= 0:
        raise ValueError("capacity investment and gain must be positive")
    business = world.businesses[business_id]
    if business.cash + 1e-9 < amount:
        raise ValueError("business cannot fund capacity investment")
    business.cash -= amount
    business.capital += amount
    business.production_capacity[recipe_id] = business.production_capacity.get(recipe_id, 1.0) + capacity_gain
    event = world.record(
        "capacity_investment",
        f"{business_id} invested in {recipe_id} capacity",
        actors=[business_id],
        entities=[recipe_id],
        data={"amount": amount, "capacity_gain": capacity_gain, "capacity": business.production_capacity[recipe_id]},
    )
    return event.id


def mule_bid(world: World, buyer_id: str, seller_id: str, good_type_id: str, quantity: float, amount: float) -> None:
    """A scarcity bid: a buyer pays a seller for an actual lot."""
    if amount <= 0:
        raise ValueError("bid must be positive")
    if world.quantity_held(seller_id, good_type_id) + 1e-9 < quantity:
        raise ValueError("seller cannot fulfill scarcity bid")
    world.pay(buyer_id, seller_id, amount, reason="scarcity auction bid")
    world.transfer_goods(good_type_id, quantity, from_holder=seller_id, to_holder=buyer_id, to_owner=buyer_id, reason="scarcity auction delivery")
    world.record("scarcity_auction", f"{buyer_id} acquired scarce {good_type_id}", actors=[buyer_id, seller_id], entities=[good_type_id], data={"quantity": quantity, "amount": amount})
