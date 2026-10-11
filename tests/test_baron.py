import unittest
import math
from datetime import timedelta

from redos.bootstrap import build_tiny_world
from redos.model import Household, Property
from redos.realestate import add_property, advance_rents, buy_property, collect_rent, lease_property, update_property_market


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

    def test_re_registering_active_lease_cannot_reset_rent_period(self):
        world, property, _owner, _buyer = self._world()
        tenant = world.households["tenant-household"]
        lease_property(world, property.id, tenant.id)
        collect_rent(world, property.id)
        lease_property(world, property.id, tenant.id)
        with self.assertRaises(ValueError):
            collect_rent(world, property.id)
        self.assertTrue(any(event.kind == "lease_unchanged" for event in world.events))

    def test_property_market_update_rejects_overflow_without_mutating_state(self):
        world, property, _owner, _buyer = self._world()
        property.market_value = 1e308
        before_history = list(property.value_history)
        with self.assertRaises(ValueError):
            update_property_market(world, property.id, 2.0, reason="overflow")
        self.assertTrue(math.isfinite(property.market_value))
        self.assertEqual(property.market_value, 1e308)
        self.assertEqual(property.value_history, before_history)

    def test_unpaid_rent_is_one_retryable_arrears_obligation(self):
        world, property, _owner, _buyer = self._world()
        tenant = world.households["tenant-household"]
        lease_property(world, property.id, tenant.id)
        tenant.cash = 0.0
        advance_rents(world)
        obligations = world.runtime["_rent_obligations"]
        open_obligations = [obligation for obligation in obligations.values() if obligation["status"] == "open"]
        self.assertEqual(len(open_obligations), 1)
        self.assertEqual(tenant.debt, property.monthly_rent)
        # A retry on the same due period must not create another debt entry.
        advance_rents(world)
        self.assertEqual(len([obligation for obligation in obligations.values() if obligation["status"] == "open"]), 1)
        tenant.cash = 20.0
        world.now += timedelta(days=31)
        advance_rents(world)
        self.assertEqual(tenant.debt, 0.0)
        self.assertTrue(any(event.kind == "rent_arrears_settled" for event in world.events))
        self.assertTrue(all(obligation["status"] == "settled" for obligation in obligations.values()))

    def test_sale_preserves_arrears_creditor(self):
        world, property, owner, buyer = self._world()
        tenant = world.households["tenant-household"]
        lease_property(world, property.id, tenant.id)
        tenant.cash = 0.0
        advance_rents(world)
        before_owner = owner.cash
        before_buyer = buyer.cash
        buy_property(world, property.id, buyer.id, owner.id)
        tenant.cash = 20.0
        world.now += timedelta(days=31)
        advance_rents(world)
        self.assertEqual(owner.cash, before_owner + property.market_value + 10.0)
        self.assertEqual(buyer.cash, before_buyer - property.market_value + 10.0)
        settled = [event for event in world.events if event.kind == "rent_arrears_settled"]
        self.assertTrue(settled)
        self.assertEqual(settled[-1].data["creditor"], owner.id)

    def test_former_tenant_arrears_settle_after_lease_ends(self):
        world, property, owner, _buyer = self._world()
        former_tenant = world.households["tenant-household"]
        new_tenant = Household("new-tenant-household", "New Tenant household", "tavern", cash=0.0)
        world.add(new_tenant)
        lease_property(world, property.id, former_tenant.id)
        former_tenant.cash = 0.0
        advance_rents(world)
        lease_property(world, property.id, new_tenant.id)
        former_tenant.cash = 10.0
        before_owner = owner.cash
        advance_rents(world)
        self.assertEqual(owner.cash, before_owner + 10.0)
        self.assertEqual(former_tenant.debt, 0.0)
        self.assertTrue(all(obligation["status"] == "settled" for obligation in world.runtime["_rent_obligations"].values() if obligation["tenant_id"] == former_tenant.id))


if __name__ == "__main__":
    unittest.main()
