"""Merchant Prince-derived multi-port trade-route planning."""

from __future__ import annotations

from dataclasses import dataclass

from .ocean import OceanTradeQuote, select_ocean_trade
from .model import World
from .transport import service_accepts


@dataclass(frozen=True)
class MerchantRouteLeg:
    service_id: str
    origin_market_id: str
    destination_market_id: str
    trade: OceanTradeQuote


def evaluate_merchant_route(
    world: World,
    service_id: str,
    market_ids: tuple[str, ...],
    good_type_ids: tuple[str, ...],
    *,
    fuel_price: float = 0.0,
) -> tuple[MerchantRouteLeg, ...]:
    """Evaluate each leg of a circular service against local price spreads."""
    if len(market_ids) < 2:
        raise ValueError("a merchant route requires at least two markets")
    service = world.transport_services[service_id]
    if len(service.stop_place_ids) != len(market_ids):
        raise ValueError("market list must match the service stop list")
    if any(world.markets[market_id].place_id != place_id for market_id, place_id in zip(market_ids, service.stop_place_ids)):
        raise ValueError("merchant markets must correspond to service stops")
    legs: list[MerchantRouteLeg] = []
    eligible_goods = tuple(good_id for good_id in good_type_ids if service_accepts(service, good_id))
    for index, origin_market_id in enumerate(market_ids):
        destination_market_id = market_ids[(index + 1) % len(market_ids)]
        trade = select_ocean_trade(
            world,
            origin_market_id,
            destination_market_id,
            service.asset_id,
            eligible_goods,
            fuel_price=fuel_price,
        )
        if trade is not None and trade.expected_margin > 0:
            legs.append(MerchantRouteLeg(service_id, origin_market_id, destination_market_id, trade))
    return tuple(legs)
