# Milestone 3 — The Living Streets

## M3.1 baseline

The first M3 slice installs a bounded, directly traversable Lower Manhattan
district into the existing harbor `World`. It does not create a second map or
player-only movement model.

The fixture currently provides:

- twelve street/intersection nodes, including Wall, Broad, Pearl, Water,
  Broadway, Beaver, Stone, Hanover, William, Cedar, and Whitehall;
- eight visitable sites: tavern, shop, workshop, warehouse, dock, Royal Exchange,
  Fly Market, and Trinity Churchyard;
- four interiors: tavern, shop, workshop, and warehouse;
- directed walk routes with explicit reverse edges;
- the existing canonical Brooklyn ferry with outbound and return services.

The street names and broad landmark relationships are grounded in Bernard
Ratzer's plan surveyed in 1766–1767. Each installed place carries the primary
Ratzer source URL and an explicit confidence note. The implementation's
coordinates and small route graph are a bounded playable approximation, not a
parcel-accurate reconstruction. Primary references:

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
open door, and any declared access or skill. Door passage starts the same
timed canonical movement used by street travel and records completion as a
causal event. The gateway rejects remote, unauthorized, unsupported, or
in-transit interactions without mutating the world.

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

`redos/persistence.py` stores a checksummed, versioned explicit JSON snapshot
of the canonical `World` in SQLite and validates the restored world before
returning it. An allowlisted dataclass registry and encoded RNG state preserve
the existing runtime registries without unsafe executable deserialization or a
second simulation model. `execute_once` records a command fingerprint and
result in canonical runtime state, so identical retries are no-ops and
conflicting argument reuse is rejected after reload. Round-trip, corruption,
command-conflict, and 72+72-hour equivalence coverage are in
`tests/test_persistence.py`.

## M3.5 baseline — living neighborhood

The street fixture now connects the existing residences to the Ratzer-derived
street graph through ordinary feeder routes. With no player commands, the
canonical runtime can move residents to work and leisure, process commerce,
create bounded meetings, and propagate witnessed information. The regression
in `tests/test_street_slice.py` runs thirty days with one external dock
incident and checks movement, work, meetings, statements, and ordinary tavern
population. No named patron or witness is injected by the test.

## M3.6 baseline — mobile web client

`python -m redos.web` starts a standard-library-only local server. Its
responsive top-down client reads `/api/state` and submits idempotent commands
to `/api/command`; versioned `/v1/state` and `/v1/command` aliases are also
retained. The browser controls the existing `merchant` actor through the
shared action gateway for movement, inspection, conversation, purchase,
delivery, door passage, ferry boarding, waiting, save, reload, and restart.
Its state view is filtered to the player's physical vicinity and includes
inventory and a local journal. `tests/test_web.py`
exercises the actual HTTP server, verifies physical movement rather than
teleportation, confirms a canonical crossing to Brooklyn, and checks that
retrying a command does not create a second mutation. No Docker, cloud
service, frontend dependency, or player-only world state is required.

The browser-selected actor remains canonical world state, but is excluded
from autonomous NPC schedule and household-need adjudication. Its issued
movement, including multi-leg continuation, still advances through the same
runtime movement authority as every other actor.

## M3.7 baseline — acceptance

`street_audit(world)` produces the machine-readable district report used by
`tests/test_milestone3_acceptance.py`. The 30-day run uses one deterministic
external dock incident and otherwise advances through the ordinary runtime. It
checks movement, work, bounded meetings, divergent incident beliefs, market
conservation, world validation, JSON serialization, and a measured runtime
bound. Acceptance tests also execute a same-seed player command tape and
demonstrate that purchase/movement choices change the canonical world. The
full pytest suite retains the Milestone 2 harbor and bidirectional-ferry
regressions, while the HTTP tests cover the playable journey and concurrent
command behavior.

Milestone 3 known limitations are deliberately bounded: the Ratzer-derived
street graph remains an approximate slice rather than a parcel survey; the
browser server is a single local session with no authentication or
multiplayer; snapshots are local SQLite application data with an explicit safe
format but no migration history; and the client is intentionally a thin
standard-library demo rather than a production frontend build.
