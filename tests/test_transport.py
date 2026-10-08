import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import TransportAsset, TransportFacility
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight


class PortsOfCallTransportTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=7)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 4, holder_id=seller.id, owner_id=seller.id, provenance=("supplier surplus",))
        add_asset(world, TransportAsset(
            "harbor-sloop",
            "Harbor Sloop",
            "vessel",
            "shop",
            buyer.id,
            capacity=2,
            fuel=100,
            fuel_capacity=100,
            fuel_burn_per_hour=0.1,
            operating_cost_per_hour=2,
        ))
        add_facility(world, TransportFacility("shop-landing", "shop", handling_capacity=1))
        add_facility(world, TransportFacility("warehouse-landing", "warehouse", handling_capacity=1))
        return world, seller, buyer

    def test_ports_of_call_freight_delivers_physical_cargo_before_settlement(self) -> None:
        world, seller, buyer = self._world()
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
            carrier_id="harbor-sloop",
            origin_facility_id="shop-landing",
            destination_facility_id="warehouse-landing",
        )
        self.assertEqual(world.now.day, 1)
        self.assertEqual(world.quantity_held(seller.id, "metals"), 4)
        self.assertEqual(world.quantity_held("harbor-sloop", "metals"), 0)
        self.assertEqual(shipment.status, "queued")

        advance_freight(world, 1)
        self.assertEqual(shipment.status, "in_transit")
        self.assertEqual(world.quantity_held("harbor-sloop", "metals"), 1)
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)
        self.assertEqual(contract.status, "in_transit")

        advance_freight(world, 24)
        self.assertEqual(shipment.status, "unloading")
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)
        advance_freight(world, 1)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(contract.status, "settled")
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 1)
        self.assertEqual(world.quantity_held("harbor-sloop", "metals"), 0)
        self.assertEqual(world.location_of("harbor-sloop"), "warehouse")
        self.assertEqual(world.now.day, 1)
        kinds = [event.kind for event in world.events]
        self.assertLess(kinds.index("freight_queued"), kinds.index("loading_started"))
        self.assertLess(kinds.index("freight_departed"), kinds.index("contract_delivered"))
        self.assertLess(kinds.index("contract_delivered"), kinds.index("contract_settled"))

    def test_carrier_capacity_is_checked_before_loading_or_clock_change(self) -> None:
        world, seller, buyer = self._world()
        contract = create_contract(
            world,
            seller.id,
            buyer.id,
            "metals",
            3,
            20,
            origin_id="shop",
            destination_id="warehouse",
            due_days=3,
        )
        with self.assertRaises(ValueError):
            dispatch_freight(
                world,
                contract.id,
                carrier_id="harbor-sloop",
                origin_facility_id="shop-landing",
                destination_facility_id="warehouse-landing",
            )
        self.assertEqual(world.quantity_held(seller.id, "metals"), 4)
        self.assertEqual(world.now.day, 1)
        self.assertEqual(world.shipments, {})

    def test_facility_queue_prevents_simultaneous_loading_beyond_capacity(self) -> None:
        world, seller, buyer = self._world()
        add_asset(world, TransportAsset("second-sloop", "Second Sloop", "vessel", "shop", buyer.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        first = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=3)
        second = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=3)
        first_shipment = dispatch_freight(world, first.id, carrier_id="harbor-sloop", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing", loading_hours=2)
        second_shipment = dispatch_freight(world, second.id, carrier_id="second-sloop", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing", loading_hours=2)
        advance_freight(world, 1)
        self.assertEqual(first_shipment.status, "loading")
        self.assertEqual(second_shipment.status, "queued")
        self.assertEqual(world.transport_facilities["shop-landing"].active_shipments, [first_shipment.id])


if __name__ == "__main__":
    unittest.main()
