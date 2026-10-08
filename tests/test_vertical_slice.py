import unittest

from redos.audit import conservation_errors, information_graph, tavern_report, validate_world
from redos.runtime import advance_world, run
from redos.vertical import build_integrated_world, default_dock_incident, run_autonomous_days
from redos.simulation import tick


class IntegratedVerticalSliceTests(unittest.TestCase):
    def test_thirty_days_are_autonomous_and_causally_auditable(self) -> None:
        slice_state = build_integrated_world()
        world = run(slice_state.world, 30, external_events=(default_dock_incident(slice_state),))
        self.assertEqual(world.now.day, 31)
        self.assertTrue(any(event.kind == "incident" for event in world.events))
        self.assertFalse(validate_world(world))
        self.assertFalse(conservation_errors(world))
        self.assertGreater(sum(event.kind == "payment" for event in world.events), 100)
        self.assertGreater(sum(event.kind == "production" for event in world.events), 30)
        self.assertGreater(sum(event.kind == "trade" for event in world.events), 10)
        self.assertGreater(sum(event.kind == "meal" for event in world.events), 30)
        self.assertGreater(sum(event.kind == "meeting" for event in world.events), 100)
        self.assertGreater(sum(event.kind == "work" for event in world.events), 100)
        competition = [event for event in world.events if event.kind == "competition"]
        self.assertTrue(any(len(event.data.get("shares", {})) >= 2 for event in competition))

    def test_living_tavern_contains_simulated_patrons_and_divergent_information(self) -> None:
        slice_state = build_integrated_world()
        world = run_autonomous_days(slice_state, 30, external_events=(default_dock_incident(slice_state),))
        for _ in range(19):
            tick(world, 1)
        report = tavern_report(world, "tavern")
        self.assertGreater(len(report), 0)
        self.assertTrue(all(item["why_here"] for item in report))
        self.assertTrue(all(item["where_before"] is not None for item in report))
        self.assertTrue(all(item["going_afterward"] for item in report))
        self.assertTrue(all("from" in heard and "trust" in heard for item in report for heard in item["heard"]))
        graph = information_graph(world)
        beliefs = [values["dock-incident"] for values in graph["beliefs"].values() if "dock-incident" in values]
        self.assertGreaterEqual(len(set(beliefs)), 2)
        self.assertGreaterEqual(len(graph["observations"]), 2)
        self.assertGreaterEqual(len(graph["statements"]), 2)

    def test_incident_initial_knowledge_is_limited_to_actual_witnesses(self) -> None:
        slice_state = build_integrated_world()
        incident = default_dock_incident(slice_state)
        world = slice_state.world
        for _ in range(4 * 24 + 13):
            advance_world(world, 1, external_events=(incident,))

        event = next(event for event in world.events if event.kind == "incident")
        observed = {observation.witness_id for observation in world.observations.values() if observation.event_id == event.id}
        physically_present = {
            actor.id
            for actor in world.actors.values()
            if actor.location_id == "dock" and actor.traveling_to is None
        }
        self.assertTrue(observed)
        self.assertEqual(observed, physically_present)
        self.assertTrue(all(event.id in world.actors[actor_id].knowledge for actor_id in observed))
        self.assertTrue(all(event.id not in actor.knowledge for actor in world.actors.values() if actor.id not in observed))


if __name__ == "__main__":
    unittest.main()
