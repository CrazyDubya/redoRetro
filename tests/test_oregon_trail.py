import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import Route, TransportAsset, TransportFacility
from redos.transport import (
    abandon_freight,
    add_asset,
    add_facility,
    advance_freight,
    divert_freight,
    dispatch_freight,
    interrupt_freight,
)


class OregonTrailJourneyTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 3, holder_id=seller.id, owner_id=seller.id, provenance=("supplier surplus",))
        add_asset(world, TransportAsset("wagon", "Covered Wagon", "cart", "shop", buyer.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("shop-landing", "shop", handling_capacity=1))
        add_facility(world, TransportFacility("warehouse-landing", "warehouse", handling_capacity=1))
        return world, seller, buyer

    def test_interruption_consumes_time_without_releasing_physical_cargo(self) -> None:
        world, seller, buyer = self._world()
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=3)
        shipment = dispatch_freight(world, contract.id, carrier_id="wagon", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing")
        advance_freight(world, 1)
        interrupt_freight(world, shipment.id, 3, reason="wagon wheel repair")
        advance_freight(world, 2)
        self.assertEqual(shipment.delay_remaining_hours, 1)
        self.assertEqual(world.quantity_held("wagon", "metals"), 1)
        advance_freight(world, 1)
        self.assertEqual(shipment.elapsed_hours, 0)
        advance_freight(world, 24)
        advance_freight(world, 1)
        self.assertEqual(contract.status, "settled")

    def test_diversion_requires_a_physical_boundary_and_preserves_contract_destination(self) -> None:
        world, seller, buyer = self._world()
        world.add(Route("tavern-warehouse", "tavern", "warehouse", 0.6, 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=5)
        shipment = dispatch_freight(world, contract.id, carrier_id="wagon", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing")
        divert_freight(world, shipment.id, ("shop-tavern", "tavern-warehouse"), reason="main road washed out")
        self.assertEqual(shipment.route_ids, ("shop-tavern", "tavern-warehouse"))
        advance_freight(world, 1)
        self.assertEqual(world.quantity_held("wagon", "metals"), 1)
        advance_freight(world, 24)
        advance_freight(world, 24)
        advance_freight(world, 1)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(contract.status, "settled")
        self.assertTrue(any(event.kind == "freight_diverted" for event in world.events))

    def test_diversion_cannot_change_route_mid_leg(self) -> None:
        world, seller, buyer = self._world()
        world.add(Route("tavern-warehouse", "tavern", "warehouse", 0.6, 1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=5)
        shipment = dispatch_freight(world, contract.id, carrier_id="wagon", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing")
        advance_freight(world, 1)
        advance_freight(world, 1)
        with self.assertRaises(ValueError):
            divert_freight(world, shipment.id, ("shop-tavern", "tavern-warehouse"), reason="unsafe route")

    def test_abandonment_fails_the_obligation_without_losing_cargo_provenance(self) -> None:
        world, seller, buyer = self._world()
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=3)
        shipment = dispatch_freight(world, contract.id, carrier_id="wagon", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing")
        advance_freight(world, 1)
        abandon_freight(world, shipment.id, reason="wagon party cannot continue")
        self.assertEqual(shipment.status, "failed")
        self.assertEqual(contract.status, "failed")
        self.assertEqual(world.quantity_held("wagon", "metals"), 1)
        self.assertTrue(any(event.kind == "freight_abandoned" for event in world.events))


if __name__ == "__main__":
    unittest.main()
