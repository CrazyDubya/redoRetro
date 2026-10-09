# Ocean Trader

## Evidence inspected

- [Ocean Trader mechanics guide](https://humbe.no/public/computergames/oceantrader/) describes independent port/good markets, price movement after buying and selling, monthly restocking/normalization, port charges, operating costs and the importance of voyage duration.
- [Ocean Trader strategy guide](https://gamefaqs.gamespot.com/pc/933893/faq/68636) documents ship capacity, fuel, condition, port-to-ship/ship-to-port cargo handling and the financial consequence of fuel and berthing.
- [MobyGames entry](https://www.mobygames.com/game/2289/ocean-trader/) confirms the 1995 DOS shipping-company simulation and its port trading focus.

## Selected mechanism

The reusable kernel is a port-to-port trade decision: compare source purchase price with destination sale price, constrain the load by physical stock and carrier capacity, subtract voyage operating/fuel cost, and only then book a physical voyage. The price/stock measurements are derived from the existing Market and InventoryLot state.

## Rejected

The implementation does not import shipyard construction, global company UI, loans, shares, multiplayer, or the game’s full port catalogue. It also does not create a market-owned cargo shadow balance. The actual booked movement is the existing `Contract` → `Shipment` → `TransportAsset` path.

## Canonical translation

`OceanTradeQuote` is an immutable derived decision object. `quote_ocean_trade` reads market prices, physical source stock, route duration, carrier capacity and operating resources. `book_ocean_trade` validates the seller’s physical lot and creates the ordinary Redos contract/freight shipment, recording the expected price spread as causal metadata. No clock is advanced by planning or booking.

## Tests and uncertainty

Tests cover capacity and stock bounds, price-spread selection, operating cost, and physical booking/delivery. The available evidence is a manual/strategy reconstruction and a mechanics guide rather than original source; exact proprietary formulas for port restocking and ship condition are intentionally not claimed.
