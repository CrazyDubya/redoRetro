import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import advance_shipments, borrow, compete, create_contract, dispatch_contract, invest_in_research, mule_bid, repay


class EnterpriseEconomyTests(unittest.TestCase):
    def test_competition_contracts_finance_and_scarcity_use_canonical_state(self) -> None:
        world = build_tiny_world()
        shop = world.businesses["shop-market-cashier"]
        warehouse = world.businesses["warehouse-business"]
        world.create_lot("metals", 10, holder_id=shop.id, owner_id=shop.id)
        world.create_lot("metals", 5, holder_id=warehouse.id, owner_id=warehouse.id)
        shares = compete(world, "shop-market", "metals")
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        warehouse.cash = 100
        shop.cash = 1_000
        borrow(world, "warehouse-business", "shop-market-cashier", 50)
        self.assertEqual(warehouse.debt, 50)
        repay(world, "warehouse-business", "shop-market-cashier", 20)
        self.assertEqual(warehouse.debt, 30)
        invest_in_research(world, "warehouse-business", 10)
        self.assertEqual(warehouse.research, 10)
        contract = create_contract(world, shop.id, warehouse.id, "metals", 2, 20, origin_id="shop", destination_id="warehouse", due_days=2)
        dispatch_contract(world, contract.id)
        advance_shipments(world, 24)
        self.assertEqual(contract.status, "settled")
        self.assertEqual(world.quantity_held(warehouse.id, "metals"), 7)

    def test_scarcity_bidding_moves_actual_goods(self) -> None:
        world = build_tiny_world()
        seller = world.businesses["shop-market-cashier"]
        buyer = world.businesses["warehouse-business"]
        seller.cash = 100
        buyer.cash = 500
        world.create_lot("medicine", 1, holder_id=seller.id, owner_id=seller.id)
        mule_bid(world, buyer.id, seller.id, "medicine", 1, 250)
        self.assertEqual(world.quantity_held(buyer.id, "medicine"), 1)
        self.assertEqual(buyer.cash, 250)


if __name__ == "__main__":
    unittest.main()
