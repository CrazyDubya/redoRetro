import copy
import gzip
import hashlib
import json
from datetime import timedelta
import tempfile
from pathlib import Path
import unittest

from redos.audit import conservation_errors, money_totals, validate_world
from redos.community_fixture import build_household_world
from redos.households import advance_household_support, cancel_support, change_household_membership, change_household_residence, settle_obligation
from redos.model import Obligation
from redos.persistence import _payload_for, load_snapshot, save_snapshot
from redos.runtime import advance_world, run


class HouseholdObligationTests(unittest.TestCase):
    def test_actual_schema3_snapshot_preserves_next_day_after_migration(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "m4-schema3.sqlite3.gz"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schema3.sqlite3"
            path.write_bytes(gzip.decompress(fixture.read_bytes()))
            world = load_snapshot(path)
        def old_digest():
            document = json.loads(_payload_for(world))
            document["schema_version"] = 3
            for name in ("support_duties", "obligations"):
                del document["world"]["fields"][name]
            for _key, household in document["world"]["fields"]["households"]["items"]:
                del household["fields"]["arrangement"]
            return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(old_digest(), "74d0be6909ce08c629e3e7e6f4e7f1933d65f8fc7c06f13b61b92fdcc930166b")
        advance_world(world, 24)
        self.assertEqual(old_digest(), "b2784343794ddae34421206a0c6a6eec490ffc8bf2f40fe51ec7742d1c97b288")

    def test_support_changes_actual_acquisition_and_consumption_over_thirty_days(self) -> None:
        supported = build_household_world(seed=81).world
        withdrawn = copy.deepcopy(supported)
        cancel_support(withdrawn, "household-support")
        initial_cash = money_totals(supported)["total"]
        run(supported, 30)
        run(withdrawn, 30)
        supported_meals = [event for event in supported.events if event.kind == "meal" and "household-c" in event.entities]
        withdrawn_meals = [event for event in withdrawn.events if event.kind == "meal" and "household-c" in event.entities]
        self.assertGreater(len(supported_meals), len(withdrawn_meals))
        self.assertGreater(len(supported.obligations), 20)
        self.assertTrue(all(obligation.status == "settled" for obligation in supported.obligations.values()))
        self.assertEqual(validate_world(supported), [])
        self.assertEqual(validate_world(withdrawn), [])
        self.assertEqual(conservation_errors(supported), [])
        self.assertEqual(conservation_errors(withdrawn), [])
        self.assertAlmostEqual(money_totals(supported)["total"], initial_cash)
        self.assertAlmostEqual(money_totals(withdrawn)["total"], initial_cash)
        allowance = next(event for event in supported.events if event.kind == "payment" and event.description == "household food acquisition allowance")
        self.assertIn("obligation_created", {event.kind for event in supported.explain(allowance.id)})
        self.assertTrue(any("obligation_created" in {cause.kind for cause in supported.explain(meal.id)} for meal in supported_meals))

    def test_cancelled_support_keeps_arrears_and_can_settle_once(self) -> None:
        world = build_household_world(seed=82).world
        debtor = world.actors["citizen-0"]
        world.pay(debtor.id, "warehouse-business", debtor.money)
        advance_household_support(world)
        obligation = next(iter(world.obligations.values()))
        self.assertEqual(obligation.status, "defaulted")
        self.assertEqual(debtor.debt, 48.0)
        change_household_membership(world, debtor.id, "household-b")
        self.assertEqual(obligation.debtor_id, debtor.id)
        self.assertEqual(obligation.creditor_id, "household-c")
        self.assertEqual(debtor.debt, 48.0)
        cancel_support(world, "household-support")
        world.pay("warehouse-business", debtor.id, 48.0)
        self.assertEqual(settle_obligation(world, obligation.id, amount=12.0), 12.0)
        self.assertEqual(debtor.debt, 36.0)
        advance_household_support(world)
        self.assertEqual(obligation.status, "settled")
        self.assertEqual(debtor.debt, 0.0)
        before = _payload_for(world)
        self.assertEqual(settle_obligation(world, obligation.id), 0.0)
        self.assertEqual(_payload_for(world), before)
        self.assertEqual(len(world.obligations), 1)

    def test_invalid_or_unaffordable_obligations_do_not_mutate(self) -> None:
        world = build_household_world(seed=83).world
        before = _payload_for(world)
        with self.assertRaisesRegex(ValueError, "signed source"):
            world.add(Obligation("wrong-creditor", "citizen-0", "merchant", "home-c", 48.0, world.now, "household-support"))
        self.assertEqual(_payload_for(world), before)
        advance_household_support(world)
        world.pay("citizen-0", "warehouse-business", world.actors["citizen-0"].money)
        # A new due date is distinct from the already settled first period.
        world.now += timedelta(days=1)
        advance_household_support(world)
        obligation = list(world.obligations.values())[-1]
        before = _payload_for(world)
        with self.assertRaises(ValueError):
            settle_obligation(world, obligation.id)
        self.assertEqual(_payload_for(world), before)

    def test_membership_and_residence_preserve_people_goods_and_arrears(self) -> None:
        world = build_household_world(seed=84).world
        actor = world.actors["citizen-8"]
        previous_location = actor.location_id
        change_household_membership(world, actor.id, "household-a")
        self.assertNotIn(actor.id, world.households["household-c"].members)
        self.assertIn(actor.id, world.households["household-a"].members)
        self.assertEqual(actor.location_id, previous_location)
        before = _payload_for(world)
        with self.assertRaises(KeyError):
            change_household_membership(world, actor.id, "missing-household")
        self.assertEqual(_payload_for(world), before)
        household = world.households["household-a"]
        lot = world.create_lot("bread", 2, holder_id=household.id, owner_id=household.id)
        old_residence = household.residence_id
        change_household_residence(world, household.id, "home-b")
        self.assertEqual(world.location_of(lot.holder_id), old_residence)
        self.assertEqual(lot.owner_id, household.id)
        self.assertEqual(actor.location_id, previous_location)
        self.assertEqual(validate_world(world), [])

    def test_membership_cannot_redirect_an_existing_household_purchase(self) -> None:
        world = build_household_world(seed=86).world
        actor = world.actors["citizen-8"]
        actor.active_task = "return with food"
        actor.task_target_location_id = "home-c"
        before = _payload_for(world)
        with self.assertRaisesRegex(ValueError, "existing household acquisition"):
            change_household_membership(world, actor.id, "household-a")
        self.assertEqual(_payload_for(world), before)
        change_household_residence(world, "household-c", "home-b")
        self.assertEqual(actor.task_target_location_id, "home-b")
        self.assertNotEqual(actor.location_id, "home-b")

    def test_hourly_bulk_and_restart_preserve_support_state(self) -> None:
        hourly = build_household_world(seed=85).world
        bulk = copy.deepcopy(hourly)
        for _ in range(48):
            advance_world(hourly, 1)
        advance_world(bulk, 24)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "households.sqlite3"
            save_snapshot(bulk, path)
            bulk = load_snapshot(path)
        advance_world(bulk, 24)
        self.assertEqual(_payload_for(bulk), _payload_for(hourly))


if __name__ == "__main__":
    unittest.main()
