import copy
import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.harbor import build_harbor_world, harbor_audit
from redos.market import refresh_market
from redos.model import Actor, Place, Route, RouteCondition, TransportAsset, TransportFacility
from redos.runtime import advance_world, run
from redos.simulation import _start_next_leg, apply_transport_weather, set_route_condition, tick
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight, replenish_asset


class Milestone2ReviewGapTests(unittest.TestCase):
    def _freight_world(self):
        world = build_tiny_world(seed=23)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 4, holder_id=seller.id, owner_id=seller.id, provenance=("supplier surplus",))
        add_asset(
            world,
            TransportAsset(
                "review-sloop",
                "Review Sloop",
                "vessel",
                "shop",
                buyer.id,
                capacity=2,
                fuel=100,
                fuel_capacity=100,
                fuel_burn_per_hour=0.1,
            ),
        )
        add_facility(world, TransportFacility("review-origin", "shop", handling_capacity=1))
        add_facility(world, TransportFacility("review-destination", "warehouse", handling_capacity=1))
        return world, seller, buyer

    def test_failed_cargo_blocks_reassignment_after_replenishment(self):
        world, seller, buyer = self._freight_world()
        asset = world.transport_assets["review-sloop"]
        asset.fuel = 0
        first = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        shipment = dispatch_freight(world, first.id, carrier_id=asset.id, origin_facility_id="review-origin", destination_facility_id="review-destination")
        advance_freight(world, 2)
        self.assertEqual(shipment.status, "failed")
        self.assertEqual(world.quantity_held(asset.id, "metals"), 1)
        self.assertTrue(asset.cargo_clearance_pending)
        replenish_asset(world, asset.id, "fuel", 10)
        self.assertTrue(asset.available)
        second = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        with self.assertRaises(ValueError):
            dispatch_freight(world, second.id, carrier_id=asset.id, origin_facility_id="review-origin", destination_facility_id="review-destination")
        self.assertEqual(len(world.shipments), 1)
        self.assertEqual(world.quantity_held(asset.id, "metals"), 1)

    def test_changed_freight_duration_normalizes_progress(self):
        world, seller, buyer = self._freight_world()
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        shipment = dispatch_freight(world, contract.id, carrier_id="review-sloop", origin_facility_id="review-origin", destination_facility_id="review-destination")
        advance_freight(world, 1)
        advance_freight(world, 20)
        set_route_condition(world, "shop-warehouse", travel_multiplier=0.5)
        advance_freight(world, 1)
        self.assertIn(shipment.status, {"arrived", "unloading", "delivered"})
        self.assertGreaterEqual(shipment.current_route_index, 1)
        self.assertGreaterEqual(shipment.elapsed_hours, 0)
        self.assertTrue(any(event.kind == "freight_progress_normalized" for event in world.events))

    def test_passenger_fuel_exhaustion_prevents_arrival(self):
        world = build_tiny_world(seed=24)
        world.add(Place("island", "Island"))
        world.add(Route("ferry", "shop", "island", 1, 1, "water", terrain="water", allowed_modes=("vessel",)))
        worker = Actor("passenger", "Passenger", "shop")
        world.add(worker)
        add_asset(world, TransportAsset("empty-ferry", "Empty Ferry", "vessel", "shop", "warehouse-business", capacity=2, fuel=0, fuel_capacity=10, fuel_burn_per_hour=1))
        world.runtime["passenger_services"] = (("empty-ferry", "shop", "island"),)
        self.assertTrue(_start_next_leg(world, worker, "island"))
        tick(world, 24)
        self.assertEqual(worker.location_id, "shop")
        self.assertEqual(world.transport_assets["empty-ferry"].fuel, 0)
        self.assertTrue(any(event.kind == "passenger_delayed" for event in world.events))

    def test_route_condition_registration_and_weather_update_are_atomic(self):
        world = build_tiny_world(seed=25)
        condition = RouteCondition("shop-warehouse", accessible=True, travel_multiplier=1.2)
        world.add(condition)
        self.assertIs(world.route_conditions["shop-warehouse"], condition)
        event_count = len(world.events)
        with self.assertRaises(KeyError):
            apply_transport_weather(world, ("shop-warehouse", "missing-route"), weather="invalid")
        self.assertEqual(len(world.events), event_count)
        self.assertEqual(world.route_conditions["shop-warehouse"].travel_multiplier, 1.2)

    def test_market_refresh_rolls_back_physical_and_derived_state_on_failure(self):
        world = build_tiny_world(seed=26)
        market = world.markets["shop-market"]
        market.production_rates["missing-good"] = 1.0
        market.production_source = "bad-external-source"
        market.production_account_id = "bad-account"
        before = (
            copy.deepcopy(market.balances),
            copy.deepcopy(market.demand_backlog),
            copy.deepcopy(market.price_history),
            market.last_updated_day,
            copy.deepcopy(world.lots),
            len(world.events),
        )
        with self.assertRaises(KeyError):
            refresh_market(world, market.id)
        self.assertEqual(market.balances, before[0])
        self.assertEqual(market.demand_backlog, before[1])
        self.assertEqual(market.price_history, before[2])
        self.assertEqual(market.last_updated_day, before[3])
        self.assertEqual(world.lots, before[4])
        self.assertEqual(len(world.events), before[5])

    def test_regional_fixture_reuses_carriers_and_routes_every_declared_mode(self):
        world = build_harbor_world(seed=27).world
        run(world, 30)
        report = harbor_audit(world)
        assignments = {asset_id: details["assignments"] for asset_id, details in report["asset_utilization"].items()}
        self.assertGreaterEqual(assignments["staten-sloop"], 2)
        self.assertGreaterEqual(assignments["warehouse-cart"], 2)
        self.assertGreaterEqual(assignments["dock-cart"], 2)
        self.assertGreaterEqual(assignments["manhattan-sloop"], 1)
        self.assertGreaterEqual(report["facility_utilization"]["manhattan-dock"]["completed_operations"], 1)
        self.assertGreater(report["goods_moved"].get("grain", 0), 0)
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])


if __name__ == "__main__":
    unittest.main()
