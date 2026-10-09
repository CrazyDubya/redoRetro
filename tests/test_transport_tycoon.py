import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import TransportAsset, TransportFacility, TransportService
from redos.transport import add_asset, add_facility, add_service, advance_freight, advance_services, dispatch_freight


class TransportTycoonServiceTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=113)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id, provenance=("service-test",))
        add_asset(world, TransportAsset("line-cart", "Line Cart", "cart", "shop", buyer.id, capacity=2, fuel=10, fuel_capacity=10, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("shop-stop", "shop", 1))
        add_facility(world, TransportFacility("warehouse-stop", "warehouse", 1))
        add_service(
            world,
            TransportService(
                "shop-warehouse-line",
                "line-cart",
                ("shop", "warehouse"),
                accepted_good_type_ids=("metals",),
                timetable_hours=(24.0, 24.0),
            ),
        )
        return world, seller, buyer

    def test_ordered_service_follows_stops_and_consumes_vehicle_resources(self):
        world, _seller, _buyer = self._world()
        service = world.transport_services["shop-warehouse-line"]
        advance_services(world, 24)
        self.assertEqual(world.transport_assets["line-cart"].location_id, "warehouse")
        self.assertEqual(service.current_stop_index, 1)
        self.assertLess(world.transport_assets["line-cart"].fuel, 10)
        advance_services(world, 24)
        self.assertEqual(world.transport_assets["line-cart"].location_id, "shop")
        self.assertEqual(service.completed_cycles, 1)

    def test_freight_assignment_interrupts_service_then_resumes_at_next_stop(self):
        world, seller, buyer = self._world()
        service = world.transport_services["shop-warehouse-line"]
        contract = create_contract(
            world,
            seller.id,
            buyer.id,
            "metals",
            1,
            20,
            origin_id="shop",
            destination_id="warehouse",
            due_days=3,
        )
        shipment = dispatch_freight(
            world,
            contract.id,
            carrier_id="line-cart",
            origin_facility_id="shop-stop",
            destination_facility_id="warehouse-stop",
            service_id=service.id,
        )
        self.assertEqual(service.status, "waiting_asset")
        advance_freight(world, 26)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(service.current_stop_index, 1)
        advance_services(world, 24)
        self.assertEqual(world.transport_assets["line-cart"].location_id, "shop")
        self.assertEqual(service.completed_cycles, 1)

    def test_service_rejects_cargo_outside_its_declared_order(self):
        world, seller, buyer = self._world()
        contract = create_contract(
            world,
            seller.id,
            buyer.id,
            "food",
            1,
            20,
            origin_id="shop",
            destination_id="warehouse",
            due_days=3,
        )
        with self.assertRaises(ValueError):
            dispatch_freight(
                world,
                contract.id,
                carrier_id="line-cart",
                origin_facility_id="shop-stop",
                destination_facility_id="warehouse-stop",
                service_id="shop-warehouse-line",
            )
        self.assertEqual(contract.status, "open")
        self.assertEqual(world.shipments, {})


if __name__ == "__main__":
    unittest.main()
