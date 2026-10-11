# Milestone 2 acceptance record — The Living Harbor

Status: implementation complete; formal acceptance evidence recorded with the
regional passenger-employment scenario.

## Scope

The harbor fixture extends the Milestone 1 canonical world with Manhattan,
Brooklyn, Staten Island, and New Jersey landing facilities. Freight, passenger
movement, carts, vessels, facilities, contracts, production, labor, finance,
insurance, property, markets, weather, and causal events all advance through
the same `World` clock.

## Phase comparison

| Phase | Required capability | Evidence in Redos |
| --- | --- | --- |
| M2.1 Ports of Call | Capacity-constrained loading, voyages, unloading, settlement | `redos.transport`, `tests/test_transport.py` |
| M2.2 Carrier Command | Persistent carriers, fuel, condition, supplies, assignment, recovery | `tests/test_physical_asset_services.py`, `tests/test_transport.py` |
| M2.3 Port operations/contracts | Queues, reservations, handling time, deadlines, failures, settlement | `tests/test_transport.py`, `tests/test_milestone2_review_gaps.py` |
| M2.4 Autonomous commerce | Demand creates contracts and recurring carrier work | `tests/test_harbor_acceptance.py`, `tests/test_completion_audit.py` |
| M2.5 Environmental constraints | Weather changes route access, delay, production, and price | `tests/test_harbor_acceptance.py` |
| M2.6 Living-world integration | Physical passenger crossing affects attendance and wages | `test_regional_passenger_disruption_reaches_attendance_and_household_cash` |
| M2.7 Living Harbor | Sustained regional simulation and machine-readable audit | `run_harbor_demonstration`, `tests/test_completion_audit.py` |

## Deterministic acceptance evidence

The primary fixture uses deterministic seeds. The 30-day acceptance tests use
seeds 11, 12, and 27. The extended audit uses seed 31 for 90 days. The
passenger comparison uses seed 44 and runs a baseline and identical storm-
disrupted world to the same elapsed time.

The only externally authored stimuli in the extended audit are:

* a deterministic storm affecting the Staten Island water routes;
* a registered, typed cargo loss used to exercise the insurance settlement
  lifecycle.

The passenger acceptance test injects one Brooklyn squall after the commuter
has boarded. Route recovery, arrival, attendance, payroll, and household debt
are then produced by ordinary world advancement.

## Required outcomes

The acceptance suite verifies that:

* regional freight completes through physical custody and bounded facilities;
* New Jersey supply uses a cart-to-vessel relay;
* recurring carriers are reused and merchant return legs settle;
* weather delays supply, reduces production and raises downstream prices;
* a passenger remains physically in transit during a disrupted crossing;
* delayed arrival produces missed attendance and reduced wages;
* the affected household accumulates a larger downstream cash shortfall;
* fuel, supplies, maintenance, operating costs, inventory, money, and causal
  ledgers remain reconciled;
* daily checkpoints and final audits contain no validation, conservation, or
  market-balance errors.

## Verification commands

```sh
python3 -m pytest -q
```

The same test command is run by GitHub Actions on pushes to `main` and pull
requests. The long-form machine-readable report is returned by
`run_harbor_demonstration(seed=31, days=90)`.

## Known limitations

The fixture remains a compact, historically inspired network rather than a
surveyed 1770 map. Supply-transaction rollback still uses whole-world
snapshots; this is tracked as a measured scalability optimization, not a
correctness exception for this milestone. Fuel, maintenance parts, and labor
are now physical for ordinary asset servicing, while explicitly administrative
replenishment APIs remain available for controlled interventions.
