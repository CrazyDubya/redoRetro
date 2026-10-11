# Milestone 3 — The Living Streets

## M3.1 baseline

The first M3 slice installs a bounded, directly traversable Lower Manhattan
district into the existing harbor `World`. It does not create a second map or
player-only movement model.

The fixture currently provides:

- four street nodes: Wall Street, Broad Street, Pearl Street, and Water Street;
- eight visitable sites: tavern, shop, workshop, warehouse, dock, Royal Exchange,
  Fly Market, and Trinity Churchyard;
- four interiors: tavern, shop, workshop, and warehouse;
- directed walk routes with explicit reverse edges;
- the existing canonical Brooklyn ferry with outbound and return services.

The street names and broad landmark relationships are grounded in Bernard
Ratzer's plan surveyed in 1766–1767. The implementation's coordinates and
small route graph are a bounded playable approximation, not a parcel-accurate
reconstruction. Primary references:

- [Library of Congress: Ratzer plan, 1767](https://www.loc.gov/item/91684092/)
- [New York Public Library: Plan of New York surveyed in 1766–1767](https://digitalcollections.nypl.org/items/ed619490-c5aa-012f-7ed8-58d385a7bc34)

## Acceptance evidence

`tests/test_street_slice.py` verifies that the district is represented by
canonical `Place` and `Route` entities, that the eight sites and four interiors
are registered, that a walking path exists, and that every street edge has a
reverse edge. It also verifies a physical ferry crossing in both directions:
the vessel and passengers must reach the first landing before the reverse
boarding can occur.

The Brooklyn commuter remains a deliberately narrow acceptance fixture. The
return ferry is now represented, but a complete recurring timetable and a
browser client are later M3 phases.

## M3.2 baseline

The district now has canonical `Door` and `SituatedObject` entities. The
interaction gateway requires physical co-location, current reachability, an
open door, and any declared access or skill. It records successful actions as
causal events and rejects remote, unauthorized, unsupported, or in-transit
interactions without mutating the world.

`tests/test_physical_interactions.py` covers locked-warehouse access, physical
door passage, route reachability, a skilled dock operation, and rejection of
remote or unsupported object actions.

## M3.3 baseline — shared actions

The shared action gateway in `redos/actions.py` exposes movement, inspection,
conversation, purchase, and physical delivery for both future player callers
and autonomous rules. It delegates to the existing canonical movement,
interaction, information, market, and inventory gateways rather than creating
player-specific state. Movement uses the same door-aware route search as the
street fixture; conversation requires stationary co-presence; purchase uses
real market stock; and delivery transfers seller-owned lots only between
co-located holders. Focused coverage is in
`tests/test_shared_actions.py`, with the complete suite retaining the M2
harbor and M3.1/M3.2 regressions.

## M3.4 baseline — durable snapshots

`redos/persistence.py` stores a checksummed, versioned snapshot of the
canonical `World` in SQLite and validates the restored world before returning
it. The snapshot includes the existing runtime registries and seeded random
state without introducing a second simulation model. `execute_once` records a
command result in canonical runtime state, so retries are no-ops and the
idempotency ledger survives reload. Round-trip, retry-after-reload, and
corruption rejection are covered by `tests/test_persistence.py`.
