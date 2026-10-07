import unittest

from redos.bootstrap import build_tiny_world
from redos.market import autonomous_trade, bargain, buy, quote, sell, travel


class StarTraderMarketTests(unittest.TestCase):
    def test_differentiated_markets_and_physical_autonomous_trade(self) -> None:
        world = build_tiny_world()
        world.markets["shop-market"].balances["metals"] = 20.0
        world.markets["north-market"].balances["metals"] = -20.0
        world.create_lot("metals", 20.0, holder_id="shop", owner_id="shop", provenance=("seeded surplus",))
        before_shop = world.quantity_held("shop", "metals")
        before_north = world.quantity_held("north", "metals")
        result = autonomous_trade(world, "merchant", "shop-market", "north", "metals", 5.0)
        self.assertEqual(result["travel_days"], 2)
        self.assertGreater(result["profit"], 0)
        self.assertLess(world.quantity_held("shop", "metals"), before_shop)
        self.assertEqual(world.quantity_held("merchant", "metals"), 0)
        self.assertAlmostEqual(world.quantity_held("north", "metals"), before_north + 5.0)
        self.assertEqual(world.actors["merchant"].location_id, "north")
        self.assertTrue(any(event.kind == "trade" for event in world.events))

    def test_market_quotes_respond_to_supply_and_shortage(self) -> None:
        world = build_tiny_world()
        market = world.markets["shop-market"]
        world.create_lot("medicine", 40, holder_id="shop", owner_id="shop")
        surplus = quote(world, "shop-market", "medicine", 1, side="buy").unit_price
        world.consume_goods("shop", "medicine", world.quantity_held("shop", "medicine"))
        shortage = quote(world, "shop-market", "medicine", 1, side="buy").unit_price
        self.assertLess(surplus, shortage)

    def test_bounded_bargaining_and_route_time(self) -> None:
        world = build_tiny_world()
        self.assertTrue(bargain(100, 105, side="buy", round_number=1))
        self.assertFalse(bargain(100, 200, side="buy", round_number=1))
        self.assertEqual(travel(world, "merchant", "north"), 2)
        self.assertEqual(world.now.day, 1)
        from redos.simulation import tick
        tick(world, 48)
        self.assertEqual(world.now.day, 3)


if __name__ == "__main__":
    unittest.main()
