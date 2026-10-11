import unittest

from redos.interactions import enter_door, interact_with_object, reachable_path
from redos.model import Actor
from redos.streets import build_street_world


class PhysicalInteractionTests(unittest.TestCase):
    def test_locked_door_and_reachability_require_access(self) -> None:
        world = build_street_world(seed=9).world
        actor = Actor("visitor", "Visitor", "water-street")
        world.add(actor)

        self.assertFalse(reachable_path(world, actor.id, "warehouse"))
        with self.assertRaises(PermissionError):
            enter_door(world, actor.id, "warehouse-door")

        actor.skills["access"] = ["warehouse"]
        path = reachable_path(world, actor.id, "warehouse")
        self.assertTrue(path)
        enter_door(world, actor.id, "warehouse-door")
        self.assertEqual(actor.location_id, "warehouse")
        self.assertTrue(any(event.kind == "door_passed" and actor.id in event.actors for event in world.events))

    def test_objects_require_physical_co_location_and_capability(self) -> None:
        world = build_street_world(seed=10).world
        actor = Actor("visitor", "Visitor", "shop")
        world.add(actor)

        with self.assertRaises(ValueError):
            interact_with_object(world, actor.id, "dock-crane", "inspect")
        actor.location_id = "dock"
        with self.assertRaises(PermissionError):
            interact_with_object(world, actor.id, "dock-crane", "operate")
        actor.skills["dockwork"] = 1.0
        result = interact_with_object(world, actor.id, "dock-crane", "operate")
        self.assertEqual(result["action"], "operate")
        self.assertTrue(any(event.kind == "object_interaction" and actor.id in event.actors for event in world.events))

    def test_unknown_or_remote_object_action_cannot_mutate_state(self) -> None:
        world = build_street_world(seed=11).world
        actor = Actor("visitor", "Visitor", "shop")
        world.add(actor)
        before = len(world.events)
        with self.assertRaises(ValueError):
            interact_with_object(world, actor.id, "shop-counter", "purchase")
        with self.assertRaises(ValueError):
            interact_with_object(world, actor.id, "exchange-board", "inspect")
        self.assertEqual(len(world.events), before)


if __name__ == "__main__":
    unittest.main()
