import unittest

from redos.bootstrap import build_tiny_world
from redos.equestrian import care_for_horse, ride
from redos.model import Actor, Place, Route, TransportAsset
from redos.simulation import effective_route_hours, tick
from redos.transport import add_asset, replenish_asset


class RidingClubTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=19)
        world.add(Place("stable", "Stable"))
        world.add(Place("trailhead", "Trailhead"))
        world.add(Place("ridge", "Ridge"))
        world.add(Route("shop-stable", "shop", "stable", 0.2, 1, "walk", terrain="plain", allowed_modes=("walk",)))
        world.add(Route("stable-ridge", "stable", "ridge", 1.0, 1, "land", terrain="rough", allowed_modes=("horse",)))
        rider = Actor("rider", "Rider", "stable", money=20.0)
        world.add(rider)
        add_asset(
            world,
            TransportAsset(
                "bay-horse",
                "Bay Horse",
                "horse",
                "stable",
                "rider",
                capacity=1,
                supplies={"energy": 60.0, "feed": 2.0},
                supply_capacity={"energy": 60.0, "feed": 4.0},
                supply_burn_per_hour={"energy": 1.0},
            ),
        )
        return world, rider, world.transport_assets["bay-horse"]

    def test_mounted_movement_uses_shared_route_and_moves_rider_and_horse(self):
        world, rider, horse = self._world()
        movement = ride(world, rider.id, horse.id, "ridge")
        self.assertEqual(movement.movement_mode, "horse")
        self.assertGreater(effective_route_hours(world, world.routes["stable-ridge"], mode="horse"), 24)
        tick(world, movement.duration_hours)
        self.assertEqual(rider.location_id, "ridge")
        self.assertEqual(horse.location_id, "ridge")
        self.assertLess(horse.supplies["energy"], 60.0)
        self.assertTrue(any(event.kind == "horse_mounted" for event in world.events))

    def test_energy_exhaustion_pauses_mounted_journey_without_teleporting(self):
        world, rider, horse = self._world()
        horse.supplies["energy"] = 2.0
        movement = ride(world, rider.id, horse.id, "ridge")
        tick(world, 3)
        self.assertEqual(rider.location_id, "stable")
        self.assertEqual(rider.traveling_to, "ridge")
        self.assertEqual(horse.unavailable_reason, "energy exhausted")
        self.assertTrue(any(event.kind == "passenger_delayed" for event in world.events))
        replenish_asset(world, horse.id, "energy", 60.0, source_id="stable")
        tick(world, movement.duration_hours)
        self.assertEqual(rider.location_id, "ridge")

    def test_care_restores_state_but_does_not_change_location_or_bypass_assignment(self):
        world, rider, horse = self._world()
        horse.readiness = 0.25
        care_for_horse(world, horse.id, "groom", 0.5)
        self.assertEqual(horse.readiness, 0.75)
        care_for_horse(world, horse.id, "rest", 0.5)
        self.assertEqual(horse.readiness, 1.0)
        self.assertEqual(horse.location_id, "stable")
        ride(world, rider.id, horse.id, "ridge")
        with self.assertRaises(ValueError):
            care_for_horse(world, horse.id, "rest", 0.1)

    def test_feed_respects_canonical_supply_capacity(self):
        world, _rider, horse = self._world()
        added = care_for_horse(world, horse.id, "feed", 5.0)
        self.assertEqual(added, 2.0)
        self.assertEqual(horse.supplies["feed"], 4.0)
        self.assertTrue(any(event.kind == "horse_fed" for event in world.events))


if __name__ == "__main__":
    unittest.main()
