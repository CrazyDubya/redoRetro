import unittest

from redos.audit import conservation_errors, information_graph, tavern_report, validate_world
from redos.vertical import build_integrated_world, run_autonomous_days
from redos.simulation import tick


class IntegratedVerticalSliceTests(unittest.TestCase):
    def test_thirty_days_are_autonomous_and_causally_auditable(self) -> None:
        slice_state = build_integrated_world()
        world = run_autonomous_days(slice_state, 30)
        self.assertEqual(world.now.day, 31)
        self.assertIsNotNone(slice_state.incident_event_id)
        self.assertFalse(validate_world(world))
        self.assertFalse(conservation_errors(world))
        self.assertGreater(sum(event.kind == "payment" for event in world.events), 100)
        self.assertGreater(sum(event.kind == "production" for event in world.events), 30)
        self.assertGreater(sum(event.kind == "trade" for event in world.events), 10)
        self.assertGreater(sum(event.kind == "meal" for event in world.events), 100)
        self.assertGreater(sum(event.kind == "meeting" for event in world.events), 100)

    def test_living_tavern_contains_simulated_patrons_and_divergent_information(self) -> None:
        slice_state = build_integrated_world()
        world = run_autonomous_days(slice_state, 30)
        for _ in range(19):
            tick(world, 1)
        report = tavern_report(world, "tavern")
        self.assertEqual(len(report), 12)
        self.assertTrue(all(item["why_here"] for item in report))
        self.assertTrue(all("from" in heard and "trust" in heard for item in report for heard in item["heard"]))
        graph = information_graph(world)
        beliefs = [values["dock-incident"] for values in graph["beliefs"].values() if "dock-incident" in values]
        self.assertGreaterEqual(len(set(beliefs)), 2)
        self.assertGreaterEqual(len(graph["observations"]), 2)
        self.assertGreaterEqual(len(graph["statements"]), 2)


if __name__ == "__main__":
    unittest.main()
