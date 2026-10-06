import unittest

from redos.bootstrap import build_tiny_world
from redos.living import Bid, Recipe, add_environment_cell, auction, produce, propagate, recollect, tell, witness_event
from redos.model import EnvironmentCell, GoodType, ScheduleEntry


class StimulatingSimulationKernelTests(unittest.TestCase):
    def test_production_uses_inputs_and_preserves_provenance(self) -> None:
        world = build_tiny_world()
        world.add(GoodType("flour", "Flour", 8.0))
        world.create_lot("metals", 3, holder_id="workshop-business", owner_id="workshop-business", provenance=("ore shipment",))
        event_id = produce(world, "workshop-business", Recipe("forge-tool", {"metals": 2}, "flour", 1))
        self.assertEqual(world.quantity_held("workshop-business", "metals"), 1)
        result = world.lots_held_by("workshop-business", "flour")
        self.assertEqual(result[0].provenance[0], event_id)
        self.assertEqual(world.explain(event_id)[0].kind, "production")

    def test_observation_recollection_and_belief_are_not_world_truth(self) -> None:
        world = build_tiny_world()
        event = world.record("incident", "a lantern was broken", entities=["tavern"])
        observations = witness_event(world, event_id=event.id, content="I saw Ada break the lantern", witnesses=["merchant", "cooper"])
        recollect(world, observations[1].id, content="I think I saw someone else", confidence=0.3)
        tell(world, "merchant", "cooper", "lantern-breaker", "Ada broke the lantern", truthful=True, trust_delta=0.1)
        self.assertNotEqual(world.observations[observations[1].id].recollection, world.events[0].description)
        self.assertEqual(world.actors["cooper"].beliefs["lantern-breaker"], "Ada broke the lantern")
        self.assertEqual(world.statements["statement-1"].truthful, True)

    def test_local_environment_propagates_and_auction_transfers_ownership(self) -> None:
        world = build_tiny_world()
        add_environment_cell(world, EnvironmentCell("fire-a", "dock", "burning", fuel=1.0, neighbors=("fire-b",)))
        add_environment_cell(world, EnvironmentCell("fire-b", "warehouse", "clear", fuel=1.0, moisture=0.0))
        self.assertEqual(propagate(world, source_cell_id="fire-a", from_state="burning", to_state="burning", probability=0.8), ["fire-b"])
        world.add(GoodType("painting", "Painting", 100.0))
        world.create_lot("painting", 1, holder_id="tavern-business", owner_id="tavern-business")
        world.actors["merchant"].money = 200
        world.actors["cooper"].money = 300
        winner, amount = auction(world, "tavern-business", "painting", 1, [Bid("merchant", 150), Bid("cooper", 120)])
        self.assertEqual((winner, amount), ("merchant", 150))
        self.assertEqual(world.quantity_held("merchant", "painting"), 1)
