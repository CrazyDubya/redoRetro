import unittest

from redos.bootstrap import build_tiny_world
from redos.insider import buy_information, execute_trade, issue_security, portfolio_value, publish_wire_event
from redos.model import Actor


class InsideTraderTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=81)
        issuer = world.businesses["warehouse-business"]
        issuer.cash = 100.0
        buyer = world.actors["merchant"]
        buyer.money = 500.0
        seller = world.actors["cooper"]
        seller.money = 100.0
        security = issue_security(world, issuer.id, security_id="warehouse-stock", name="Warehouse Stock", shares=10.0, initial_price=20.0)
        # Move a tradable block to the seller using the same execution gateway.
        execute_trade(world, seller.id, issuer.id, security.id, 4.0, price=20.0, order_id="seed-trade")
        return world, issuer, buyer, seller, security

    def test_trade_moves_finite_shares_and_money_and_updates_price(self):
        world, _issuer, buyer, seller, security = self._world()
        order = execute_trade(world, buyer.id, seller.id, security.id, 2.0, price=25.0, order_id="trade-1")
        self.assertEqual(order.status, "filled")
        self.assertEqual(world.security_holdings["holding-2"].quantity, 2.0)
        self.assertEqual(buyer.money, 450.0)
        self.assertEqual(seller.money, 70.0)
        self.assertEqual(security.price, 25.0)
        self.assertEqual(sum(h.quantity for h in world.security_holdings.values() if h.security_id == security.id), 10.0)
        self.assertEqual(portfolio_value(world, buyer.id), 50.0)

    def test_insolvent_trade_does_not_remove_shares(self):
        world, _issuer, buyer, seller, security = self._world()
        buyer.money = 1.0
        before = [(h.id, h.quantity) for h in world.security_holdings.values()]
        with self.assertRaises(ValueError):
            execute_trade(world, buyer.id, seller.id, security.id, 1.0, price=20.0)
        self.assertEqual([(h.id, h.quantity) for h in world.security_holdings.values()], before)

    def test_information_uses_existing_statement_and_belief_provenance(self):
        world, _issuer, buyer, seller, _security = self._world()
        wire_id = publish_wire_event(world, seller.id, "warehouse_orders", "orders are rising")
        self.assertIn(wire_id, {event.id for event in world.events})
        statement = buy_information(
            world,
            buyer.id,
            seller.id,
            "warehouse_orders",
            "orders are rising",
            cost=5.0,
            truthful=True,
        )
        self.assertEqual(buyer.beliefs["warehouse_orders"], "orders are rising")
        self.assertEqual(buyer.belief_provenance["warehouse_orders"].source_id, statement.id)
        self.assertEqual(buyer.money, 495.0)


if __name__ == "__main__":
    unittest.main()
