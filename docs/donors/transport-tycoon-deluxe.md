# Transport Tycoon Deluxe

## Evidence inspected

- [OpenTTD Orders manual](https://wiki.openttd.org/en/Manual/Orders) documents ordered vehicle stops, loading behavior, transfer and the requirement for a route with more than one station to earn transport income.
- [OpenTTD Timetable manual](https://wiki.openttd.org/en/Manual/Timetable) documents per-leg travel/station timing and delay accumulation when traffic or breakdowns disrupt a service.
- [OpenTTD Cargo manual](https://wiki.openttd.org/en/Manual/Cargo) documents discrete cargo units, producer/acceptor behavior, station custody and age-sensitive cargo.
- [Transport Tycoon Deluxe manual](https://drwjf.github.io/ctm/references/Transport_Tycoon_Deluxe_Manual_EN.pdf) was used as the original-game operating reference for assigning vehicle routes and station acceptance.

## Verified mechanism selected for Redos

Transport Tycoon’s reusable kernel is an ordered vehicle service: a persistent vehicle follows stops, spends time traveling or waiting at a stop, consumes operating resources, and can be assigned cargo only when the cargo type is accepted by that service. A freight assignment interrupts the service asset while the existing physical Shipment path handles loading, movement, unloading and settlement. Once the shipment arrives, the service resumes from the destination stop.

## Rejected

The implementation does not import the company UI, map construction, rail signaling, vehicle purchasing, industry-growth formulas, or the original game’s virtual station micro-process. Those mechanics either belong to later transport/production work or would create a second cargo authority. Cargo remains physical `InventoryLot` custody in the canonical world.

## Canonical translation

`TransportService` stores the ordered stop list, accepted cargo types, dwell/timetable state and current leg. It reads `Route`, `RouteCondition` and `TransportAsset`; it mutates only service state and the asset’s canonical location/resources. Freight still uses `Shipment`, `TransportFacility`, `Contract` and `World.transfer_goods`. A service cargo assignment records the service on the same Shipment and cannot coexist with another asset assignment.

## Tests and uncertainty

Tests cover cyclic ordered movement, fuel consumption, cargo interruption/resumption and rejection of unaccepted cargo. OpenTTD is a later open-source reimplementation rather than the original TTD source, so exact proprietary payment and station-rating formulas are not claimed here; only the documented reusable service mechanisms are translated.
