# Carrier Command (1988) archaeology

## Evidence inspected

- [Carrier Command Amiga manual transcription](https://www.lemonamiga.com/doc/carrier-command/291), an original-era operation guide indexed with the original 1988 manual material.
- [Original release and instruction record](https://www.myabandonware.com/game/carrier-command-m6), used to distinguish the 1988 game from later Carrier Command releases.
- [Atari ST release record](https://www.atarimania.com/games/atari-st-games-carrier-command-8869/print?print=1), used as a secondary release/platform cross-check only.

The original source code was not located. The manual evidence is sufficient for the selected logistics mechanisms, but not for exact numerical formulas.

## Verified mechanics selected for Redos

The manual describes the carrier as a persistent mobile base with subordinate Manta aircraft and Walrus amphibious vehicles. It documents unit selection and courses, active versus stored units, fuel, repair state, replenishment, and the consequences of running out of fuel or sustaining damage. It also describes stockpiled replacements and supply-dependent launch/readiness preparation.

Redos keeps the reusable kernel and rejects the combat layer:

- `TransportAsset` now carries readiness, condition, assignment kind, fuel and named operational supplies.
- Assignment is an explicit reservation, so one asset cannot accept incompatible obligations.
- Supply consumption can make an asset unavailable while preserving its assignment failure and cargo custody.
- Replenishment and repair are canonical transitions that can restore availability after a failure.
- Existing freight movement remains the authority for cargo and route state.

## Deliberately rejected

- naval and island combat;
- weapons, targeting, command centres and conquest;
- remote-control or real-time tactical interfaces;
- the fictional island campaign and military production chain;
- a second logistics or inventory world.

## Canonical state read and changed

The kernel reads and changes only `World.transport_assets`, existing `Shipment`, `InventoryLot`, `Contract`, `Route` and causal-event records. It does not create a second clock, location map or cargo store. Assignment, consumption, replenishment, repair and failure all produce inspectable events.

## Tests

The M2.2 regression coverage verifies that a fuel-starved carrier fails with cargo still aboard, releases its assignment, remains unavailable until replenished, and then becomes available again. Existing tests cover carrier reservation, capacity, facility queues and runtime integration.

## Remaining uncertainty

The manual does not expose the original formulas for repair duration, fuel burn, unit production or supply quantities. Redos uses explicit asset parameters and records that these are translated primitives rather than faithful numerical reconstruction.
