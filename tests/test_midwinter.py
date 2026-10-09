import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import create_contract
from redos.model import Place, Route, TransportAsset, TransportFacility
from redos.simulation import effective_route_hours, route_path, set_route_condition, tick
from redos.transport import add_asset, add_facility, advance_freight, dispatch_freight


class MidwinterTraversalTests(unittest.TestCase):
    def test_terrain_method_and_condition_change_passage_time(self) -> None:
        world = build_tiny_world()
        route = Route(
            "rough-pass",
            "shop",
            "north",
            1.0,
            1,
            "walk",
            terrain="rough",
            allowed_modes=("walk", "cart"),
        )
        world.add(route)
        walking_hours = effective_route_hours(world, route, mode="walk")
        cart_hours = effective_route_hours(world, route, mode="cart")
        self.assertGreater(walking_hours, 24)
        self.assertGreater(cart_hours, walking_hours)
        set_route_condition(world, route.id, travel_multiplier=2.0, hazard="deep snow")
        self.assertEqual(effective_route_hours(world, route, mode="walk"), walking_hours * 2)

    def test_blocked_route_is_not_selected_and_no_unapproved_traversal_occurs(self) -> None:
        world = build_tiny_world()
        world.add(Route("shop-alternative", "shop", "north", 4.0, 4, "walk", terrain="plain", allowed_modes=("walk",)))
        set_route_condition(world, "shop-north", accessible=False, hazard="washed out pass")
        path = route_path(world, "shop", "north", mode="walk")
        self.assertEqual([route.id for route in path], ["shop-alternative"])
        set_route_condition(world, "shop-alternative", accessible=False, hazard="flooded road")
        self.assertEqual(route_path(world, "shop", "north", mode="walk"), [])
        with self.assertRaises(ValueError):
            world.begin_movement("merchant", "shop-north")

    def test_condition_blocking_pauses_an_actor_until_the_route_reopens(self) -> None:
        world = build_tiny_world()
        set_route_condition(world, "shop-north", accessible=False, hazard="ice storm")
        with self.assertRaises(ValueError):
            world.begin_movement("merchant", "shop-north")
        set_route_condition(world, "shop-north", accessible=True)
        movement = world.begin_movement("merchant", "shop-north")
        tick(world, 12)
        self.assertEqual(world.actors["merchant"].location_id, "shop")
        self.assertEqual(world.movements[movement.id].elapsed_hours, 12)
        set_route_condition(world, "shop-north", accessible=False, hazard="renewed ice storm")
        tick(world, 12)
        self.assertEqual(world.movements[movement.id].elapsed_hours, 12)
        set_route_condition(world, "shop-north", accessible=True)
        tick(world, 36)
        self.assertEqual(world.actors["merchant"].location_id, "north")

    def test_freight_waits_on_a_blocked_route_and_resumes_with_cargo_aboard(self) -> None:
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        world.create_lot("metals", 1, holder_id=seller.id, owner_id=seller.id, provenance=("supplier",))
        add_asset(world, TransportAsset("supply-sloop", "Supply Sloop", "vessel", "shop", buyer.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_facility(world, TransportFacility("shop-landing", "shop", handling_capacity=1))
        add_facility(world, TransportFacility("warehouse-landing", "warehouse", handling_capacity=1))
        contract = create_contract(world, seller.id, buyer.id, "metals", 1, 20, origin_id="shop", destination_id="warehouse", due_days=3)
        shipment = dispatch_freight(world, contract.id, carrier_id="supply-sloop", origin_facility_id="shop-landing", destination_facility_id="warehouse-landing")
        set_route_condition(world, "shop-warehouse", accessible=False, hazard="harbor ice")
        advance_freight(world, 1)
        self.assertEqual(shipment.status, "in_transit")
        self.assertEqual(world.quantity_held("supply-sloop", "metals"), 1)
        advance_freight(world, 1)
        self.assertTrue(any(event.kind == "freight_delayed" for event in world.events))
        advance_freight(world, 10)
        self.assertEqual(shipment.status, "in_transit")
        set_route_condition(world, "shop-warehouse", accessible=True)
        advance_freight(world, 24)
        advance_freight(world, 1)
        self.assertEqual(shipment.status, "delivered")
        self.assertEqual(contract.status, "settled")


if __name__ == "__main__":
    unittest.main()
