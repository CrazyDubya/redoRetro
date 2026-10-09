import unittest

from redos.bootstrap import build_tiny_world
from redos.model import TransportAsset, TransportFacility
from redos.ocean import book_ocean_trade, quote_ocean_trade, select_ocean_trade
from redos.transport import add_asset, add_facility, advance_freight


class OceanTraderTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=127)
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["north-market-cashier"]
        seller.cash = 500_000.0
        buyer.cash = 500_000.0
        world.create_lot("metals", 3, holder_id=seller.id, owner_id=seller.id, provenance=("ocean-trader-test",))
        world.create_lot("metals", 3, holder_id="shop", owner_id=seller.id, provenance=("ocean-trader-port-stock",))
        # Make the destination market scarce, so its derived sell price is
        # visibly above the source buy price.
        world.markets["north-market"].demand_backlog["metals"] = 20.0
        add_asset(world, TransportAsset("trade-cart", "Trade Cart", "cart", "shop", seller.id, capacity=2, fuel=100, fuel_capacity=100, fuel_burn_per_hour=0.1, operating_cost_per_hour=1.0))
        add_facility(world, TransportFacility("trade-origin", "shop", 1))
        add_facility(world, TransportFacility("trade-destination", "north", 1))
        return world, seller, buyer

    def test_quote_uses_physical_stock_capacity_price_spread_and_cost(self):
        world, _seller, _buyer = self._world()
        trade = quote_ocean_trade(world, "shop-market", "north-market", "metals", "trade-cart", quantity=2, fuel_price=3.0)
        self.assertEqual(trade.quantity, 2)
        self.assertLess(trade.buy_unit_price, trade.sell_unit_price)
        self.assertGreater(trade.travel_hours, 0)
        self.assertGreater(trade.estimated_operating_cost, 0)
        self.assertGreater(trade.expected_margin, 0)

    def test_selection_chooses_a_carryable_positive_margin(self):
        world, _seller, _buyer = self._world()
        trade = select_ocean_trade(world, "shop-market", "north-market", "trade-cart", ("metals", "food"))
        self.assertIsNotNone(trade)
        self.assertEqual(trade.good_type_id, "metals")
        self.assertLessEqual(trade.quantity, world.transport_assets["trade-cart"].capacity)

    def test_booking_uses_the_existing_physical_freight_path(self):
        world, seller, buyer = self._world()
        trade = quote_ocean_trade(world, "shop-market", "north-market", "metals", "trade-cart", quantity=1)
        shipment = book_ocean_trade(
            world,
            trade,
            seller_id=seller.id,
            buyer_id=buyer.id,
            origin_facility_id="trade-origin",
            destination_facility_id="trade-destination",
            due_days=4,
        )
        self.assertEqual(world.quantity_held("trade-cart", "metals"), 0)
        advance_freight(world, 1)
        self.assertEqual(world.quantity_held("trade-cart", "metals"), 1)
        advance_freight(world, 49)
        self.assertEqual(shipment.status, "delivered")
        self.assertGreaterEqual(world.quantity_held("north", "metals"), 1)
        self.assertTrue(any(event.kind == "ocean_trade_booked" for event in world.events))


if __name__ == "__main__":
    unittest.main()
