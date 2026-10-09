import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import TransportAsset, TransportFacility
from redos.transport import add_asset, add_facility, advance_freight, assign_crew, dispatch_freight


class HighSeasTraderTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=137)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        seller.cash = 500_000.0
        buyer.cash = 500_000.0
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id, provenance=("crew-voyage-test",))
        add_asset(
            world,
            TransportAsset(
                "crew-sloop",
                "Crewed Sloop",
                "vessel",
                "shop",
                seller.id,
                capacity=2,
                fuel=100,
                fuel_capacity=100,
                fuel_burn_per_hour=0.1,
                supplies={"food": 2.0},
                supply_capacity={"food": 2.0},
                supply_burn_per_hour={"food": 0.05},
                minimum_crew=2,
            ),
        )
        add_facility(world, TransportFacility("crew-origin", "shop", 1))
        add_facility(world, TransportFacility("crew-destination", "warehouse", 1))
        return world, seller, buyer

    def test_voyage_requires_existing_crew_and_consumes_supplies(self):
        world, seller, buyer = self._world()
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="warehouse", due_days=4)
        with self.assertRaises(ValueError):
            dispatch_freight(world, contract.id, carrier_id="crew-sloop", origin_facility_id="crew-origin", destination_facility_id="crew-destination")
        assign_crew(world, "crew-sloop", ("merchant", "cooper"))
        shipment = dispatch_freight(world, contract.id, carrier_id="crew-sloop", origin_facility_id="crew-origin", destination_facility_id="crew-destination")
        advance_freight(world, 26)
        self.assertEqual(shipment.status, "delivered")
        self.assertLess(world.transport_assets["crew-sloop"].supplies["food"], 2.0)
        self.assertTrue(any(event.kind == "asset_crew_assigned" for event in world.events))

    def test_supply_shortage_fails_the_voyage_without_losing_cargo(self):
        world, seller, buyer = self._world()
        assign_crew(world, "crew-sloop", ("merchant", "cooper"))
        world.transport_assets["crew-sloop"].supplies["food"] = 0.01
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="warehouse", due_days=4)
        shipment = dispatch_freight(world, contract.id, carrier_id="crew-sloop", origin_facility_id="crew-origin", destination_facility_id="crew-destination")
        advance_freight(world, 26)
        self.assertEqual(shipment.status, "failed")
        self.assertEqual(world.quantity_held("crew-sloop", "metals"), 1)
        self.assertTrue(world.transport_assets["crew-sloop"].cargo_clearance_pending)


if __name__ == "__main__":
    unittest.main()
