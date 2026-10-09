import unittest

from redos.bootstrap import build_tiny_world
from redos.merchant import evaluate_merchant_route
from redos.model import TransportAsset, TransportService
from redos.transport import add_asset, add_service


class MerchantPrinceRouteTests(unittest.TestCase):
    def test_circular_route_evaluation_uses_each_towns_physical_market(self):
        world = build_tiny_world(seed=157)
        owner = world.businesses["shop-market-cashier"]
        add_asset(world, TransportAsset("merchant-line", "Merchant Line", "cart", "shop", owner.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1, operating_cost_per_hour=0.25))
        add_service(world, TransportService("merchant-circle", "merchant-line", ("shop", "north", "south"), accepted_good_type_ids=("metals", "medicine")))
        world.markets["north-market"].demand_backlog["metals"] = 20
        world.markets["south-market"].demand_backlog["medicine"] = 20
        legs = evaluate_merchant_route(
            world,
            "merchant-circle",
            ("shop-market", "north-market", "south-market"),
            ("metals", "medicine"),
            fuel_price=2.0,
        )
        self.assertTrue(legs)
        self.assertTrue(all(leg.service_id == "merchant-circle" for leg in legs))
        self.assertTrue(all(leg.trade.expected_margin > 0 for leg in legs))
        self.assertTrue(any(leg.origin_market_id == "shop-market" and leg.destination_market_id == "north-market" for leg in legs))

    def test_route_evaluation_does_not_mutate_clock_or_inventory(self):
        world = build_tiny_world(seed=158)
        owner = world.businesses["shop-market-cashier"]
        add_asset(world, TransportAsset("merchant-line", "Merchant Line", "cart", "shop", owner.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1))
        add_service(world, TransportService("merchant-circle", "merchant-line", ("shop", "north", "south")))
        before = (world.now, {lot.id: lot.quantity for lot in world.lots.values()})
        evaluate_merchant_route(world, "merchant-circle", ("shop-market", "north-market", "south-market"), ("metals", "medicine"))
        self.assertEqual(world.now, before[0])
        self.assertEqual({lot.id: lot.quantity for lot in world.lots.values()}, before[1])


if __name__ == "__main__":
    unittest.main()
