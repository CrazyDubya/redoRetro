import unittest

from redos.bootstrap import build_tiny_world
from redos.equestrian import care_for_horse
from redos.harbor import build_harbor_world, harbor_audit
from redos.model import Actor, Business, GoodType, TransportAsset
from redos.runtime import run
from redos.transport import add_asset, service_asset_from_inventory, supply_asset_from_inventory


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
