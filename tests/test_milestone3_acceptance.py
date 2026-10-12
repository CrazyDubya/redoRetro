import json
from time import perf_counter
import unittest

from redos.actions import inspect as inspect_object, move, purchase
from redos.market import quote
from redos.persistence import execute_once
from redos.model import ScheduleEntry
from redos.runtime import advance_world, run
from redos.streets import build_street_world, street_audit
from redos.vertical import default_dock_incident


class Milestone3AcceptanceTests(unittest.TestCase):
    def test_thirty_day_street_audit_is_canonical_and_machine_readable(self) -> None:
        state = build_street_world(seed=51)
        started = perf_counter()
        world = run(state.world, 30, external_events=(default_dock_incident(state),))
        elapsed = perf_counter() - started
        report = street_audit(world)

        self.assertEqual(world.now.day, 31)
        self.assertEqual(report["schema"], "redos.street-audit.v1")
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])
        self.assertEqual(report["invariants"]["market_balance_errors"], [])
        self.assertGreater(report["events"].get("movement", 0), 20)
        self.assertGreater(report["events"].get("work", 0), 100)
        self.assertGreater(report["events"].get("meeting", 0), 20)
        self.assertGreaterEqual(len(report["incident_beliefs"]), 2)
        self.assertGreaterEqual(len(set(report["incident_beliefs"].values())), 2)
        self.assertGreaterEqual(len(report["district"]["street_nodes"]), 12)
        self.assertGreater(elapsed, 0.0)
        self.assertLess(elapsed, 60.0)
        json.dumps(report)

    def test_same_seed_player_command_tape_changes_the_canonical_world(self) -> None:
        baseline = build_street_world(seed=52).world
        intervened = build_street_world(seed=52).world

        execute_once(
            baseline,
            "tape-inspect-shop",
            inspect_object,
            baseline,
            "merchant",
            "shop-counter",
        )
        execute_once(
            intervened,
            "tape-inspect-shop",
            inspect_object,
            intervened,
            "merchant",
            "shop-counter",
        )
        execute_once(
            intervened,
            "tape-buy-metals",
            purchase,
            intervened,
            "merchant",
            "shop-market",
            "metals",
            1.0,
        )
        execute_once(
            intervened,
            "tape-move-exchange",
            move,
            intervened,
            "merchant",
            "royal-exchange",
        )
        for _ in range(6):
            from redos.runtime import advance_world

            advance_world(baseline, 1)
            advance_world(intervened, 1)

        # The intervention must continue to affect the autonomous economy,
        # not only the player's immediate balance and inventory.  The shop's
        # market cashier has a different post-run balance after the same
        # runtime has adjudicated the changed market state.
        for _ in range(42):
            advance_world(baseline, 1)
            advance_world(intervened, 1)

        self.assertEqual(baseline.seed, intervened.seed)
        self.assertNotEqual(
            baseline.actors["merchant"].money,
            intervened.actors["merchant"].money,
        )
        self.assertGreater(intervened.quantity_held("merchant", "metals"), baseline.quantity_held("merchant", "metals"))
        baseline_quote = quote(baseline, "shop-market", "metals", 1.0, side="buy")
        intervened_quote = quote(intervened, "shop-market", "metals", 1.0, side="buy")
        self.assertNotEqual(baseline_quote.unit_price, intervened_quote.unit_price)
        self.assertTrue(any(event.kind == "market_refresh" for event in intervened.events))

    def test_player_movement_wins_over_schedule_and_household_need(self) -> None:
        world = build_street_world(seed=53).world
        player = world.actors["merchant"]
        player.schedule = [ScheduleEntry(0, 24, "work", "shop", priority=10, interruptible=False)]
        household = world.households[player.household_id]
        if world.quantity_held(household.id, "bread"):
            world.consume_goods(household.id, "bread", world.quantity_held(household.id, "bread"), reason="player-control test")

        move(world, player.id, "royal-exchange")
        for _ in range(3):
            advance_world(world, 1)

        self.assertEqual(player.location_id, "royal-exchange")
        self.assertIsNone(player.traveling_to)
        self.assertIsNone(player.active_task)
        self.assertIsNone(player.schedule_override_until)


if __name__ == "__main__":
    unittest.main()
