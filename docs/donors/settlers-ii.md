# The Settlers II — relay logistics kernel

## Evidence inspected

- [The Settlers II guide on roads, flags and transport](https://wiki.mwmdev.com/content/wikipedia_en_all_maxi_2024-01/A/The_Settlers_II), which describes roads as the required transport network, flags as handoff hubs, and multiple carriers reducing congestion on long routes.
- [Settlers II building guide](https://settlers2.net/guides/buildings/), which documents storehouses as storage/transport buildings and notes that additional storehouses reduce distribution time.
- [Settlers II building datasheet](https://settlers2.net/guides/datasheet-for-buildings/), which identifies storehouses and harbors as storage/transport infrastructure and notes carrier variants affecting road throughput.
- [Settlers II instruction-manual reference](https://en.wikipedia.org/wiki/The_Settlers_II), used to locate the original manual citation and cross-check the settlement economy description.

No original source listing was recovered. The selected mechanic is therefore behavioral extraction from the manual/guides and not numerical emulation.

## Selected mechanics

- goods travel on a declared multi-leg route;
- a route can be partitioned among sequential carriers;
- a carrier at the next waypoint is reserved before the journey starts;
- cargo is physically transferred at the handoff point and remains in carrier custody;
- an unavailable next carrier causes a waiting journey rather than teleportation or silent rerouting;
- reservations are released on delivery or failure, while the current carrier's cargo/readiness remains separately auditable.

## Deliberately rejected

Settlement territory spread, military buildings, construction UI, worker population generation, donkey breeding, exact road placement geometry and the donor's real-time map presentation. Existing `Route`, `Shipment`, `TransportAsset` and `TransportFacility` remain authoritative.

## Canonical state translation

The extension adds only relay fields to `Shipment` and a reservation field to `TransportAsset`. It uses `World.transfer_goods` at each handoff, the existing route accessibility and movement timing, and the existing failure/recovery event chain. No second route graph, cargo ledger or world clock is introduced.

## Tests and uncertainty

`tests/test_settlers_ii.py` verifies a two-carrier road relay, physical custody, carrier reservation, waiting for an unavailable handoff carrier, and cleanup after failure. Exact flag spacing, carrier counts and throughput formulas remain uncertain.
