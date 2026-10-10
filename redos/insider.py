"""Inside Trader securities, information and auditable trade mechanics."""

from __future__ import annotations

import math

from .living import tell
from .model import Business, Security, SecurityHolding, Statement, TradeOrder, World


def _money_holder(world: World, holder_id: str):
    holder = world.actors.get(holder_id) or world.businesses.get(holder_id) or world.households.get(holder_id)
    if holder is None:
        raise KeyError(f"unknown money holder {holder_id!r}")
    return holder


def _holding(world: World, owner_id: str, security_id: str) -> SecurityHolding | None:
    return next(
        (holding for holding in world.security_holdings.values() if holding.owner_id == owner_id and holding.security_id == security_id),
        None,
    )


def issue_security(
    world: World,
    issuer_id: str,
    *,
    security_id: str,
    name: str,
    shares: float,
    initial_price: float,
) -> Security:
    issuer = world.businesses.get(issuer_id)
    if issuer is None:
        raise KeyError(issuer_id)
    if security_id in world.securities:
        raise ValueError(f"security {security_id} already exists")
    if not math.isfinite(shares) or not math.isfinite(initial_price) or shares <= 0 or initial_price <= 0 or not name:
        raise ValueError("invalid security terms")
    security = Security(
        id=security_id,
        name=name,
        issuer_id=issuer_id,
        outstanding_shares=shares,
        price=initial_price,
        price_history=[(world.now, initial_price)],
    )
    world.add(security)
    holding = SecurityHolding(f"holding-{len(world.security_holdings) + 1}", issuer_id, security_id, shares, initial_price)
    world.add(holding)
    world.record(
        "security_issued",
        f"{issuer_id} issued {shares} shares of {security_id}",
        actors=[issuer_id],
        entities=[security_id, holding.id],
        data={"shares": shares, "price": initial_price},
    )
    return security


def execute_trade(
    world: World,
    buyer_id: str,
    seller_id: str,
    security_id: str,
    quantity: float,
    *,
    price: float | None = None,
    order_id: str | None = None,
) -> TradeOrder:
    buyer = _money_holder(world, buyer_id)
    _money_holder(world, seller_id)
    if buyer_id == seller_id:
        raise ValueError("trade requires distinct buyer and seller")
    security = world.securities[security_id]
    trade_price = security.price if price is None else price
    if not math.isfinite(quantity) or not math.isfinite(trade_price) or quantity <= 0 or trade_price <= 0:
        raise ValueError("trade quantity and price must be positive")
    seller_holding = _holding(world, seller_id, security_id)
    if seller_holding is None or seller_holding.quantity + 1e-9 < quantity:
        raise ValueError("seller does not hold enough shares")
    order_id = order_id or f"trade-{len(world.trade_orders) + 1}"
    if order_id in world.trade_orders:
        raise ValueError(f"trade order {order_id} already exists")
    total = quantity * trade_price
    payment = world.pay(buyer_id, seller_id, total, reason=f"purchase of {security_id}")
    buyer_holding = _holding(world, buyer_id, security_id)
    if buyer_holding is None:
        buyer_holding = SecurityHolding(f"holding-{len(world.security_holdings) + 1}", buyer_id, security_id, 0.0, 0.0)
        world.add(buyer_holding)
    before_quantity = buyer_holding.quantity
    buyer_holding.quantity += quantity
    buyer_holding.average_cost = (
        ((before_quantity * buyer_holding.average_cost) + total) / buyer_holding.quantity
        if buyer_holding.quantity > 0 else 0.0
    )
    seller_holding.quantity -= quantity
    security.price = trade_price
    security.price_history.append((world.now, trade_price))
    order = TradeOrder(order_id, buyer_id, security_id, "buy", quantity, trade_price, "filled", world.now)
    world.add(order)
    world.record(
        "security_trade",
        f"{buyer_id} bought {quantity} {security_id} from {seller_id}",
        actors=[buyer_id, seller_id],
        entities=[security_id, order.id, buyer_holding.id, seller_holding.id],
        causes=[payment.id],
        data={"quantity": quantity, "price": trade_price, "total": total},
    )
    return order


def publish_wire_event(world: World, source_id: str, proposition: str, content: str, *, truthful: bool = True) -> str:
    """Record a wire item without silently changing any actor's belief."""
    _money_holder(world, source_id)
    event = world.record(
        "wire_news",
        f"{source_id} published market news about {proposition}",
        actors=[source_id],
        entities=[proposition],
        data={"content": content, "truthful": truthful},
    )
    return event.id


def buy_information(
    world: World,
    buyer_id: str,
    informant_id: str,
    proposition: str,
    content: str,
    *,
    cost: float,
    truthful: bool,
    trust_delta: float = 0.0,
) -> Statement:
    """Pay an actor for a statement; belief and truth remain separate state."""
    if buyer_id not in world.actors or informant_id not in world.actors:
        raise ValueError("paid information requires two people")
    if buyer_id == informant_id:
        raise ValueError("information buyer and informant must be distinct")
    if cost <= 0:
        raise ValueError("information must cost something")
    payment = world.pay(buyer_id, informant_id, cost, reason=f"information about {proposition}")
    statement = tell(
        world,
        informant_id,
        buyer_id,
        proposition,
        content,
        truthful=truthful,
        trust_delta=trust_delta,
    )
    world.record(
        "information_purchased",
        f"{buyer_id} paid {informant_id} for information",
        actors=[buyer_id, informant_id],
        entities=[statement.id, proposition],
        causes=[payment.id],
        data={"cost": cost, "truthful": truthful},
    )
    return statement


def portfolio_value(world: World, owner_id: str) -> float:
    _money_holder(world, owner_id)
    return sum(
        holding.quantity * world.securities[holding.security_id].price
        for holding in world.security_holdings.values()
        if holding.owner_id == owner_id and holding.quantity > 0
    )
