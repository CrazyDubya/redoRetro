"""Ocean Trader-derived port-price voyage planning.

The quote is deliberately derived from canonical market stock, prices, routes
and carrier capacity.  Booking hands the chosen quantity to the existing
contract and freight authorities; this module owns no cargo or clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enterprise import create_contract
from .market import quote
from .model import Shipment, World
from .simulation import effective_route_hours, route_path
from .transport import dispatch_freight


@dataclass(frozen=True)
class OceanTradeQuote:
    origin_market_id: str
    destination_market_id: str
    good_type_id: str
    carrier_id: str
    quantity: float
    buy_unit_price: float
    sell_unit_price: float
    travel_hours: float
    estimated_operating_cost: float

    @property
    def gross_margin(self) -> float:
        return (self.sell_unit_price - self.buy_unit_price) * self.quantity

    @property
    def expected_margin(self) -> float:
        return self.gross_margin - self.estimated_operating_cost


def quote_ocean_trade(
    world: World,
    origin_market_id: str,
    destination_market_id: str,
    good_type_id: str,
    carrier_id: str,
    *,
    quantity: float | None = None,
    fuel_price: float = 0.0,
) -> OceanTradeQuote:
    """Quote a physically possible port-to-port cargo opportunity."""
    if fuel_price < 0:
        raise ValueError("fuel price cannot be negative")
    origin_market = world.markets[origin_market_id]
    destination_market = world.markets[destination_market_id]
    asset = world.transport_assets[carrier_id]
    path = route_path(world, origin_market.place_id, destination_market.place_id, mode=asset.asset_type)
    if not path:
        raise ValueError("carrier has no accessible route between the markets")
    available = world.quantity_held(origin_market.place_id, good_type_id)
    capacity = max(0.0, asset.capacity - sum(lot.quantity for lot in world.lots_held_by(asset.id)))
    requested = min(available, capacity) if quantity is None else quantity
    if requested <= 0 or requested > available + 1e-9 or requested > capacity + 1e-9:
        raise ValueError("requested trade quantity exceeds physical stock or carrier capacity")
    buy_price = quote(world, origin_market_id, good_type_id, requested, side="buy").unit_price
    sell_price = quote(world, destination_market_id, good_type_id, requested, side="sell").unit_price
    travel_hours = sum(effective_route_hours(world, route, mode=asset.asset_type) for route in path)
    operating_cost = asset.operating_cost_per_hour * travel_hours
    operating_cost += asset.fuel_burn_per_hour * travel_hours * fuel_price
    return OceanTradeQuote(
        origin_market_id,
        destination_market_id,
        good_type_id,
        carrier_id,
        requested,
        buy_price,
        sell_price,
        travel_hours,
        operating_cost,
    )


def select_ocean_trade(
    world: World,
    origin_market_id: str,
    destination_market_id: str,
    carrier_id: str,
    good_type_ids: tuple[str, ...],
    *,
    fuel_price: float = 0.0,
) -> OceanTradeQuote | None:
    """Choose the best currently affordable, physically carryable cargo."""
    quotes: list[OceanTradeQuote] = []
    for good_type_id in good_type_ids:
        try:
            quotes.append(
                quote_ocean_trade(
                    world,
                    origin_market_id,
                    destination_market_id,
                    good_type_id,
                    carrier_id,
                    fuel_price=fuel_price,
                )
            )
        except (KeyError, ValueError):
            continue
    return max(quotes, key=lambda candidate: candidate.expected_margin, default=None)


def book_ocean_trade(
    world: World,
    trade: OceanTradeQuote,
    *,
    seller_id: str,
    buyer_id: str,
    origin_facility_id: str,
    destination_facility_id: str,
    due_days: int,
    loading_hours: float = 1.0,
    unloading_hours: float = 1.0,
    service_id: str | None = None,
) -> Shipment:
    """Turn a selected quote into the canonical physical freight obligation."""
    origin_place = world.markets[trade.origin_market_id].place_id
    destination_place = world.markets[trade.destination_market_id].place_id
    if world.location_of(seller_id) != origin_place or world.location_of(buyer_id) != destination_place:
        raise ValueError("trade parties must be physically present at the quoted ports")
    if world.quantity_held(seller_id, trade.good_type_id) + 1e-9 < trade.quantity:
        raise ValueError("seller does not hold the quoted physical cargo")
    contract = create_contract(
        world,
        seller_id,
        buyer_id,
        trade.good_type_id,
        trade.quantity,
        trade.sell_unit_price,
        origin_id=origin_place,
        destination_id=destination_place,
        due_days=due_days,
    )
    shipment = dispatch_freight(
        world,
        contract.id,
        carrier_id=trade.carrier_id,
        origin_facility_id=origin_facility_id,
        destination_facility_id=destination_facility_id,
        loading_hours=loading_hours,
        unloading_hours=unloading_hours,
        service_id=service_id,
    )
    world.record(
        "ocean_trade_booked",
        f"{trade.good_type_id} booked from {origin_place} to {destination_place}",
        actors=[seller_id, buyer_id],
        entities=[contract.id, shipment.id, trade.carrier_id],
        causes=contract.causal_event_ids[-1:],
        data={
            "buy_unit_price": trade.buy_unit_price,
            "sell_unit_price": trade.sell_unit_price,
            "expected_margin": trade.expected_margin,
            "travel_hours": trade.travel_hours,
        },
    )
    return shipment
