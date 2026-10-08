# Milestone 1 acceptance record

The integrated fixture is built by `redos.vertical.build_integrated_world` and
run by the generic `redos.runtime.run` clock. `run_autonomous_days` is retained
only as a thin compatibility wrapper. It contains twelve citizens, three
households, a tavern, shop market, workshop, warehouse, dock, vessel inventory,
building interiors, jobs, and local routes.

The 30-day acceptance test verifies:

- autonomous movement through continuous positions, shared by player and NPC
  actors, including physical contract shipments;
- sleep, work attendance, meals, wages, household expenses, purchases, and
  health changes driven by eligible needs and schedules;
- grain → flour → bread production with lot provenance;
- physical market transfers and changing market prices;
- direct firm competition and market-share records;
- meetings, witness observations, recollection differences, statements, trust,
  and divergent beliefs;
- an externally injected dock incident known initially only to actual witnesses;
- ordinary role-based cargo duty provides plausible dock traffic without naming
  witnesses in the incident fixture, and the integrated test checks immediate
  knowledge against physical co-presence;
- a naturally populated evening tavern whose patrons arrived through ordinary
  schedules rather than a test-time visitor list;
- conservation and world-state validation after thirty days.
- a family problem can interrupt attendance, reduce payroll, and produce a
  causally linked downstream household debt decision.

Run it with:

```sh
pytest -q
```

The test suite includes both the focused donor kernels and the integrated
vertical-slice acceptance tests.
