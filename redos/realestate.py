"""Small Baron-derived real-estate mechanics on the canonical world."""

from __future__ import annotations

from datetime import timedelta

from .model import Property, World, require_finite


def add_property(world: World, property: Property) -> Property:
    if property.place_id not in world.places:
        raise KeyError(property.place_id)
    require_finite(property.market_value, "property market value")
    require_finite(property.monthly_rent, "property monthly rent")
    if property.market_value <= 0 or property.monthly_rent < 0:
        raise ValueError("property value must be positive and rent non-negative")
    if property.owner_id not in world.actors and property.owner_id not in world.businesses and property.owner_id not in world.households:
        raise KeyError(property.owner_id)
    if not property.value_history:
        property.value_history.append((world.now, property.market_value))
    world.add(property)
    world.record("property_registered", f"{property.id} entered the property market", entities=[property.id, property.place_id])
    return property


def update_property_market(world: World, property_id: str, factor: float, *, reason: str) -> float:
    require_finite(factor, "property market factor")
    if factor <= 0:
        raise ValueError("property market factor must be positive")
    property = world.properties[property_id]
    before = property.market_value
    projected = before * factor
    require_finite(projected, "property market value")
    property.market_value = projected
    property.value_history.append((world.now, property.market_value))
    world.record(
        "property_market_update",
        f"{property.id} value changed because {reason}",
        entities=[property.id, property.place_id],
        data={"factor": factor, "before": before, "after": property.market_value, "reason": reason},
    )
    return property.market_value


def buy_property(world: World, property_id: str, buyer_id: str, seller_id: str, *, price: float | None = None) -> float:
    property = world.properties[property_id]
    if property.owner_id != seller_id:
        raise ValueError("seller does not own property")
    amount = property.market_value if price is None else price
    require_finite(amount, "property price")
    if amount <= 0:
        raise ValueError("property price must be positive")
    payment = world.pay(buyer_id, seller_id, amount, reason=f"{property.id} purchase")
    former_tenant = property.occupied_by_id
    property.owner_id = buyer_id
    if former_tenant == buyer_id:
        property.occupied_by_id = None
        property.last_rent_at = None
    world.record(
        "property_transferred",
        f"{buyer_id} bought {property.id}",
        actors=[buyer_id, seller_id],
        entities=[property.id],
        causes=(payment.id,),
        data={"price": amount},
    )
    if former_tenant == buyer_id:
        world.record(
            "lease_terminated_by_sale",
            f"{property.id} lease ended when ownership changed",
            actors=[former_tenant, buyer_id, seller_id],
            entities=[property.id],
            causes=(payment.id,),
        )
    return amount


def lease_property(world: World, property_id: str, tenant_id: str) -> None:
    property = world.properties[property_id]
    if tenant_id not in world.actors and tenant_id not in world.businesses and tenant_id not in world.households:
        raise KeyError(tenant_id)
    if tenant_id == property.owner_id:
        raise ValueError("owner cannot lease property to itself")
    if property.occupied_by_id == tenant_id:
        # Re-registering the same active lease is an idempotent administrative
        # operation.  In particular, it must not erase the timestamp that
        # protects the current rental period from duplicate collection.
        world.record(
            "lease_unchanged",
            f"{property.id} is already leased to {tenant_id}",
            actors=[tenant_id, property.owner_id],
            entities=[property.id],
        )
        return
    previous_tenant = property.occupied_by_id
    if previous_tenant is not None:
        world.record(
            "lease_terminated",
            f"{property.id} lease to {previous_tenant} ended before reassignment",
            actors=[previous_tenant, property.owner_id, tenant_id],
            entities=[property.id],
            data={"previous_tenant": previous_tenant, "new_tenant": tenant_id},
        )
    property.occupied_by_id = tenant_id
    property.last_rent_at = None
    world.record("property_leased", f"{property.id} leased to {tenant_id}", actors=[tenant_id, property.owner_id], entities=[property.id])


def collect_rent(world: World, property_id: str) -> float:
    property = world.properties[property_id]
    if property.occupied_by_id is None:
        raise ValueError("property is not occupied")
    if property.monthly_rent <= 0:
        return 0.0
    if property.last_rent_at is not None and world.now < property.last_rent_at + timedelta(days=30):
        raise ValueError("rent is not due for this rental period")
    payment = world.pay(
        property.occupied_by_id,
        property.owner_id,
        property.monthly_rent,
        reason=f"{property.id} rent",
    )
    world.record(
        "rent_paid",
        f"{property.occupied_by_id} paid rent for {property.id}",
        actors=[property.occupied_by_id, property.owner_id],
        entities=[property.id],
        causes=(payment.id,),
        data={"amount": property.monthly_rent},
    )
    property.last_rent_at = world.now
    return property.monthly_rent


