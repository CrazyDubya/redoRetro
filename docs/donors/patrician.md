# The Patrician

## Evidence inspected

- [The Patrician Amiga manual](https://www.lemonamiga.com/doc/patrician/1197) describes a trade simulation in which prices depend on supply/demand and town population depends on food supply.
- [Patrician III manual](https://cdn.akamai.steamstatic.com/steam/apps/33570/manuals/manual-patrician3.pdf?t=1450011557) documents continuous production, trade-route supply, warehouse/trading-office transfer and town production/demand.
- [Patrician II review](https://www.gamespot.com/reviews/patrician-ii-review/1900-2819467/) describes town-specific prices driven by demand and supply and automated routes/convoys.
- [Patrician IV interview](https://www.gamewatcher.com/interviews/patrician-iv-interview/11366) confirms the selected economic loop: local production, transport, consumption, and prices determined by offer and demand.

## Selected mechanism

The reusable kernel is town acceptance and storage: local demand remains an economic pressure until physical goods arrive, while a warehouse/storage facility can reject a delivery when its capacity is full. A successful market delivery reduces the destination market's demand backlog and therefore changes later price pressure.

## Rejected

No Hanseatic political ladder, elections, piracy, combat, town construction, detailed production catalogue, or second automated-convoy implementation is added. Ordered `TransportService` already represents recurring routes; this donor adds its town-demand/storage consequence rather than duplicating it.

## Canonical translation

`Market.demand_backlog` is the derived unmet-demand pressure. `TransportFacility.storage_access_id` and `storage_capacity` constrain the physical destination holder. Freight settlement transfers the canonical lot first only after capacity validation, then calls `accept_market_delivery` to reduce the town backlog. No market inventory shadow is created.

## Tests and uncertainty

Tests cover demand reduction after physical arrival and rejection at a full warehouse with cargo still on the carrier. The evidence is original/manual documentation and contemporary reviews rather than source, so exact Patrician price curves and town population formulas remain outside this extraction.
