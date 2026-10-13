import copy
import gzip
import hashlib
import json
from datetime import timedelta
import tempfile
from pathlib import Path
import unittest

from redos.audit import conservation_errors, money_totals, validate_world
from redos.actions import move
from redos.community_fixture import build_household_world
from redos.households import advance_household_support, cancel_support, change_household_membership, change_household_residence, recover_household_goods, settle_obligation
from redos.market import buy
from redos.model import Obligation
from redos.persistence import _payload_for, load_snapshot, save_snapshot
from redos.runtime import advance_world, run


class HouseholdObligationTests(unittest.TestCase):
    def test_relocation_from_market_preserves_private_stock_and_physical_recovery(self) -> None:
        world = build_household_world(seed=91).world
        household = world.households["merchant-household"]
        change_household_residence(world, household.id, "shop")
        lot = world.create_lot("metals", 2.0, holder_id=household.id, owner_id=household.id)
        public_before = world.quantity_held("shop", "metals")
        change_household_residence(world, household.id, "home-a")
        self.assertEqual(world.quantity_held("shop", "metals"), public_before)
        self.assertEqual(world.markets["shop-market"].balances["metals"], public_before)
        self.assertEqual(world.location_of(lot.holder_id), "shop")
        self.assertNotEqual(lot.holder_id, "shop")
        buy(world, "merchant", "shop-market", "metals", 1)
        self.assertEqual(lot.quantity, 2.0)
        world.move_actor("citizen-8", "shop", reason="fixture stranger is co-located with storage")
        before = _payload_for(world)
        with self.assertRaises(PermissionError):
            recover_household_goods(world, "citizen-8", lot.holder_id, "metals", 1)
        self.assertEqual(_payload_for(world), before)
        move(world, "merchant", "wall-street")
        before = _payload_for(world)
        with self.assertRaisesRegex(ValueError, "stationary co-location"):
            recover_household_goods(world, "merchant", lot.holder_id, "metals", 1)
        self.assertEqual(_payload_for(world), before)
        advance_world(world, 1)
        move(world, "merchant", "shop")
        advance_world(world, 1)
        recovered = recover_household_goods(world, "merchant", lot.holder_id, "metals", 1)
        self.assertEqual(lot.quantity, 1.0)
        self.assertTrue(all(world.lots[lot_id].owner_id == household.id for lot_id in recovered))
        self.assertIn("household_residence_changed", {event.kind for event in world.explain(world.events[-1].id)})
        self.assertEqual(validate_world(world), [])
        self.assertEqual(conservation_errors(world), [])
    def test_cancellation_preserves_unprocessed_past_periods_and_rejects_duplicates(self) -> None:
        world = build_household_world(seed=88).world
        duty = world.support_duties["household-support"]
        first_due = duty.next_due_at
        world.advance_hours(48)
        cancel_support(world, duty.id)
        self.assertEqual(len(world.obligations), 3)
        self.assertEqual({o.due_at for o in world.obligations.values()}, {first_due + timedelta(hours=24*i) for i in range(3)})
        advance_household_support(world)
        self.assertTrue(all(o.status == "settled" for o in world.obligations.values()))
        before = _payload_for(world)
        with self.assertRaises(ValueError):
            world.add(Obligation("duplicate-period", duty.supporter_id, duty.household_id,
                                 duty.jurisdiction_place_id, duty.amount, first_due, duty.id))
        self.assertEqual(_payload_for(world), before)

    def test_direct_registration_cannot_charge_a_period_twice(self) -> None:
        world = build_household_world(seed=90).world
        duty = world.support_duties["household-support"]
        obligation = Obligation(f"support:{duty.id}:{duty.next_due_at.isoformat()}", duty.supporter_id,
                                duty.household_id, duty.jurisdiction_place_id, duty.amount, duty.next_due_at, duty.id)
        world.add(obligation)
        before = _payload_for(world)
        with self.assertRaisesRegex(ValueError, "canonical obligation ID"):
            world.add(Obligation("second-record-same-period", duty.supporter_id, duty.household_id,
                                 duty.jurisdiction_place_id, duty.amount, duty.next_due_at, duty.id))
        self.assertEqual(_payload_for(world), before)
        previous_cash = world.actors[duty.supporter_id].money
        advance_household_support(world)
        self.assertEqual(len(world.obligations), 1)
        self.assertEqual(previous_cash - world.actors[duty.supporter_id].money, duty.amount)

    def test_future_support_obligation_ids_cannot_be_claimed_by_other_records(self) -> None:
        from dataclasses import replace
        from redos.model import Actor

        world = build_household_world(seed=89).world
        tie = next(iter(world.social_ties.values()))
        future_id = "support:household-support:1770-01-02T00:00:00"
        before = _payload_for(world)
        for candidate in (replace(tie, id=future_id), Actor(future_id, "Conflicting actor", "shop")):
            with self.assertRaisesRegex(ValueError, "reserved"):
                world.add(candidate)
            self.assertEqual(_payload_for(world), before)

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