def advance_rents(world: World) -> None:
    """Collect due rent and carry unpaid periods as retryable obligations.

    Rent arrears are not silently re-created as fresh debt on every retry.
    Each missed period has one persistent obligation, and a later payment can
    settle current rent plus open arrears in one canonical transfer.
    """
    attempted = world.runtime.setdefault("_rent_attempts", set())
    obligations = world.runtime.setdefault("_rent_obligations", {})
    for property in world.properties.values():
        if property.occupied_by_id is None or property.monthly_rent <= 0:
            continue
        if property.last_rent_at is not None and world.now < property.last_rent_at + timedelta(days=30):
            continue
        period = (property.id, world.now.year, world.now.month)
        if period in attempted:
            continue
        attempted.add(period)
        occupant_id = property.occupied_by_id
        occupant = world.actors.get(occupant_id) or world.businesses.get(occupant_id) or world.households.get(occupant_id)
        if occupant is None:
            continue
        open_arrears = [
            obligation
            for obligation in obligations.values()
            if obligation["property_id"] == property.id
            and obligation["tenant_id"] == occupant_id
            and obligation["status"] == "open"
        ]
        arrears_amount = sum(float(obligation["amount"]) for obligation in open_arrears)
        current_amount = property.monthly_rent
        try:
            # Prefer settling the current period and all outstanding arrears
            # together.  This makes the debt lifecycle explicit and avoids
            # inventing a separate financial authority for rent collection.
            if getattr(occupant, "cash", getattr(occupant, "money", 0.0)) + 1e-9 >= current_amount + arrears_amount:
                payment = world.pay(
                    occupant_id,
                    property.owner_id,
                    current_amount + arrears_amount,
                    reason=f"{property.id} rent and arrears",
                )
                world.record(
                    "rent_paid",
                    f"{occupant_id} paid rent for {property.id}",
                    actors=[occupant_id, property.owner_id],
                    entities=[property.id],
                    causes=(payment.id,),
                    data={"amount": current_amount, "arrears": arrears_amount},
                )
                for obligation in open_arrears:
                    obligation["status"] = "settled"
                    obligation["settled_at"] = world.now.isoformat()
                    world.record(
                        "rent_arrears_settled",
                        f"{occupant_id} settled rent arrears for {property.id}",
                        actors=[occupant_id, property.owner_id],
                        entities=[property.id],
                        causes=(payment.id,),
                        data={"amount": obligation["amount"], "period": obligation["period"]},
                    )
                if arrears_amount > 0:
                    occupant.debt = max(0.0, occupant.debt - arrears_amount)
                property.last_rent_at = world.now
                continue
            # If the tenant can cover only the current period, do not make a
            # successful current payment disappear behind old arrears.
            collect_rent(world, property.id)
            if open_arrears:
                world.record(
                    "rent_arrears_deferred",
                    f"{occupant_id} deferred arrears for {property.id}",
                    actors=[occupant_id, property.owner_id],
                    entities=[property.id],
                    data={"amount": arrears_amount},
                )
        except (KeyError, ValueError) as exc:
            key = f"{property.id}:{occupant_id}:{property.last_rent_at.isoformat() if property.last_rent_at else period}"
            obligation = obligations.setdefault(
                key,
                {
                    "property_id": property.id,
                    "tenant_id": occupant_id,
                    "landlord_id": property.owner_id,
                    "period": period,
                    "amount": current_amount,
                    "status": "open",
                    "attempts": 0,
                    "last_reason": None,
                },
            )
            obligation["attempts"] = int(obligation.get("attempts", 0)) + 1
            reason = str(exc)
            if obligation.get("last_reason") != reason:
                obligation["last_reason"] = reason
                occupant.debt += current_amount
                world.record(
                    "rent_unpaid",
                    f"{occupant_id} could not pay rent for {property.id}",
                    actors=[occupant_id, property.owner_id],
                    entities=[property.id],
                    data={"amount": current_amount, "reason": reason, "obligation": key},
                )
            property.last_rent_at = world.now
