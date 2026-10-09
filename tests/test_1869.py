import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import Route, TransportAsset, TransportFacility
from redos.simulation import best_route, set_route_condition
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight


class NineteenSixtyNineRouteTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=131)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = 500_000.0
        buyer.cash = 500_000.0
        world.create_lot("metals", 2, holder_id=seller.id, owner_id=seller.id, provenance=("route-test",))
        world.add(Route("shop-north-direct", "shop", "north", 10.0, 4, mode="road"))
        world.add(Route("shop-tavern-waypoint", "shop", "tavern", 1.0, 1, mode="road"))
        world.add(Route("tavern-north-waypoint", "tavern", "north", 1.0, 1, mode="road"))
        add_asset(world, TransportAsset("route-cart", "Route Cart", "cart", "shop", seller.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("route-origin", "shop", 1))
        add_facility(world, TransportFacility("route-destination", "north", 1))
        return world, seller, buyer

    def test_best_route_prefers_waypoints_when_conditions_make_direct_course_worse(self):
        world, _seller, _buyer = self._world()
        set_route_condition(world, "shop-north-direct", travel_multiplier=2.0, wind=0.5, waterway="calm")
        set_route_condition(world, "shop-north", travel_multiplier=3.0, wind=0.5, waterway="calm")
        set_route_condition(world, "shop-tavern", travel_multiplier=2.0, wind=0.5, waterway="calm")
        path = best_route(world, "shop", "north", mode="cart")
        self.assertEqual([route.id for route in path], ["shop-tavern-waypoint", "tavern-north-waypoint"])
        self.assertEqual(best_route(world, "shop", "north", mode="cart", max_hours=40), [])

    def test_selected_route_is_the_physical_shipment_route(self):
        world, seller, buyer = self._world()
        set_route_condition(world, "shop-north-direct", travel_multiplier=2.0, wind=0.5, waterway="calm")
        set_route_condition(world, "shop-north", travel_multiplier=3.0, wind=0.5, waterway="calm")
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="north", due_days=5)
        shipment = dispatch_freight(
            world,
            contract.id,
            carrier_id="route-cart",
            origin_facility_id="route-origin",
            destination_facility_id="route-destination",
            route_ids=("shop-tavern-waypoint", "tavern-north-waypoint"),
        )
        self.assertEqual(shipment.route_ids, ("shop-tavern-waypoint", "tavern-north-waypoint"))
        advance_freight(world, 50)
        self.assertEqual(shipment.status, "delivered")
        self.assertGreaterEqual(world.quantity_held("north", "metals"), 1)

    def test_inaccessible_explicit_course_cannot_be_dispatched(self):
        world, seller, buyer = self._world()
        set_route_condition(world, "shop-north-direct", accessible=False, travel_multiplier=1.0)
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20_000, origin_id="shop", destination_id="north", due_days=5)
        with self.assertRaises(ValueError):
            dispatch_freight(
                world,
                contract.id,
                carrier_id="route-cart",
                origin_facility_id="route-origin",
                destination_facility_id="route-destination",
                route_ids=("shop-north-direct",),
            )
        self.assertEqual(contract.status, "open")
        self.assertEqual(world.shipments, {})


if __name__ == "__main__":
    unittest.main()
