import unittest

from redos.bootstrap import build_tiny_world
from redos.derby import add_horse, race_horses, train_horse
from redos.equestrian import care_for_horse
from redos.model import Actor, Place, TransportAsset
from redos.transport import add_asset, assign_asset


class DerbyStallionTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=31)
        world.add(Place("track", "Racing Track"))
        owner_a = Actor("owner-a", "Owner A", "track", money=50.0)
        owner_b = Actor("owner-b", "Owner B", "track", money=50.0)
        world.add(owner_a)
        world.add(owner_b)
        add_asset(world, TransportAsset("horse-a", "Fast Horse", "horse", "track", owner_a.id, capacity=1, supplies={"energy": 20}, supply_capacity={"energy": 20}))
        add_asset(world, TransportAsset("horse-b", "Steady Horse", "horse", "track", owner_b.id, capacity=1, supplies={"energy": 20}, supply_capacity={"energy": 20}))
        add_horse(world, "horse-a", speed=0.9, stamina=0.8, temperament=0.7)
        add_horse(world, "horse-b", speed=0.5, stamina=0.5, temperament=0.5)
        return world, owner_a, owner_b

    def test_training_changes_ability_and_records_fatigue(self):
        world, _owner_a, _owner_b = self._world()
        horse = world.horses["horse-a"]
        train_horse(world, "horse-a", surface="grass", intensity="strong")
        self.assertGreater(horse.speed, 0.9)
        self.assertGreater(horse.fatigue, 0)
        self.assertTrue(any(event.kind == "horse_trained" for event in world.events))

    def test_injury_and_assignment_block_racing_and_transport(self):
        world, _owner_a, _owner_b = self._world()
        world.horses["horse-a"].injury = 0.5
        with self.assertRaises(ValueError):
            race_horses(world, "injured-race", ("horse-a", "horse-b"), location_id="track", distance_m=1600, purse=10, purse_account_id="tavern-business")
        world.horses["horse-a"].injury = 0
        assign_asset(world, "horse-a", "training-run", kind="passenger")
        with self.assertRaises(ValueError):
            race_horses(world, "assigned-race", ("horse-a", "horse-b"), location_id="track", distance_m=1600, purse=10, purse_account_id="tavern-business")

    def test_race_is_co_located_and_pays_existing_owner(self):
        world, owner_a, owner_b = self._world()
        purse_account = world.businesses["tavern-business"]
        before_purse = purse_account.cash
        order = race_horses(
            world,
            "spring-mile",
            ("horse-a", "horse-b"),
            location_id="track",
            distance_m=1600,
            purse=25,
            purse_account_id=purse_account.id,
        )
        self.assertEqual(order[0], "horse-a")
        self.assertEqual(owner_a.money, 75.0)
        self.assertEqual(owner_b.money, 50.0)
        self.assertEqual(purse_account.cash, before_purse - 25)
        self.assertEqual(world.horses["horse-a"].wins, 1)
        self.assertEqual(world.horses["horse-a"].races, 1)
        self.assertGreater(world.horses["horse-a"].fatigue, 0)
        self.assertTrue(any(event.kind == "horse_race_result" for event in world.events))

    def test_recovery_uses_existing_care_state(self):
        world, _owner_a, _owner_b = self._world()
        profile = world.horses["horse-a"]
        profile.fatigue = 0.8
        profile.injury = 0.2
        world.transport_assets["horse-a"].readiness = 0.2
        care_for_horse(world, "horse-a", "rest", 0.8)
        self.assertEqual(profile.fatigue, 0.0)
        self.assertEqual(profile.injury, 0.0)
        self.assertEqual(world.transport_assets["horse-a"].readiness, 1.0)


if __name__ == "__main__":
    unittest.main()
