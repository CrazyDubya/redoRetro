import unittest

from redos.bootstrap import build_tiny_world
from redos.model import Household, Property
from redos.realestate import add_property, buy_property, collect_rent, lease_property, update_property_market


class BaronTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=51)
        owner = world.businesses["warehouse-business"]
        buyer = world.businesses["tavern-business"]
        world.add(Household("tenant-household", "Tenant household", "tavern", cash=100.0))
        property = add_property(
            world,
            Property("warehouse-unit", "Warehouse Unit", "warehouse", "business", owner.id, market_value=200.0, monthly_rent=10.0),
        )
        return world, property, owner, buyer

    def test_property_market_history_and_transfer_use_canonical_state(self):
        world, property, owner, buyer = self._world()
        before_buyer = buyer.cash
        update_property_market(world, property.id, 1.25, reason="harbor expansion")
        self.assertEqual(property.market_value, 250.0)
        self.assertEqual(len(property.value_history), 2)
        buy_property(world, property.id, buyer.id, owner.id)
        self.assertEqual(property.owner_id, buyer.id)
        self.assertEqual(buyer.cash, before_buyer - 250.0)
        self.assertEqual(owner.cash, 1_250.0)
        self.assertTrue(any(event.kind == "property_transferred" for event in world.events))

    def test_lease_rent_transfers_money_and_missing_cash_does_not_change_owner(self):
        world, property, owner, _buyer = self._world()
        tenant = world.households["tenant-household"]
        lease_property(world, property.id, tenant.id)
        before_owner = owner.cash
        self.assertEqual(collect_rent(world, property.id), 10.0)
        self.assertEqual(owner.cash, before_owner + 10.0)
        tenant.cash = 0.0
        with self.assertRaises(ValueError):
            collect_rent(world, property.id)
        self.assertEqual(property.owner_id, owner.id)
        self.assertEqual(owner.cash, before_owner + 10.0)

    def test_property_sale_preserves_existing_tenancy(self):
        world, property, owner, buyer = self._world()
        tenant = world.households["tenant-household"]
        before_buyer = buyer.cash
        lease_property(world, property.id, tenant.id)
        buy_property(world, property.id, buyer.id, owner.id)
        self.assertEqual(property.owner_id, buyer.id)
        self.assertEqual(property.occupied_by_id, tenant.id)
        world.advance(days=30)
        self.assertEqual(collect_rent(world, property.id), 10.0)
        self.assertEqual(buyer.cash, before_buyer - property.market_value + 10.0)


if __name__ == "__main__":
    unittest.main()
