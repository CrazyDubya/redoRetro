# Milestone 1 acceptance record

The integrated fixture is built by `redos.vertical.build_integrated_world` and
run with `run_autonomous_days`.  It contains twelve citizens, three households,
a tavern, shop market, workshop, warehouse, dock, vessel inventory, building
interiors, jobs, and local routes.

The 30-day acceptance test verifies:

- autonomous movement through continuous positions, shared by player and NPC
  actors;
- sleep, work, meals, wages, household expenses, purchases, and health changes;
- grain → flour → bread production with lot provenance;
- physical market transfers and changing market prices;
- direct firm competition and market-share records;
- meetings, witness observations, recollection differences, statements, trust,
  and divergent beliefs;
- a dock incident known initially only to actual witnesses;
- a populated evening tavern whose patrons arrived through scheduled simulation;
- conservation and world-state validation after thirty days.

Run it with:

```sh
python3 -m unittest discover -s tests -v
```

The test suite includes both the focused donor kernels and the integrated
vertical-slice acceptance tests.
