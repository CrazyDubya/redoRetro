import unittest
from datetime import timedelta

from redos.bootstrap import build_tiny_world
from redos.equestrian import care_for_horse
from redos.harbor import build_harbor_world, harbor_audit
from redos.model import Actor, Business, GoodType, TransportAsset, TransportService
from redos.runtime import run
from redos.simulation import set_route_condition
from redos.transport import add_asset, add_service, advance_services, service_asset_from_inventory, supply_asset_from_inventory


class PhysicalAssetServiceTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=601)
        world.add(GoodType("fuel", "Barrelled fuel", 2.0))
        world.add(GoodType("maintenance-parts", "Maintenance parts", 5.0))
        world.add(Business("service-yard", "Service Yard", "shop", "service", cash=100.0))
        world.create_lot("fuel", 20.0, holder_id="service-yard", owner_id="service-yard", provenance=("physical fuel stock",))
        world.create_lot("maintenance-parts", 10.0, holder_id="service-yard", owner_id="service-yard", provenance=("physical parts stock",))
        worker = Actor(
            "service-worker",
            "Service Worker",
            "shop",
            employer_id="service-yard",
            occupation="mechanic",
            current_activity="work",
        )
        world.add(worker)
        owner = world.businesses["warehouse-business"]
        owner.cash = 100.0
        add_asset(
            world,
            TransportAsset(
                "service-cart",
                "Service Cart",
                "cart",
                "shop",
                owner.id,
                capacity=2,
                fuel=0.0,
                fuel_capacity=10.0,
                condition=0.5,
            ),
        )
        return world, owner, worker

    def test_supply_consumes_physical_stock_and_pays_supplier(self):
        world, owner, _worker = self._world()
        added = supply_asset_from_inventory(
            world,
            "service-cart",
            "fuel",
            6.0,
            source_holder_id="service-yard",
            good_type_id="fuel",
            unit_price=2.0,
            payee_id="service-yard",
        )
        self.assertEqual(added, 6.0)
        self.assertEqual(world.transport_assets["service-cart"].fuel, 6.0)
        self.assertEqual(world.quantity_held("service-yard", "fuel"), 14.0)
        self.assertEqual(owner.cash, 88.0)
        self.assertEqual(world.businesses["service-yard"].cash, 112.0)
        self.assertTrue(any(event.kind == "asset_supply_purchased" for event in world.events))

    def test_maintenance_requires_present_worker_and_physical_parts(self):
        world, owner, worker = self._world()
        worker.current_activity = "sleep"
        with self.assertRaises(ValueError):
            service_asset_from_inventory(
                world,
                "service-cart",
                source_holder_id="service-yard",
                parts_good_type_id="maintenance-parts",
                parts_quantity=1.0,
                worker_id=worker.id,
                repair_amount=0.25,
            )
        worker.current_activity = "work"
        repaired = service_asset_from_inventory(
            world,
            "service-cart",
            source_holder_id="service-yard",
            parts_good_type_id="maintenance-parts",
            parts_quantity=1.0,
            worker_id=worker.id,
            repair_amount=0.25,
            unit_price=5.0,
            labor_price=2.0,
            payee_id="service-yard",
        )
        self.assertAlmostEqual(repaired, 0.25)
        self.assertEqual(world.transport_assets["service-cart"].condition, 0.75)
        self.assertEqual(world.quantity_held("service-yard", "maintenance-parts"), 9.0)
        self.assertEqual(owner.cash, 93.0)
        self.assertTrue(any(event.kind == "asset_maintenance" for event in world.events))

    def test_moving_asset_cannot_be_serviced_at_last_waypoint(self):
        world, owner, worker = self._world()
        add_service(world, TransportService("moving-service", "service-cart", ("shop", "north")))
        service = world.transport_services["moving-service"]
        service.status = "in_transit"
        service.route_ids = ("shop-north",)
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                "service-cart",
                "fuel",
                1.0,
                source_holder_id="service-yard",
                good_type_id="fuel",
            )
        with self.assertRaises(ValueError):
            service_asset_from_inventory(
                world,
                "service-cart",
                source_holder_id="service-yard",
                parts_good_type_id="maintenance-parts",
                parts_quantity=1.0,
                worker_id=worker.id,
            )
        service.status = "ready"
        self.assertEqual(supply_asset_from_inventory(world, "service-cart", "fuel", 1.0, source_holder_id="service-yard", good_type_id="fuel", unit_price=1.0), 1.0)

    def test_blocked_partial_service_leg_is_not_a_station(self):
        world, _owner, worker = self._world()
        asset = world.transport_assets["service-cart"]
        asset.fuel = 10.0
        add_service(world, TransportService("blocked-service", "service-cart", ("shop", "north")))
        advance_services(world, 0.5)
        set_route_condition(world, "shop-north", accessible=False, hazard="washed out")
        advance_services(world, 1.0)
        service = world.transport_services["blocked-service"]
        self.assertEqual(service.status, "blocked")
        self.assertGreater(service.elapsed_hours, 0.0)
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                asset.id,
                "fuel",
                1.0,
                source_holder_id="service-yard",
                good_type_id="fuel",
            )
        with self.assertRaises(ValueError):
            service_asset_from_inventory(
                world,
                asset.id,
                source_holder_id="service-yard",
                parts_good_type_id="maintenance-parts",
                parts_quantity=1.0,
                worker_id=worker.id,
            )

    def test_zero_progress_resource_stall_can_refuel_and_resume(self):
        world, _owner, worker = self._world()
        asset = world.transport_assets["service-cart"]
        asset.fuel = 10.0
        asset.supplies["stores"] = 0.0
        asset.supply_capacity["stores"] = 48.0
        asset.supply_burn_per_hour["stores"] = 1.0
        world.add(GoodType("stores", "Travel stores", 1.0))
        world.create_lot("stores", 48.0, holder_id="service-yard", owner_id="service-yard", provenance=("travel stores",))
        add_service(world, TransportService("stalled-service", "service-cart", ("shop", "north")))
        advance_services(world, 0.5)
        service = world.transport_services["stalled-service"]
        self.assertEqual(service.status, "waiting_asset")
        self.assertTrue(service.route_ids)
        self.assertEqual(service.elapsed_hours, 0.0)
        self.assertEqual(service.journey_elapsed_hours, 0.0)
        self.assertEqual(
            supply_asset_from_inventory(
                world,
                asset.id,
                "stores",
                48.0,
                source_holder_id="service-yard",
                good_type_id="stores",
                unit_price=1.0,
                payee_id="service-yard",
            ),
            48.0,
        )
        advance_services(world, 48.0)
        self.assertEqual(asset.location_id, "north")
        self.assertEqual(service.status, "dwelling")
        self.assertEqual(service.journey_elapsed_hours, 48.0)

    def test_mid_route_resource_stall_cannot_be_serviced_at_last_waypoint(self):
        world, _owner, _worker = self._world()
        asset = world.transport_assets["service-cart"]
        asset.fuel = 10.0
        asset.supplies["stores"] = 0.5
        asset.supply_capacity["stores"] = 1.0
        asset.supply_burn_per_hour["stores"] = 1.0
        world.add(GoodType("stores", "Travel stores", 1.0))
        world.create_lot("stores", 2.0, holder_id="service-yard", owner_id="service-yard", provenance=("travel stores",))
        add_service(world, TransportService("mid-route-stall", "service-cart", ("shop", "north")))
        advance_services(world, 0.5)
        service = world.transport_services["mid-route-stall"]
        self.assertEqual(service.status, "in_transit")
        self.assertGreater(service.elapsed_hours, 0.0)
        advance_services(world, 1.0)
        self.assertEqual(service.status, "waiting_asset")
        self.assertGreater(service.elapsed_hours, 0.0)
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                asset.id,
                "stores",
                1.0,
                source_holder_id="service-yard",
                good_type_id="stores",
            )

    def test_duplicate_fuel_requirements_are_aggregated_before_consumption(self):
        world, _owner, _worker = self._world()
        asset = world.transport_assets["service-cart"]
        asset.fuel = 0.5
        asset.fuel_burn_per_hour = 0.4
        asset.supply_burn_per_hour["fuel"] = 0.4
        add_service(world, TransportService("duplicate-fuel-service", "service-cart", ("shop", "north")))
        advance_services(world, 1.0)
        self.assertEqual(asset.fuel, 0.5)
        self.assertEqual(asset.accrued_operating_cost, 0.0)
        self.assertEqual(world.transport_services["duplicate-fuel-service"].elapsed_hours, 0.0)

    def test_supply_requires_the_owner_when_stock_is_mixed(self):
        world, owner, _worker = self._world()
        other = Business("other-seller", "Other Seller", "shop", "supplier", cash=100.0)
        world.add(other)
        world.create_lot("fuel", 2.0, holder_id="service-yard", owner_id=other.id, provenance=("other seller stock",))
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                "service-cart",
                "fuel",
                1.0,
                source_holder_id="service-yard",
                good_type_id="fuel",
            )
        added = supply_asset_from_inventory(
            world,
            "service-cart",
            "fuel",
            1.0,
            source_holder_id="service-yard",
            good_type_id="fuel",
            seller_id="service-yard",
            payee_id="service-yard",
            unit_price=2.0,
        )
        self.assertEqual(added, 1.0)
        self.assertEqual(world.quantity_held("service-yard", "fuel"), 21.0)

    def test_zero_price_cross_owner_supply_requires_explicit_gift(self):
        world, _owner, _worker = self._world()
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                "service-cart",
                "fuel",
                1.0,
                source_holder_id="service-yard",
                good_type_id="fuel",
            )
        self.assertEqual(world.transport_assets["service-cart"].fuel, 0.0)
        self.assertEqual(
            supply_asset_from_inventory(
                world,
                "service-cart",
                "fuel",
                1.0,
                source_holder_id="service-yard",
                good_type_id="fuel",
                allow_gift=True,
            ),
            1.0,
        )

    def test_encumbered_source_cargo_cannot_become_fuel_or_be_paid_for(self):
        world, owner, _worker = self._world()
        source = TransportAsset(
            "encumbered-source",
            "Encumbered Source",
            "cart",
            "shop",
            "service-yard",
            capacity=2,
            assigned_shipment_id="active-shipment",
            assignment_kind="freight",
            available=False,
        )
        add_asset(world, source)
        world.create_lot("fuel", 2.0, holder_id=source.id, owner_id="service-yard", provenance=("committed fuel",))
        before_cash = owner.cash
        before_events = len(world.events)
        with self.assertRaises(ValueError):
            supply_asset_from_inventory(
                world,
                "service-cart",
                "fuel",
                1.0,
                source_holder_id=source.id,
                good_type_id="fuel",
                unit_price=2.0,
                payee_id="service-yard",
            )
        self.assertEqual(owner.cash, before_cash)
        self.assertEqual(world.transport_assets["service-cart"].fuel, 0.0)
        self.assertEqual(world.quantity_held(source.id, "fuel"), 2.0)
        self.assertEqual(len(world.events), before_events)

    def test_encumbered_source_parts_cannot_be_paid_for_or_restore_condition(self):
        world, owner, worker = self._world()
        source = TransportAsset(
            "encumbered-parts-source",
            "Encumbered Parts Source",
            "cart",
            "shop",
            "service-yard",
            capacity=2,
            assigned_shipment_id="active-shipment",
            assignment_kind="freight",
            available=False,
        )
        add_asset(world, source)
        world.create_lot("maintenance-parts", 2.0, holder_id=source.id, owner_id="service-yard", provenance=("committed parts",))
        asset = world.transport_assets["service-cart"]
        before_cash = owner.cash
        before_condition = asset.condition
        before_events = len(world.events)
        with self.assertRaises(ValueError):
            service_asset_from_inventory(
                world,
                asset.id,
                source_holder_id=source.id,
                parts_good_type_id="maintenance-parts",
                parts_quantity=1.0,
                worker_id=worker.id,
                unit_price=5.0,
                payee_id="service-yard",
            )
        self.assertEqual(owner.cash, before_cash)
        self.assertEqual(asset.condition, before_condition)
        self.assertEqual(world.quantity_held(source.id, "maintenance-parts"), 2.0)
        self.assertEqual(world.runtime.get("_asset_service_worker_hours", {}), {})
        self.assertEqual(len(world.events), before_events)

    def test_resource_bundle_preflight_does_not_burn_fuel_without_stores(self):
        world, owner, _worker = self._world()
        asset = world.transport_assets["service-cart"]
        asset.fuel = 5.0
        asset.supplies["stores"] = 0.0
        asset.supply_capacity["stores"] = 2.0
        asset.supply_burn_per_hour["stores"] = 1.0
        add_service(world, TransportService("resource-service", "service-cart", ("shop", "north")))
        advance_services(world, 1.0)
        self.assertEqual(asset.fuel, 5.0)
        self.assertEqual(asset.supplies["stores"], 0.0)
        self.assertEqual(asset.accrued_operating_cost, 0.0)
        self.assertEqual(world.transport_services["resource-service"].elapsed_hours, 0.0)

    def test_one_mechanic_cannot_service_two_assets_in_one_hour(self):
        world, owner, worker = self._world()
        add_asset(world, TransportAsset("second-cart", "Second Cart", "cart", "shop", owner.id, capacity=2, condition=0.5))
        service_asset_from_inventory(
            world,
            "service-cart",
            source_holder_id="service-yard",
            parts_good_type_id="maintenance-parts",
            parts_quantity=1.0,
            worker_id=worker.id,
            unit_price=5.0,
            payee_id="service-yard",
        )
        world.now += timedelta(minutes=30)
        with self.assertRaises(ValueError):
            service_asset_from_inventory(
                world,
                "second-cart",
                source_holder_id="service-yard",
                parts_good_type_id="maintenance-parts",
                parts_quantity=1.0,
                worker_id=worker.id,
            )

    def test_service_causality_uses_event_ids_not_inventory_lot_ids(self):
        world, _owner, _worker = self._world()
        supply_asset_from_inventory(
            world,
            "service-cart",
            "fuel",
            1.0,
            source_holder_id="service-yard",
            good_type_id="fuel",
            unit_price=2.0,
            payee_id="service-yard",
        )
        purchase = next(event for event in reversed(world.events) if event.kind == "asset_supply_purchased")
        caused = {event.id for event in world.events}
        self.assertTrue(purchase.causes)
        self.assertTrue(set(purchase.causes) <= caused)
        self.assertTrue(any(event.kind == "goods_transfer" and event.id in purchase.causes for event in world.events))
        self.assertTrue(any(event.kind == "consumption" and event.id in purchase.causes for event in world.events))

    def test_harbor_uses_multimodal_transfer_and_autonomous_service(self):
        world = build_harbor_world(seed=602).world
        run(world, 30)
        report = harbor_audit(world)
        self.assertEqual(world.routes["newjersey-dock"].destination_id, "newjersey-transfer")
        self.assertEqual(world.routes["newjersey-transfer-dock"].mode, "water")
        self.assertGreaterEqual(report["asset_utilization"]["warehouse-cart"]["assignments"], 2)
        self.assertGreaterEqual(report["asset_utilization"]["newjersey-sloop"]["assignments"], 2)
        self.assertGreater(report["physical_asset_services"]["supplies_purchased"], 0)
        self.assertGreater(report["physical_asset_services"]["maintenance_operations"], 0)
        self.assertEqual(report["invariants"]["conservation_errors"], [])

    def test_horse_feed_can_be_consumed_from_canonical_stock(self):
        world = build_tiny_world(seed=603)
        world.runtime["horse_feed_allow_gift"] = True
        world.add(GoodType("feed", "Horse feed", 1.0))
        world.create_lot("feed", 5.0, holder_id="shop", owner_id="shop-market-cashier", provenance=("feed delivery",))
        add_asset(
            world,
            TransportAsset(
                "stable-horse",
                "Stable Horse",
                "horse",
                "shop",
                "warehouse-business",
                capacity=1,
                supplies={"feed": 0.0},
                supply_capacity={"feed": 5.0},
            ),
        )
        added = care_for_horse(world, "stable-horse", "feed", 2.0, source_id="shop")
        self.assertEqual(added, 2.0)
        self.assertEqual(world.quantity_held("shop", "feed"), 3.0)
        self.assertEqual(world.transport_assets["stable-horse"].supplies["feed"], 2.0)


if __name__ == "__main__":
    unittest.main()
