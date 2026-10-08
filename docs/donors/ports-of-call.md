# Ports of Call (1987) archaeology

## Evidence inspected

- [1987 Amiga manual scan](https://www.bestoldgames.net/download/games/ports-of-call/ports-of-call-amiga-manual.pdf), credited to Rolf-Dieter Klein, Martin Ulrich and Aegis Development.
- [Developer's Ports of Call overview](https://www.portsofcall.de/overview/overview_en.html), used to distinguish the original Classic product from later XXL and 3D versions.
- [Manual transcription](https://oldgamesdownload.com/manual/ports-of-call-amiga-manual-english/) used for searchable page references.

No original source listing was located during this pass. The manual is the primary authority for the selected mechanics; secondary descriptions were not used to infer formulas.

## Verified mechanics

The manual describes Ports of Call as a tramp-shipping business simulation. Verified mechanics include:

- freight and destination selection through charter offers;
- loading cargo before departure and unloading before agreed payment is credited;
- route, destination and estimated arrival information;
- ship fuel and refueling;
- fuel consumption affected by time at sea and weather;
- ship condition, repair, port charges and recurring operating expenses;
- speed choices trading fuel consumption against voyage duration and fixed operating cost;
- delayed or costly port navigation as a commercial consequence.

## Redos translation in M2.1

- `TransportAsset` is the persistent carrier identity, capacity, condition, fuel, operator, owner and availability record.
- `TransportFacility` is the physical loading/unloading service point with a bounded active-handling set and queues.
- Existing `Contract`, `Shipment`, `InventoryLot`, `Route` and causal events remain authoritative for the freight obligation.
- `dispatch_freight` creates a queued shipment without advancing the global clock.
- `advance_freight` adjudicates loading, departure, route progress, arrival, unloading, physical custody transfer and settlement.
- Operating cost is currently accrued and recorded on the carrier; cash settlement of that liability is deferred to the port-operations stage.

## Deliberately rejected for M2.1

- manual harbor steering and arcade navigation;
- global ship-market purchasing and mortgages;
- international freight-rate reconstruction;
- detailed weather, reefs, icebergs and rescue events;
- a second shipping or inventory economy.

## Canonical state read and changed

The transport kernel reads contract terms, route topology, physical inventory, carrier capacity/condition/fuel, facility queues and business cash. It changes only the canonical shipment, carrier, facility, inventory, contract and event records. It does not advance `World.now`.

## Remaining uncertainty

The manual establishes the economic relationships but does not expose the original numerical formulas for freight offers, fuel burn, repairs or operating costs. M2.1 therefore uses explicit Redos parameters and records the uncertainty rather than claiming formula-level faithfulness.
