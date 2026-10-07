"""Star Trader-derived places, goods, markets, travel, and bargaining."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import Actor, GoodType, Market, Place, Route, World


# The original BASIC game names these UR, MET, HE, MED, SOFT, and GEMS.  Its
# setup module uses a three-class production model and the main module updates
# stocks/prices from production, development, and time since the last visit.
STAR_GOODS = (
    ("uranium", "Uranium", 5000.0, 1.0),
    ("metals", "Metals", 3500.0, 1.0),
    ("equipment", "Heavy equipment", 4000.0, 1.5),
    ("medicine", "Medicine", 4500.0, 0.4),
    ("software", "Computer software", 3000.0, 0.1),
    ("gems", "Star gems", 3000.0, 0.1),
)

# Rows are the recovered BASIC M and C matrices.  The result is the net local
# production/need rate used by the original price refresh routine.
MATRIX_M = (
    (-0.025, -0.050, -0.025),
    (0.000, -0.025, -0.025),
    (0.000, 0.100, 0.100),
    (-0.025, 0.100, 0.000),
    (0.100, 0.200, 0.100),
    (0.100, -0.025, 0.000),
)
MATRIX_C = (
    (1.0, 1.5, 0.5),
    (0.75, 0.75, 0.75),
    (-0.25, -0.25, -0.25),
    (0.0, -0.5, 0.5),
    (0.0, -0.5, 0.0),
    (0.5, 1.5, 0.0),
)


@dataclass(frozen=True)
class TradeQuote:
    market_id: str
    good_type_id: str
    quantity: float
    unit_price: float
    side: str

    @property
    def total(self) -> float:
        return self.quantity * self.unit_price


def install_star_goods(world: World) -> None:
    for good_id, name, base_price, weight in STAR_GOODS:
        world.add(GoodType(good_id, name, base_price, weight))


def create_star_market(world: World, market_id: str, place_id: str, *, development_level: int | None = None) -> Market:
    if development_level is not None:
        world.places[place_id].development_level = development_level
    level = world.places[place_id].development_level
    market = Market(
        id=market_id,
        place_id=place_id,
        fixed_prices={good_id: base for good_id, _name, base, _weight in STAR_GOODS},
    )
    for index, (good_id, _name, _base, _weight) in enumerate(STAR_GOODS):
        # Star Trader's class I-IV descriptions collapse here to three
        # production classes while retaining its actual rate calculation.
        development_class = min(2, max(0, (level - 1) // 5))
        rate = (1.0 + level / 15.0) * (MATRIX_M[index][development_class] * level + MATRIX_C[index][development_class])
        market.production_rates[good_id] = max(0.0, rate)
        market.demand_rates[good_id] = max(0.0, -rate)
        market.balances[good_id] = rate * 12.0
        market.demand_backlog[good_id] = 0.0
        market.price_history[good_id] = []
    world.add(market)
    seed_market_inventory(world, market.id)
    refresh_market(world, market.id)
    return market


def seed_market_inventory(world: World, market_id: str) -> None:
    market = world.markets[market_id]
    for good_id, balance in market.balances.items():
        if balance > 0 and world.quantity_held(market.place_id, good_id) == 0:
            world.create_lot(good_id, balance, holder_id=market.place_id, owner_id=market.place_id, provenance=(f"production:{market.id}",))


def _market_price(world: World, market: Market, good_type_id: str) -> float:
    base = market.fixed_prices[good_type_id]
    # Physical lots are canonical.  balances is only a published economic
    # measurement retained for reports and never drives stock transfers.
    physical_stock = world.quantity_held(market.place_id, good_type_id)
    balance = physical_stock - market.demand_backlog.get(good_type_id, 0.0)
    rate = abs(market.production_rates.get(good_type_id, 0.0)) + abs(market.demand_rates.get(good_type_id, 0.0))
    # This is the BASIC formula's economic shape: a positive stock balance
    # lowers price and a negative balance raises it, with a bounded margin.
    pressure = max(-0.75, min(1.5, -balance / (max(1.0, rate) * 36.0)))
    development = world.places[market.place_id].development_level
    return round(base * (1.0 + pressure) * (1.0 + 0.04 * max(0, 2 - development // 5)), 2)


def quote(world: World, market_id: str, good_type_id: str, quantity: float, *, side: str) -> TradeQuote:
    if quantity <= 0 or side not in {"buy", "sell"}:
        raise ValueError("quantity must be positive and side must be buy or sell")
    market = world.markets[market_id]
    return TradeQuote(market_id, good_type_id, quantity, _market_price(world, market, good_type_id), side)


def refresh_market(world: World, market_id: str, *, days: int = 1) -> None:
    market = world.markets[market_id]
    if days < 0:
        raise ValueError("days cannot be negative")
    for good_id in market.balances:
        production = market.production_rates.get(good_id, 0.0) * days
        demand = market.demand_rates.get(good_id, 0.0) * days
        market.balances[good_id] = world.quantity_held(market.place_id, good_id)
        market.demand_backlog[good_id] = max(0.0, market.demand_backlog.get(good_id, 0.0) + demand - production)
        market.price_history.setdefault(good_id, []).append(_market_price(world, market, good_id))
    market.last_updated_day += days
    # New production is physical canonical inventory, not an abstract market
    # number.  Demand consumes that stock only when a transaction occurs.
    for good_id, rate in market.production_rates.items():
        if rate > 0:
            quantity = rate * days
            production_event = world.record(
                "market_production",
                f"{market.id} produced {quantity} {good_id}",
                entities=[market.id, good_id],
                data={"quantity": quantity},
            )
            world.create_lot(good_id, quantity, holder_id=market.place_id, owner_id=market.place_id, provenance=(production_event.id,))
            market.balances[good_id] = world.quantity_held(market.place_id, good_id)
    world.record("market_refresh", f"{market.id} refreshed for {days} day(s)", entities=[market_id])


def _money_object(world: World, holder_id: str) -> Actor | object:
    if holder_id in world.actors:
        return world.actors[holder_id]
    if holder_id in world.businesses:
        return world.businesses[holder_id]
    raise KeyError(holder_id)


def _debit_credit(world: World, buyer_id: str, seller_id: str, amount: float, *, causes: Iterable[str]) -> None:
    world.pay(buyer_id, seller_id, amount, causes=causes, reason="market transaction payment")


def buy(world: World, buyer_id: str, market_id: str, good_type_id: str, quantity: float, *, offer: float | None = None) -> TradeQuote:
    market = world.markets[market_id]
    place_id = market.place_id
    if world.location_of(buyer_id) != place_id:
        raise ValueError("buyer must be physically present at the market")
    available = world.quantity_held(place_id, good_type_id)
    if available + 1e-9 < quantity:
        shortfall = quantity - available
        market.demand_backlog[good_type_id] = market.demand_backlog.get(good_type_id, 0.0) + shortfall
        world.record(
            "unmet_demand",
            f"{buyer_id} could not buy {quantity} {good_type_id}",
            actors=[buyer_id],
            entities=[market_id, good_type_id],
            data={"requested": quantity, "available": available, "shortfall": shortfall},
        )
        raise ValueError(f"market shortage: only {available} available")
    target = _market_price(world, market, good_type_id)
    unit_price = offer if offer is not None else target
    if unit_price <= 0 or unit_price > target * 1.25:
        raise ValueError("market rejected the purchase offer")
    quote_obj = TradeQuote(market_id, good_type_id, quantity, unit_price, "buy")
    payment = world.pay(buyer_id, place_id if place_id in world.businesses else _market_cashier(world, place_id), quote_obj.total, reason="purchase at market")
    world.transfer_goods(good_type_id, quantity, from_holder=place_id, to_holder=buyer_id, to_owner=buyer_id, causes=[payment.id], reason="goods bought at market")
    market.balances[good_type_id] = world.quantity_held(place_id, good_type_id)
    world.record("trade", f"{buyer_id} bought {quantity} {good_type_id}", actors=[buyer_id], entities=[market_id, good_type_id], causes=[payment.id], data={"quantity": quantity, "unit_price": unit_price})
    return quote_obj


def _market_cashier(world: World, place_id: str) -> str:
    for business in world.businesses.values():
        if business.location_id == place_id and business.kind in {"market", "shop", "warehouse"}:
            return business.id
    # Place-held money is represented by a synthetic business only when the
    # caller installs one; creating silent money would violate conservation.
    raise ValueError(f"market at {place_id} has no business cashier")


def sell(world: World, seller_id: str, market_id: str, good_type_id: str, quantity: float, *, ask: float | None = None) -> TradeQuote:
    market = world.markets[market_id]
    if world.location_of(seller_id) != market.place_id:
        raise ValueError("seller must be physically present at the market")
    if world.quantity_held(seller_id, good_type_id) + 1e-9 < quantity:
        raise ValueError("seller does not have enough goods")
    target = _market_price(world, market, good_type_id)
    unit_price = ask if ask is not None else target
    if unit_price < target * 0.75:
        raise ValueError("market rejected the sale offer")
    cashier = _market_cashier(world, market.place_id)
    quote_obj = TradeQuote(market_id, good_type_id, quantity, unit_price, "sell")
    payment = world.pay(cashier, seller_id, quote_obj.total, reason="market purchase from seller")
    world.transfer_goods(good_type_id, quantity, from_holder=seller_id, to_holder=market.place_id, to_owner=market.place_id, causes=[payment.id], reason="goods sold into market")
    market.balances[good_type_id] = world.quantity_held(market.place_id, good_type_id)
    world.record("trade", f"{seller_id} sold {quantity} {good_type_id}", actors=[seller_id], entities=[market_id, good_type_id], causes=[payment.id], data={"quantity": quantity, "unit_price": unit_price})
    return quote_obj


def travel(world: World, actor_id: str, destination_id: str) -> int:
    from .simulation import walk

    movement = walk(world, actor_id, destination_id)
    return int(movement.duration_hours // 24) if movement.duration_hours >= 24 else 0


def bargain(target: float, offer: float, *, side: str, round_number: int, max_rounds: int = 3) -> bool:
    """A transparent approximation of Star Trader's bounded bid loop."""
    if side == "buy":
        return offer <= target * (1.0 + 0.08 * round_number) or round_number >= max_rounds and offer <= target * 1.25
    if side == "sell":
        return offer >= target * (1.0 - 0.08 * round_number) or round_number >= max_rounds and offer >= target * 0.75
    raise ValueError(side)


def autonomous_trade(world: World, actor_id: str, origin_market: str, destination: str, good_type_id: str, quantity: float) -> dict[str, float | int]:
    origin = world.markets[origin_market]
    before_money = world.actors[actor_id].money
    buy_quote = buy(world, actor_id, origin_market, good_type_id, quantity)
    days = travel(world, actor_id, destination)
    from .simulation import tick
    while world.actors[actor_id].traveling_to is not None:
        tick(world, 1)
    destination_market = next(market for market in world.markets.values() if market.place_id == destination)
    sell_quote = sell(world, actor_id, destination_market.id, good_type_id, quantity)
    return {
        "travel_days": days,
        "buy_total": buy_quote.total,
        "sell_total": sell_quote.total,
        "profit": world.actors[actor_id].money - before_money,
        "origin_stock": world.quantity_held(origin.place_id, good_type_id),
        "destination_stock": world.quantity_held(destination, good_type_id),
    }
