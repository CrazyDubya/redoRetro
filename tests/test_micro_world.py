import unittest

from redos.bootstrap import build_micro_world
from redos.simulation import run_days


class MicroWorldAuditTests(unittest.TestCase):
    def test_twelve_people_and_thirty_days_without_state_corruption(self) -> None:
        world = build_micro_world()
        run_days(world, 30)
        self.assertEqual(len(world.actors), 14)  # merchant, cooper, plus 12 citizens
        self.assertEqual(len(world.households), 4)
        self.assertGreaterEqual(len(world.events), 30)
        self.assertTrue(all(lot.quantity >= 0 for lot in world.lots.values()))
        self.assertTrue(all(actor.age > 0 and actor.health > 0 for actor in world.actors.values()))
        self.assertLessEqual(world.now.day, 31)


if __name__ == "__main__":
    unittest.main()
