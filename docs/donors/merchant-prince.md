# Merchant Prince

## Evidence inspected

- [Merchant Prince manual](https://www.scribd.com/document/776175117/Merchant-Prince-Manual) documents circular trade routes, production, city commodity limits and warehouse use.
- [Merchant Prince overview](https://en.wikipedia.org/wiki/Merchant_Prince) describes trade by galleys, cogs, donkey teams and camel caravans, commodity movement among cities, and automated trading routes.
- [MobyGames entry](https://www.mobygames.com/game/4354/merchant-prince/) identifies route, warehouse and commodity management as the main economic work.
- [Contemporary review](https://www.ibiblio.org/GameBytes/issue18/greviews/mprince/mprince.html) confirms automated trade routes as the reusable operational mechanism.

## Selected mechanism

The reusable kernel is multi-port route evaluation: a merchant route compares local source/destination prices for each leg, respects the assigned carrier's capacity and operating cost, and keeps only profitable, physically carryable opportunities. The existing `TransportService` remains the route authority.

## Rejected

Political bribery, Senate/Church offices, conquest, mercenaries, piracy, brigandry, relic exploration, and multiplayer are excluded. No separate Merchant Prince warehouse, fleet, or world clock is created.

## Canonical translation

`evaluate_merchant_route` maps service stops to existing `Market` places and calls `select_ocean_trade` for each circular leg. `OceanTradeQuote` reads physical market stock, local demand-derived prices, route duration and carrier capacity/cost. The result is a derived plan; actual cargo movement still requires ordinary `Contract`, `Shipment`, `TransportAsset`, `TransportFacility` and `World.transfer_goods` transitions.

## Tests and uncertainty

Tests cover multi-town circular evaluation, per-leg positive-margin filtering, carrier constraints and the no-mutation property of planning. Exact original route automation, guard systems and political access rules are not claimed because they are outside this extraction.
