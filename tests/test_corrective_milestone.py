import unittest
from datetime import datetime

from redos.audit import causal_chain, conservation_errors, market_balance_errors, validate_world
from redos.bootstrap import build_tiny_world
from redos.enterprise import allocate_contract, advance_shipments, create_contract, dispatch_contract, mule_bid, settle_contract
from redos.living import Bid, auction, propagate_information, recollect, tell, witness_event
from redos.market import buy, travel
from redos.model import Actor
from redos.employment import charge_household_expense, hire, pay_wages
from redos.model import JobOpening, ScheduleEntry
from redos.simulation import interrupt, interrupt_for_family_problem, tick


class CorrectiveMilestoneTests(unittest.TestCase):
    def test_transfers_do_not_create_goods_and_market_measurement_cannot_hide_divergence(self) -> None:
        world = build_tiny_world()
        world.create_lot("metals", 10, holder_id="shop", owner_id="shop")
        before = sum(lot.quantity for lot in world.lots.values() if lot.good_type_id == "metals")
        world.transfer_goods("metals", 4, from_holder="shop", to_holder="merchant", to_owner="merchant")
        after = sum(lot.quantity for lot in world.lots.values() if lot.good_type_id == "metals")
        self.assertEqual(before, after)
        self.assertFalse(conservation_errors(world))
        world.markets["shop-market"].balances["metals"] = 999
        self.assertTrue(market_balance_errors(world))
        self.assertTrue(validate_world(world))

    def test_contract_cargo_is_not_at_destination_until_shipment_arrives(self) -> None:
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id)
        contract = create_contract(world, seller.id, buyer.id, "metals", 2, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        dispatch_contract(world, contract.id)
        self.assertEqual(contract.status, "in_transit")
        with self.assertRaises(ValueError):
            settle_contract(world, contract.id)
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)
        self.assertEqual(world.location_of(contract.shipment_id), "shop")
        world.advance_hours(24)
        advance_shipments(world, 24)
        self.assertEqual(contract.status, "settled")
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 2)

    def test_contract_deadline_is_absolute_across_year_boundary(self) -> None:
        world = build_tiny_world()
        world.now = datetime(1770, 12, 31, 23)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 1, holder_id=seller.id, owner_id=seller.id)
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        self.assertEqual(contract.due_at, datetime(1771, 1, 2, 23))
        dispatch_contract(world, contract.id)
        world.advance_hours(24)
        advance_shipments(world, 24)
        self.assertLess(world.now, contract.due_at)
        self.assertEqual(contract.status, "settled")

    def test_contract_can_fail_without_creating_or_teleporting_cargo(self) -> None:
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        buyer.cash = 0
        world.create_lot("metals", 1, holder_id=seller.id, owner_id=seller.id)
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=1)
        dispatch_contract(world, contract.id)
        world.advance_hours(24)
        advance_shipments(world, 24)
        self.assertEqual(contract.status, "failed")
        self.assertEqual(contract.failure_reason, "buyer insolvent at delivery")
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1)
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)

    def test_obligations_reserve_stock_and_failed_sales_leave_money_untouched(self) -> None:
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 1, holder_id=seller.id, owner_id=seller.id)
        first = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=1)
        second = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=1)
        self.assertEqual(allocate_contract(world, first.id).status, "allocated")
        self.assertEqual(allocate_contract(world, second.id).status, "failed")
        before = buyer.cash
        with self.assertRaises(ValueError):
            mule_bid(world, buyer.id, seller.id, "medicine", 1, 100)
        self.assertEqual(buyer.cash, before)
        with self.assertRaises(ValueError):
            auction(world, buyer.id, "medicine", 1, [Bid(seller.id, 100)])
        self.assertEqual(buyer.cash, before)

    def test_shortage_creates_demand_pressure_without_creating_stock(self) -> None:
        world = build_tiny_world()
        market = world.markets["shop-market"]
        available = world.quantity_held("shop", "medicine")
        if available:
            world.consume_goods("shop", "medicine", available)
        before = world.quantity_held("shop", "medicine")
        backlog_before = market.demand_backlog["medicine"]
        with self.assertRaises(ValueError):
            buy(world, "merchant", market.id, "medicine", 1)
        self.assertEqual(world.quantity_held("shop", "medicine"), before)
        self.assertEqual(market.demand_backlog["medicine"], backlog_before + 1)
        self.assertTrue(any(event.kind == "unmet_demand" for event in world.events))

    def test_market_travel_starts_shared_movement_without_advancing_time(self) -> None:
        world = build_tiny_world()
        travel(world, "merchant", "north")
        self.assertEqual(world.now, datetime(1770, 1, 1))
        self.assertEqual(world.actors["merchant"].location_id, "shop")
        tick(world, 48)
        self.assertEqual(world.actors["merchant"].location_id, "north")

    def test_schedule_interruption_reduces_attendance_and_payroll(self) -> None:
        world = build_tiny_world()
        actor = world.actors["merchant"]
        actor.schedule = [ScheduleEntry(0, 24, "work", "shop")]
        world.add(JobOpening("full-day-job", "shop-market-cashier", "shopkeeper", 50, 0, 24))
        hire(world, actor.id, "full-day-job")
        actor.schedule = [ScheduleEntry(0, 24, "work", "shop")]
        for _ in range(8):
            tick(world, 1)
        interrupt(world, actor.id, "care for daughter", "shop", hours=4, reason="daughter became ill")
        for _ in range(12):
            tick(world, 1)
        paid = pay_wages(world, "shop-market-cashier")
        self.assertLess(actor.work_hours_by_day["1770-01-01"], 20)
        self.assertLess(paid, 50)
        self.assertTrue(any(event.kind == "schedule_interrupted" for event in world.events))

    def test_family_problem_flows_through_attendance_wages_and_household_debt(self) -> None:
        world = build_tiny_world()
        actor = world.actors["merchant"]
        actor.money = 0
        world.households[actor.household_id].cash = 0
        actor.schedule = [ScheduleEntry(0, 24, "work", "shop")]
        world.add(JobOpening("family-job", "shop-market-cashier", "shopkeeper", 50, 0, 24))
        hire(world, actor.id, "family-job")
        problem_id = interrupt_for_family_problem(
            world,
            actor.id,
            "care for daughter",
            "tavern",
            hours=24,
            description="daughter became ill",
        )
        for _ in range(8):
            tick(world, 1)
        pay_wages(world, "shop-market-cashier")
        missed = next(event for event in world.events if event.kind == "wage_missed")
        charge_household_expense(
            world,
            actor.id,
            40,
            expense="medical bill",
            causes=(missed.id,),
        )
        debt = next(event for event in world.events if event.kind == "debt")
        self.assertEqual(world.households[actor.household_id].debt, 40)
        chain = causal_chain(world, debt.id)
        self.assertEqual([event["kind"] for event in chain[:4]], ["debt", "wage_missed", "schedule_interrupted", "family_problem"])
        self.assertEqual(chain[-1]["id"], problem_id)

    def test_statement_does_not_rewrite_truth_or_cascade_forever(self) -> None:
        world = build_tiny_world()
        for actor_id in ("a", "b", "c"):
            world.add(Actor(actor_id, actor_id, "tavern"))
        event = world.record("incident", "a seal broke", entities=["dock"])
        observation = witness_event(world, event_id=event.id, content="the seal broke", witnesses=["a"])[0]
        recollect(world, observation.id, content="someone touched the seal", confidence=0.4)
        world.actors["a"].beliefs["seal"] = "someone touched the seal"
        first = propagate_information(world, proposition="seal", location_id="tavern")
        self.assertTrue(first)
        self.assertEqual({statement.speaker_id for statement in first}, {"a"})
        second = propagate_information(world, proposition="seal", location_id="tavern")
        self.assertFalse(second)
        self.assertEqual(next(item for item in world.events if item.id == event.id).description, "a seal broke")
        self.assertNotEqual(world.actors["b"].beliefs["seal"], "the seal broke")


if __name__ == "__main__":
    unittest.main()
