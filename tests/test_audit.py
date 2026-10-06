import unittest

from redos.audit import causal_chain, information_graph, tavern_report, validate_world
from redos.bootstrap import build_tiny_world
from redos.living import tell, witness_event


class AuditTests(unittest.TestCase):
    def test_information_graph_keeps_truth_observation_statement_and_belief_distinct(self) -> None:
        world = build_tiny_world()
        event = world.record("incident", "crate went missing", entities=["warehouse"])
        witness_event(world, event_id=event.id, content="I saw the crate leave", witnesses=["merchant"])
        tell(world, "merchant", "cooper", "crate-thief", "I think the cooper took it", truthful=False, trust_delta=-0.1)
        graph = information_graph(world)
        self.assertEqual(graph["observations"][0]["event"], event.id)
        self.assertFalse(graph["statements"][0]["truthful"])
        self.assertEqual(graph["beliefs"]["cooper"]["crate-thief"], "I think the cooper took it")
        self.assertEqual(graph["trust"]["cooper"]["merchant"], 0.4)

    def test_tavern_report_and_causal_chain_are_reconstructable(self) -> None:
        world = build_tiny_world()
        event = world.record("incident", "a meeting occurred", entities=["tavern"])
        witness_event(world, event_id=event.id, content="I saw the meeting", witnesses=["merchant"])
        world.actors["merchant"].location_id = "tavern"
        report = tavern_report(world, "tavern")
        self.assertEqual(report[0]["witnessed"][0]["event"], event.id)
        self.assertEqual(causal_chain(world, event.id)[0]["kind"], "incident")
        self.assertEqual(validate_world(world), [])


if __name__ == "__main__":
    unittest.main()
