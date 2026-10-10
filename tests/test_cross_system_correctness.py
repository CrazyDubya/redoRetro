import math
import unittest

from redos.audit import validate_world
from redos.bank import charge_account_fee, deposit, open_account, originate_loan, repay_loan
from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract, dispatch_contract
from redos.insider import execute_trade, issue_security
from redos.insurance import approve_claim, file_claim, insurer_exposure, issue_policy, record_loss
from redos.model import Business, TransportAsset, TransportFacility, TransportService
from redos.ocean import book_ocean_trade, quote_ocean_trade
from redos.runtime import advance_world
from redos.transport import (
    add_asset,
    add_facility,
    add_service,
    advance_freight,
    dispatch_freight,
    replenish_asset,
    resolve_failed_cargo,
)


class CrossSystemCorrectnessTests(unittest.TestCase):
    def test_self_payment_is_rejected_without_minting_money(self):
        world = build_tiny_world(seed=200)
        holder = world.businesses["warehouse-business"]
        before = holder.cash
        with self.assertRaises(ValueError):
            world.pay(holder.id, holder.id, 10.0)
        with self.assertRaises(ValueError):
            world.pay(holder.id, holder.id, 1e-12)
        self.assertEqual(holder.cash, before)

    def test_non_finite_canonical_inputs_are_rejected_before_mutation(self):
        world = build_tiny_world(seed=2001)
        seller = world.businesses["shop-market-cashier"]
        before_lots = dict(world.lots)
        with self.assertRaises(ValueError):
            world.consume_goods(seller.id, "metals", math.nan)
        self.assertEqual(world.lots, before_lots)
        with self.assertRaises(ValueError):
            create_contract(world, seller.id, "warehouse-business", "metals", math.inf, 10.0, origin_id="shop", destination_id="warehouse", due_days=1)
        self.assertEqual(world.contracts, {})

    def test_bank_fee_and_interest_use_the_correct_side_of_the_ledger(self):
        world = build_tiny_world(seed=201)
        world.add(Business("bank", "Harbor Bank", "shop", "bank", cash=1_000.0))
        customer = world.businesses["warehouse-business"]
        customer.cash = 200.0
        account = open_account(world, "bank", customer.id, annual_interest_rate=0.365, service_charge=10.0, account_id="acct")
        deposit(world, account.id, 100.0)
        world.advance(days=10)
        deposit(world, account.id, 100.0)
        world.advance(days=10)
        charge_account_fee(world, account.id)
        self.assertAlmostEqual(account.balance, 193.01, places=6)
        self.assertAlmostEqual(customer.cash, 0.0, places=6)
        self.assertAlmostEqual(world.businesses["bank"].cash, 1_200.0, places=6)

    def test_final_loan_repayment_accrues_elapsed_interest(self):
        world = build_tiny_world(seed=202)
        world.add(Business("bank", "Harbor Bank", "shop", "bank", cash=1_000.0))
        borrower = world.businesses["warehouse-business"]
        borrower.cash = 300.0
        loan = originate_loan(world, "bank", borrower.id, 200.0, annual_interest_rate=0.365, loan_id="loan")
        world.advance(days=10)
        self.assertAlmostEqual(repay_loan(world, loan.id, 202.0), 202.0, places=6)
        self.assertEqual(loan.status, "repaid")
        self.assertAlmostEqual(loan.accrued_interest, 0.0, places=6)

    def test_insurance_claim_is_bound_to_loss_time_and_loss_identity(self):
        world = build_tiny_world(seed=203)
        world.add(Business("insurer", "Harbor Mutual", "shop", "insurer", cash=500.0))
        customer = world.businesses["warehouse-business"]
        customer.cash = 300.0
        before_policy = world.record("fire", "customer stock burned before coverage", actors=[customer.id])
        world.advance(days=1)
        policy = issue_policy(world, "insurer", customer.id, line="cargo", region_id="warehouse", premium=10.0, coverage_limit=100.0, policy_id="policy")
        with self.assertRaises(ValueError):
            file_claim(world, policy.id, loss_event_id=before_policy.id, loss_amount=20.0)
        loss = record_loss(world, customer.id, loss_kind="fire", covered_risk="cargo", location_id="warehouse", verified_loss_amount=60.0, description="customer stock burned")
        claim = file_claim(world, policy.id, loss_event_id=loss.id, loss_amount=60.0, claim_id="claim")
        with self.assertRaises(ValueError):
            file_claim(world, policy.id, loss_event_id=loss.id, loss_amount=60.0, claim_id="claim-again")
        approve_claim(world, claim.id)
        world.advance(days=31)
        self.assertEqual(insurer_exposure(world, "insurer")["approved_claims"], 60.0)

    def test_insurance_rejects_non_loss_events_and_unverified_excess(self):
        world = build_tiny_world(seed=2031)
        world.add(Business("insurer", "Harbor Mutual", "shop", "insurer", cash=500.0))
        customer = world.businesses["warehouse-business"]
        customer.cash = 300.0
        policy = issue_policy(world, "insurer", customer.id, line="cargo", region_id="warehouse", premium=10.0, coverage_limit=100.0, policy_id="policy")
        with self.assertRaises(ValueError):
            file_claim(world, policy.id, loss_event_id=next(event.id for event in world.events if event.kind == "policy_issued"), loss_amount=20.0)
        loss = record_loss(world, customer.id, loss_kind="theft", covered_risk="cargo", location_id="warehouse", verified_loss_amount=40.0, description="verified cargo damage")
        with self.assertRaises(ValueError):
            file_claim(world, policy.id, loss_event_id=loss.id, loss_amount=41.0)

    def test_services_advance_on_the_normal_world_clock(self):
        world = build_tiny_world(seed=204)
        owner = world.businesses["warehouse-business"]
        add_asset(world, TransportAsset("clock-cart", "Clock Cart", "cart", "shop", owner.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_service(world, TransportService("clock-service", "clock-cart", ("shop", "tavern"), timetable_hours=(24.0,)))
        advance_world(world, 24)
        self.assertEqual(world.transport_assets["clock-cart"].location_id, "tavern")
        self.assertEqual(world.transport_services["clock-service"].current_stop_index, 1)

    def test_freight_and_service_share_one_world_clock_hour(self):
        world = build_tiny_world(seed=2041)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("shared-clock",))
        add_asset(world, TransportAsset("shared-cart", "Shared Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_service(world, TransportService("shared-service", "shared-cart", ("shop", "tavern"), timetable_hours=(24.0,)))
        add_facility(world, TransportFacility("shared-origin", "shop", 1))
        add_facility(world, TransportFacility("shared-destination", "tavern", 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="tavern", due_days=2)
        shipment = dispatch_freight(world, contract.id, carrier_id="shared-cart", origin_facility_id="shared-origin", destination_facility_id="shared-destination", service_id="shared-service")
        advance_world(world, 1)
        self.assertEqual(shipment.status, "in_transit")
        self.assertEqual(world.transport_services["shared-service"].current_stop_index, 0)

    def test_standalone_freight_does_not_suppress_the_next_service_tick(self):
        world = build_tiny_world(seed=2042)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("service-clock",))
        add_asset(world, TransportAsset("service-cart", "Service Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_service(world, TransportService("service-clock", "service-cart", ("shop", "tavern"), timetable_hours=(24.0,)))
        add_facility(world, TransportFacility("service-origin", "shop", 1))
        add_facility(world, TransportFacility("service-destination", "tavern", 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="tavern", due_days=2)
        dispatch_freight(world, contract.id, carrier_id="service-cart", origin_facility_id="service-origin", destination_facility_id="service-destination", service_id="service-clock")
        advance_freight(world, 50)
        advance_world(world, 1)
        self.assertGreater(world.transport_services["service-clock"].journey_elapsed_hours, 0.0)

    def test_legacy_dispatch_moves_origin_owned_market_custody_before_shipment(self):
        world = build_tiny_world(seed=2043)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id="shop", owner_id=seller.id, provenance=("legacy-origin-custody",))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="north", due_days=2)
        dispatch_contract(world, contract.id)
        self.assertIsNotNone(contract.shipment_id)
        self.assertEqual(world.quantity_held(contract.shipment_id, "metals"), 1.0)

    def test_cargo_recovery_advances_through_normal_world_clock(self):
        world, seller, shipment = self._failed_freight_world()
        advance_freight(world, 50)
        self.assertTrue(resolve_failed_cargo(world, shipment.id))
        advance_world(world, 25)
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1.0)
        self.assertEqual(world.quantity_held("recovery-cart", "metals"), 0.0)

    def test_service_vehicle_cannot_be_double_booked_while_in_transit(self):
        world = build_tiny_world(seed=209)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("service-reservation",))
        add_asset(world, TransportAsset("reserved-cart", "Reserved Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_service(world, TransportService("reserved-service", "reserved-cart", ("shop", "tavern"), timetable_hours=(24.0,)))
        advance_world(world, 1)
        add_facility(world, TransportFacility("reserved-origin", "shop", 1))
        add_facility(world, TransportFacility("reserved-destination", "warehouse", 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="warehouse", due_days=2)
        with self.assertRaises(ValueError):
            dispatch_freight(world, contract.id, carrier_id="reserved-cart", origin_facility_id="reserved-origin", destination_facility_id="reserved-destination")
        self.assertEqual(contract.status, "open")
        self.assertEqual(world.shipments, {})

    def _failed_freight_world(self, *, fuel: float = 100.0):
        world = build_tiny_world(seed=205)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        seller.cash = 500_000.0
        buyer.cash = 0.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("recovery-test",))
        add_asset(world, TransportAsset("recovery-cart", "Recovery Cart", "cart", "shop", seller.id, capacity=1, fuel=fuel, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("recovery-origin", "shop", 1))
        add_facility(world, TransportFacility("recovery-destination", "warehouse", 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="warehouse", due_days=2)
        shipment = dispatch_freight(world, contract.id, carrier_id="recovery-cart", origin_facility_id="recovery-origin", destination_facility_id="recovery-destination")
        return world, seller, shipment

    def test_failed_cargo_returns_by_physical_journey(self):
        world, seller, shipment = self._failed_freight_world()
        advance_freight(world, 50)
        self.assertEqual(shipment.status, "failed")
        self.assertEqual(world.quantity_held("recovery-cart", "metals"), 1.0)
        self.assertTrue(resolve_failed_cargo(world, shipment.id))
        self.assertEqual(world.quantity_held(seller.id, "metals"), 0.0)
        self.assertEqual(world.transport_assets["recovery-cart"].assignment_kind, "cargo_recovery")
        advance_freight(world, 25)
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1.0)
        self.assertEqual(world.quantity_held("recovery-cart", "metals"), 0.0)

    def test_mid_route_failure_cannot_teleport_cargo_to_seller(self):
        world, seller, shipment = self._failed_freight_world(fuel=0.35)
        advance_freight(world, 5)
        self.assertEqual(shipment.status, "failed")
        self.assertTrue(resolve_failed_cargo(world, shipment.id))
        self.assertEqual(world.quantity_held(seller.id, "metals"), 0.0)
        self.assertEqual(world.quantity_held("recovery-cart", "metals"), 1.0)
        replenish_asset(world, "recovery-cart", "fuel", 10.0)
        advance_freight(world, 30)
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1.0)
        self.assertEqual(world.quantity_held("recovery-cart", "metals"), 0.0)

    def test_ocean_booking_rejection_does_not_mutate_cargo_or_create_contract(self):
        world = build_tiny_world(seed=206)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("booking-test",))
        world.create_lot("metals", 1.0, holder_id="shop", owner_id=seller.id, provenance=("booking-port-stock",))
        add_asset(world, TransportAsset("booking-cart", "Booking Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        trade = quote_ocean_trade(world, "shop-market", "north-market", "metals", "booking-cart", quantity=1)
        before_events = len(world.events)
        before_shop_stock = world.quantity_held("shop", "metals")
        with self.assertRaises(KeyError):
            book_ocean_trade(world, trade, seller_id=seller.id, buyer_id=buyer.id, origin_facility_id="missing-origin", destination_facility_id="missing-destination", due_days=2)
        self.assertEqual(len(world.shipments), 0)
        self.assertEqual(len(world.contracts), 0)
        self.assertEqual(world.quantity_held("shop", "metals"), before_shop_stock)
        self.assertEqual(len(world.events), before_events + 1)
        self.assertFalse(any(event.kind in {"contract_signed", "goods_transfer"} for event in world.events[before_events:]))
        self.assertTrue(any(event.kind == "booking_rejected" for event in world.events))

    def test_ocean_quote_and_booking_use_one_owned_market_lot(self):
        world = build_tiny_world(seed=208)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id="shop", owner_id=seller.id, provenance=("single-market-lot",))
        world.markets["north-market"].demand_backlog["metals"] = 20.0
        add_asset(world, TransportAsset("single-lot-cart", "Single Lot Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("single-lot-origin", "shop", 1))
        add_facility(world, TransportFacility("single-lot-destination", "north", 1))
        trade = quote_ocean_trade(world, "shop-market", "north-market", "metals", "single-lot-cart", quantity=1)
        shipment = book_ocean_trade(world, trade, seller_id=seller.id, buyer_id=buyer.id, origin_facility_id="single-lot-origin", destination_facility_id="single-lot-destination", due_days=4)
        self.assertEqual(world.quantity_held("single-lot-cart", "metals"), 0.0)
        advance_freight(world, 1)
        self.assertEqual(world.quantity_held("single-lot-cart", "metals"), 1.0)
        self.assertEqual(shipment.status, "in_transit")

    def test_market_delivery_remains_visible_to_market_purchases(self):
        world = build_tiny_world(seed=207)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = buyer.cash = 500_000.0
        world.create_lot("metals", 1.0, holder_id=seller.id, owner_id=seller.id, provenance=("market-test",))
        world.markets["north-market"].demand_backlog["metals"] = 2.0
        add_asset(world, TransportAsset("market-cart", "Market Cart", "cart", "shop", seller.id, capacity=1, fuel=100.0, fuel_capacity=100.0, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("market-origin", "shop", 1))
        add_facility(world, TransportFacility("market-destination", "north", 1, storage_access_id=buyer.id))
        before = world.quantity_held("north", "metals")
        contract = create_contract(world, seller.id, buyer.id, "metals", 1.0, 20.0, origin_id="shop", destination_id="north", due_days=3)
        dispatch_freight(world, contract.id, carrier_id="market-cart", origin_facility_id="market-origin", destination_facility_id="market-destination")
        advance_freight(world, 50)
        self.assertAlmostEqual(world.quantity_held("north", "metals"), before + 1.0)

    def test_non_finite_finance_is_rejected_and_audited(self):
        world = build_tiny_world(seed=208)
        with self.assertRaises(ValueError):
            world.pay("warehouse-business", "shop-market-cashier", math.nan)
        world.businesses["warehouse-business"].cash = math.nan
        with self.assertRaises(ValueError):
            world.pay("warehouse-business", "shop-market-cashier", 1.0)
        world.businesses["warehouse-business"].cash = 100.0
        world.businesses["shop-market-cashier"].cash = math.nan
        with self.assertRaises(ValueError):
            world.pay("warehouse-business", "shop-market-cashier", 1.0)
        self.assertEqual(world.businesses["warehouse-business"].cash, 100.0)
        security = issue_security(world, "warehouse-business", security_id="nan-test", name="Nan Test", shares=2.0, initial_price=10.0)
        with self.assertRaises(ValueError):
            execute_trade(world, "merchant", "warehouse-business", security.id, 1.0, price=math.nan)
        world.businesses["warehouse-business"].cash = math.nan
        self.assertTrue(any("non-finite" in error for error in validate_world(world)))


if __name__ == "__main__":
    unittest.main()
