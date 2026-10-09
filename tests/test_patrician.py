import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import TransportAsset, TransportFacility
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight


class PatricianTownEconomyTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=149)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = 500_000.0
        buyer.cash = 500_000.0
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id, provenance=("patrician-test",))
        world.markets["north-market"].demand_backlog["metals"] = 4.0
        add_asset(world, TransportAsset("town-trader", "Town Trader", "cart", "shop", seller.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("town-origin", "shop", 1))
        add_facility(world, TransportFacility("north-market-hall", "north", 1))
        return world, seller, buyer

    def test_physical_delivery_reduces_town_demand(self):
        world, seller, buyer = self._world()
        before = world.markets["north-market"].demand_backlog["metals"]
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="north", due_days=4)
        shipment = dispatch_freight(world, contract.id, carrier_id="town-trader", origin_facility_id="town-origin", destination_facility_id="north-market-hall")
        advance_freight(world, 50)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(world.markets["north-market"].demand_backlog["metals"], before - 1)
        self.assertTrue(any(event.kind == "market_delivery_accepted" for event in world.events))

    def test_warehouse_capacity_blocks_delivery_without_losing_cargo(self):
        world, seller, buyer = self._world()
        add_facility(world, TransportFacility("small-warehouse", "north", 1, storage_access_id=buyer.id, storage_capacity=0.5))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="north", due_days=4)
        shipment = dispatch_freight(world, contract.id, carrier_id="town-trader", origin_facility_id="town-origin", destination_facility_id="small-warehouse")
        advance_freight(world, 50)
        self.assertEqual(shipment.status, "failed")
        self.assertEqual(world.quantity_held("town-trader", "metals"), 1)
        self.assertEqual(world.quantity_held(buyer.id, "metals"), 0)


if __name__ == "__main__":
    unittest.main()
