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
    property.market_value *= factor
    require_finite(property.market_value, "property market value")
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
    property.owner_id = buyer_id
    world.record(
        "property_transferred",
        f"{buyer_id} bought {property.id}",
        actors=[buyer_id, seller_id],
        entities=[property.id],
        causes=(payment.id,),
        data={"price": amount},
    )
    return amount


def lease_property(world: World, property_id: str, tenant_id: str) -> None:
    property = world.properties[property_id]
    if tenant_id not in world.actors and tenant_id not in world.businesses and tenant_id not in world.households:
        raise KeyError(tenant_id)
    if tenant_id == property.owner_id:
        raise ValueError("owner cannot lease property to itself")
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
