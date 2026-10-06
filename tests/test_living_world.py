import unittest

from redos.bootstrap import build_tiny_world
from redos.living import witness_event
from redos.model import Actor, AggregatePopulation, ScheduleEntry
from redos.employment import age_one_year, charge_household_expense, hire, pay_wages
from redos.simulation import add_aggregate_population, ask_about, interrupt, reconcile_population, run_days, tick
from redos.model import Business, JobOpening


class LivingWorldTests(unittest.TestCase):
    def test_six_autonomous_people_move_and_answer_from_own_knowledge(self) -> None:
        world = build_tiny_world()
        for index in range(6):
            actor = Actor(f"person-{index}", f"Person {index}", "tavern", age=20 + index, schedule=[ScheduleEntry(0, 24, "visit shop", "shop")])
            world.add(actor)
        run_days(world, 2)
        moved = [actor for actor in world.actors.values() if actor.id.startswith("person-") and actor.location_id == "shop"]
        self.assertEqual(len(moved), 6)
        event = world.record("incident", "a private argument at the dock")
        witness_event(world, event_id=event.id, content="I heard an argument", witnesses=["person-0"])
        self.assertEqual(ask_about(world, "person-0", event.id), "I heard an argument")
        self.assertEqual(ask_about(world, "person-1", event.id), "I do not know anything about that.")

    def test_aggregate_population_reconciles_with_resolved_people(self) -> None:
        world = build_tiny_world()
        for index in range(3):
            world.add(Actor(f"resolved-{index}", f"Resolved {index}", "south"))
        add_aggregate_population(world, AggregatePopulation("south-population", "south", 10, 30, 2))
        report = reconcile_population(world, "south-population")
        self.assertEqual(report, {"aggregate_population": 10, "resolved_local_people": 3, "unresolved": 7})

    def test_travel_is_not_a_teleport(self) -> None:
        world = build_tiny_world()
        actor = world.actors["merchant"]
        actor.schedule = [ScheduleEntry(0, 24, "go north", "north")]
        tick(world, 1)
        self.assertEqual(actor.location_id, "shop")
        self.assertEqual(actor.traveling_to, "north")
        tick(world, 48)
        self.assertEqual(actor.location_id, "north")

    def test_job_wages_expenses_and_interruption_change_the_same_actor(self) -> None:
        world = build_tiny_world()
        world.actors["merchant"].skills["trade"] = 1
        world.add(JobOpening("shopkeeper-job", "shop-market-cashier", "shopkeeper", 50, 8, 16, "trade"))
        hire(world, "merchant", "shopkeeper-job")
        starting_cash = world.actors["merchant"].money
        pay_wages(world, "shop-market-cashier")
        self.assertEqual(world.actors["merchant"].money, starting_cash + 50)
        charge_household_expense(world, "merchant", 10, expense="rent")
        self.assertEqual(world.actors["merchant"].money, starting_cash + 40)
        age_one_year(world, "merchant")
        self.assertEqual(world.actors["merchant"].age, 32)
        interrupt(world, "merchant", "visit sick daughter", "tavern", hours=2, reason="daughter became ill")
        tick(world, 1)
        self.assertEqual(world.actors["merchant"].current_activity, "visit sick daughter")


if __name__ == "__main__":
    unittest.main()
