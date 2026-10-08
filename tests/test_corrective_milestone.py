import unittest
from copy import deepcopy
from datetime import datetime

from redos.audit import causal_chain, conservation_errors, market_balance_errors, validate_world
from redos.bootstrap import build_tiny_world
from redos.enterprise import allocate_contract, advance_shipments, create_contract, dispatch_contract, mule_bid, settle_contract
from redos.living import Bid, auction, meet, propagate_information, recollect, revise_belief, tell, witness_event
from redos.market import autonomous_trade, buy, refresh_market, travel
from redos.model import Actor, Place, Route
from redos.employment import charge_household_expense, hire, pay_wages
from redos.model import JobOpening, ScheduleEntry
from redos.runtime import _adjudicate_food_need, _complete_food_task, adjudicate_hour
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
        self.assertEqual(world.quantity_held(seller.id, "metals"), 0)
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)
        self.assertEqual(world.shipments[contract.shipment_id].status, "returning")
        for _ in range(24):
            advance_shipments(world, 1)
        self.assertEqual(world.shipments[contract.shipment_id].status, "returned")
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1)

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

    def test_bulk_and_hourly_ticks_complete_the_same_multileg_journey(self) -> None:
        def prepare():
            world = build_tiny_world()
            world.routes.pop("shop-north")
            world.add(Place("waypoint", "Way Point", 1))
            world.add(Route("shop-waypoint", "shop", "waypoint", 1.0, 1))
            world.add(Route("waypoint-north", "waypoint", "north", 1.0, 1))
            travel(world, "merchant", "north")
            return world

        bulk = prepare()
        hourly = prepare()
        tick(bulk, 48)
        for _ in range(48):
            tick(hourly, 1)
        self.assertEqual(bulk.actors["merchant"].location_id, "north")
        self.assertEqual(hourly.actors["merchant"].location_id, "north")
        self.assertEqual(bulk.actors["merchant"].journey_destination_id, hourly.actors["merchant"].journey_destination_id)

    def test_autonomous_trade_completes_all_route_legs(self) -> None:
        world = build_tiny_world()
        world.routes.pop("shop-north")
        world.add(Place("waypoint", "Way Point", 1))
        world.add(Route("shop-waypoint", "shop", "waypoint", 1.0, 1))
        world.add(Route("waypoint-north", "waypoint", "north", 1.0, 1))
        world.create_lot("medicine", 1, holder_id="shop", owner_id="shop-market-cashier")
        north_stock = world.quantity_held("north", "medicine")
        result = autonomous_trade(world, "merchant", "shop-market", "north", "medicine", 1)
        self.assertEqual(world.actors["merchant"].location_id, "north")
        self.assertIsNone(world.actors["merchant"].journey_destination_id)
        self.assertEqual(sum(event.kind == "travel_started" for event in world.events), 2)
        self.assertEqual(world.quantity_held("merchant", "medicine"), 0)
        self.assertEqual(result["destination_stock"], north_stock + 1)

    def test_food_stays_with_shopper_until_the_shopper_reaches_home(self) -> None:
        from redos.vertical import build_integrated_world

        slice_state = build_integrated_world()
        world = slice_state.world
        actor = world.actors["citizen-0"]
        household = world.households[actor.household_id]
        actor.location_id = "shop"
        actor.active_task = "acquire food"
        actor.task_target_location_id = "shop"
        _complete_food_task(world, actor)
        self.assertEqual(world.quantity_held(actor.id, "bread"), 1)
        self.assertEqual(world.quantity_held(household.id, "bread"), 0)
        while actor.traveling_to is not None or actor.location_id != household.residence_id:
            tick(world, 1)
            _complete_food_task(world, actor)
        self.assertEqual(world.quantity_held(actor.id, "bread"), 0)
        self.assertEqual(world.quantity_held(household.id, "bread"), 1)

    def test_food_need_does_not_preempt_work_or_duplicate_a_returning_shopper(self) -> None:
        world = build_tiny_world()
        actor = world.actors["merchant"]
        actor.schedule = [ScheduleEntry(0, 24, "work", "shop")]
        actor.current_activity = "work"
        _adjudicate_food_need(world)
        self.assertIsNone(actor.active_task)
        actor.current_activity = "at home"
        actor.active_task = "return with food"
        _adjudicate_food_need(world)
        self.assertEqual(actor.active_task, "return with food")

    def test_market_refresh_requires_an_explicit_production_source(self) -> None:
        world = build_tiny_world()
        market = world.markets["shop-market"]
        market.production_source = None
        before_stock = world.quantity_held(market.place_id, "medicine")
        before_balances = deepcopy(market.balances)
        before_backlog = deepcopy(market.demand_backlog)
        before_history = deepcopy(market.price_history)
        before_day = market.last_updated_day
        before_events = len(world.events)
        with self.assertRaises(ValueError):
            refresh_market(world, market.id)
        self.assertEqual(world.quantity_held(market.place_id, "medicine"), before_stock)
        self.assertEqual(market.balances, before_balances)
        self.assertEqual(market.demand_backlog, before_backlog)
        self.assertEqual(market.price_history, before_history)
        self.assertEqual(market.last_updated_day, before_day)
        self.assertEqual(len(world.events), before_events)

    def test_encounters_are_bounded_and_information_uses_only_encounter_edges(self) -> None:
        world = build_tiny_world()
        for actor_id in ("a", "b", "c", "d", "e", "f"):
            world.add(Actor(actor_id, actor_id, "tavern"))
            world.actors[actor_id].current_activity = "visit tavern"
        adjudicate_hour(world)
        self.assertEqual(sum(event.kind == "meeting" for event in world.events), 3)
        world.actors["a"].beliefs["seal"] = "the seal broke"
        world.runtime["active_encounters"] = (("a", "b"), ("c", "d"))
        world.runtime["active_encounter_at"] = world.now
        statements = propagate_information(world, proposition="seal", location_id="tavern")
        self.assertEqual({statement.listener_id for statement in statements}, {"b"})
        self.assertNotIn("seal", world.actors["d"].beliefs)

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
        first = propagate_information(world, proposition="seal", location_id="tavern", encounter_pairs=(("a", "b"),))
        self.assertTrue(first)
        self.assertEqual({statement.speaker_id for statement in first}, {"a"})
        second = propagate_information(world, proposition="seal", location_id="tavern", encounter_pairs=(("a", "b"),))
        self.assertFalse(second)
        self.assertEqual(next(item for item in world.events if item.id == event.id).description, "a seal broke")
        self.assertNotEqual(world.actors["b"].beliefs["seal"], "the seal broke")

    def test_false_testimony_keeps_provenance_across_multiple_relays(self) -> None:
        world = build_tiny_world()
        for actor_id in ("a", "b", "c", "d"):
            world.add(Actor(actor_id, actor_id, "tavern"))
        tell(world, "a", "b", "seal", "the seal broke", truthful=False)
        first = propagate_information(world, proposition="seal", location_id="tavern", encounter_pairs=(("b", "c"),))
        second = propagate_information(world, proposition="seal", location_id="tavern", encounter_pairs=(("c", "d"),))
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertFalse(first[0].truthful)
        self.assertFalse(second[0].truthful)

    def test_new_direct_observation_replaces_old_belief_provenance(self) -> None:
        world = build_tiny_world()
        for actor_id in ("a", "b", "c"):
            world.add(Actor(actor_id, actor_id, "tavern"))
        tell(world, "a", "b", "seal", "the seal broke", truthful=False)
        revise_belief(
            world,
            "b",
            "seal",
            "the seal was intact",
            truthful=True,
            source_kind="observation",
            source_id="observation-direct",
        )
        statements = propagate_information(world, proposition="seal", location_id="tavern", encounter_pairs=(("b", "c"),))
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].truthful)

    def test_fractional_ticks_credit_actual_work_duration(self) -> None:
        world = build_tiny_world()
        actor = world.actors["cooper"]
        actor.schedule = [ScheduleEntry(0, 24, "work", "workshop")]
        tick(world, 1.5)
        self.assertAlmostEqual(actor.work_hours_by_day["1770-01-01"], 1.5)


if __name__ == "__main__":
    unittest.main()
