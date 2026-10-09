import unittest

from redos.bootstrap import build_tiny_world
from redos.model import TransportAsset, TransportFacility
from redos.runtime import _adjudicate_businesses, advance_world
from redos.transport import add_asset, add_facility, assign_asset, release_asset


class AutonomousCommercialTransportTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id, provenance=("supplier surplus",))
        add_asset(world, TransportAsset("service-sloop", "Service Sloop", "vessel", "shop", buyer.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("shop-landing", "shop", handling_capacity=1))
        add_facility(world, TransportFacility("warehouse-landing", "warehouse", handling_capacity=1))
        world.runtime["transport_services"] = (("service-sloop", "shop-landing", "warehouse-landing"),)
        world.runtime["input_flows"] = ((seller.id, buyer.id, "metals", 1, 20),)
        return world, seller, buyer

    def test_business_need_dispatches_through_a_declared_available_service(self) -> None:
        world, seller, buyer = self._world()
        _adjudicate_businesses(world)
        self.assertEqual(len(world.shipments), 1)
        shipment = next(iter(world.shipments.values()))
        self.assertEqual(shipment.carrier_id, "service-sloop")
        self.assertEqual(world.contracts[shipment.contract_id].status, "allocated")
        for _ in range(26):
            advance_world(world, 1)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(world.contracts[shipment.contract_id].status, "settled")

    def test_unavailable_service_leaves_demand_pending_then_retries(self) -> None:
        world, seller, buyer = self._world()
        assign_asset(world, "service-sloop", "passenger-run", kind="passenger")
        _adjudicate_businesses(world)
        self.assertEqual(world.shipments, {})
        pending = [contract for contract in world.contracts.values() if contract.status == "open"]
        self.assertEqual(len(pending), 1)
        release_asset(world, "service-sloop")
        _adjudicate_businesses(world)
        self.assertEqual(len(world.shipments), 1)
        self.assertEqual(world.shipments[next(iter(world.shipments))].contract_id, pending[0].id)


if __name__ == "__main__":
    unittest.main()
