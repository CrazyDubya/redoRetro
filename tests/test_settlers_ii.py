import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import GoodType, Route, TransportAsset, TransportFacility
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight


class SettlersIIRelayTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=91)
        world.add(GoodType("grain", "Grain", 2.0))
        world.add(Route("shop-flag", "shop", "warehouse", 1.0, 1, mode="road", terrain="road", allowed_modes=("cart",)))
        world.add(Route("flag-dock", "warehouse", "dock", 1.0, 1, mode="road", terrain="road", allowed_modes=("cart",)))
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        seller.cash = 500.0
        buyer.cash = 500.0
        world.create_lot("grain", 5.0, holder_id=seller.id, owner_id=seller.id, provenance=("relay-test",))
        add_facility(world, TransportFacility("shop-yard", "shop", 1))
        add_facility(world, TransportFacility("warehouse-yard", "warehouse", 1))
        add_facility(world, TransportFacility("dock-yard", "dock", 1))
        add_asset(world, TransportAsset("cart-a", "First cart", "cart", "shop", seller.id, 5.0, fuel=10.0, fuel_capacity=10.0, fuel_burn_per_hour=0.0))
        add_asset(world, TransportAsset("cart-b", "Relay cart", "cart", "warehouse", seller.id, 5.0, fuel=10.0, fuel_capacity=10.0, fuel_burn_per_hour=0.0))
        contract = create_contract(world, seller.id, buyer.id, "grain", 5.0, 2.0, origin_id="shop", destination_id="dock", due_days=5)
        return world, seller, buyer, contract

    def test_relay_transfers_physical_custody_and_reserves_next_carrier(self):
        world, seller, _buyer, contract = self._world()
        shipment = dispatch_freight(
            world,
            contract.id,
            carrier_id="cart-a",
            origin_facility_id="shop-yard",
            destination_facility_id="dock-yard",
            loading_hours=1.0,
            unloading_hours=1.0,
            carrier_plan=("cart-a", "cart-b"),
            relay_leg_counts=(1, 1),
        )
        self.assertEqual(world.transport_assets["cart-b"].reserved_for_shipment_id, shipment.id)
        advance_freight(world, 26.0)
        self.assertEqual(shipment.carrier_id, "cart-b")
        self.assertEqual(world.quantity_held("cart-a", "grain"), 0.0)
        self.assertEqual(world.quantity_held("cart-b", "grain"), 5.0)
        self.assertFalse(world.transport_assets["cart-a"].cargo_clearance_pending)
        self.assertTrue(any(event.kind == "freight_handoff" for event in world.events))
        advance_freight(world, 25.0)
        self.assertEqual(contract.status, "settled")
        self.assertEqual(world.quantity_held(seller.id, "grain"), 0.0)

    def test_unavailable_next_carrier_waits_without_cargo_teleport(self):
        world, _seller, _buyer, contract = self._world()
        shipment = dispatch_freight(
            world,
            contract.id,
            carrier_id="cart-a",
            origin_facility_id="shop-yard",
            destination_facility_id="dock-yard",
            carrier_plan=("cart-a", "cart-b"),
            relay_leg_counts=(1, 1),
        )
        world.transport_assets["cart-b"].available = False
        advance_freight(world, 26.0)
        self.assertEqual(shipment.status, "handoff_wait")
        self.assertEqual(world.quantity_held("cart-a", "grain"), 5.0)
        self.assertEqual(world.quantity_held("cart-b", "grain"), 0.0)
        self.assertNotEqual(contract.status, "settled")


if __name__ == "__main__":
    unittest.main()
