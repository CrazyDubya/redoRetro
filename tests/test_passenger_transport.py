import unittest

from redos.bootstrap import build_tiny_world
from redos.employment import pay_wages
from redos.model import Actor, Business, JobOpening, Place, Route, ScheduleEntry, TransportAsset
from redos.simulation import _start_next_leg, tick
from redos.transport import add_asset, assign_asset, release_asset


class PassengerTransportTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world()
        world.add(Place("island-job", "Island workplace"))
        world.add(Route("ferry-crossing", "shop", "island-job", 1.0, 1, "water", terrain="water", allowed_modes=("vessel",)))
        world.add(Business("island-employer", "Island Employer", "island-job", "warehouse", cash=1_000.0))
        world.add(JobOpening("island-opening", "island-employer", "dock worker", 24.0, 8, 16))
        worker = Actor(
            "ferry-worker",
            "Ferry Worker",
            "shop",
            occupation="dock worker",
            employer_id="island-employer",
            money=10.0,
            schedule=[ScheduleEntry(8, 16, "work", "island-job", priority=10, interruptible=False)],
        )
        world.add(worker)
        world.businesses["island-employer"].employees.append(worker.id)
        add_asset(world, TransportAsset("ferry", "Harbor Ferry", "vessel", "shop", "island-employer", capacity=4, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        world.runtime["passenger_services"] = (("ferry", "shop", "island-job"),)
        return world, worker

    def test_worker_boards_physical_ferry_and_arrives_without_work_credit_while_traveling(self) -> None:
        world, worker = self._world()
        movement_started = _start_next_leg(world, worker, "island-job")
        self.assertTrue(movement_started)
        self.assertEqual(worker.traveling_to, "island-job")
        tick(world, 12)
        self.assertEqual(worker.location_id, "shop")
        self.assertEqual(worker.work_hours_by_day, {})
        tick(world, 12)
        self.assertEqual(worker.location_id, "island-job")
        self.assertEqual(world.transport_assets["ferry"].location_id, "island-job")
        pay_wages(world, "island-employer")
        self.assertTrue(any(event.kind == "wage_missed" and worker.id in event.actors for event in world.events))

    def test_unavailable_ferry_does_not_fallback_to_teleport_or_walking(self) -> None:
        world, worker = self._world()
        assign_asset(world, "ferry", "maintenance", kind="maintenance")
        self.assertFalse(_start_next_leg(world, worker, "island-job"))
        self.assertEqual(worker.location_id, "shop")
        self.assertTrue(any(event.kind == "passenger_service_unavailable" for event in world.events))
        release_asset(world, "ferry")
        self.assertTrue(_start_next_leg(world, worker, "island-job"))
        self.assertEqual(worker.traveling_to, "island-job")


if __name__ == "__main__":
    unittest.main()
