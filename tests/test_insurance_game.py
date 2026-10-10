import unittest

from redos.bootstrap import build_tiny_world
from redos.insurance import approve_claim, file_claim, insurer_exposure, issue_policy, record_loss, settle_claim
from redos.model import Business


class InsuranceGameTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=71)
        world.add(Business("insurer", "Harbor Mutual", "shop", "insurer", cash=500.0))
        customer = world.businesses["warehouse-business"]
        customer.cash = 200.0
        return world, world.businesses["insurer"], customer

    def test_policy_requires_premium_and_event_linked_claim(self):
        world, insurer, customer = self._world()
        policy = issue_policy(
            world,
            insurer.id,
            customer.id,
            line="property",
            region_id="warehouse",
            premium=25.0,
            coverage_limit=100.0,
            deductible=10.0,
            policy_id="policy-1",
        )
        self.assertEqual(customer.cash, 175.0)
        loss = record_loss(world, customer.id, loss_kind="flood", covered_risk="property", location_id="warehouse", verified_loss_amount=140.0, description="warehouse stock damaged")
        claim = file_claim(world, policy.id, loss_event_id=loss.id, loss_amount=140.0, claim_id="claim-1")
        self.assertEqual(claim.indemnity, 100.0)
        self.assertEqual(approve_claim(world, claim.id), 100.0)
        self.assertEqual(settle_claim(world, claim.id), 100.0)
        self.assertEqual(claim.status, "paid")
        self.assertEqual(customer.cash, 275.0)
        self.assertEqual(insurer.cash, 425.0)

    def test_unrelated_event_cannot_create_claim_and_insolvent_settlement_preserves_obligation(self):
        world, insurer, customer = self._world()
        policy = issue_policy(
            world,
            insurer.id,
            customer.id,
            line="cargo",
            region_id="warehouse",
            premium=10.0,
            coverage_limit=80.0,
            policy_id="policy-2",
        )
        unrelated = world.record("dock_fire", "a different merchant's cargo burned", actors=["merchant"])
        with self.assertRaises(ValueError):
            file_claim(world, policy.id, loss_event_id=unrelated.id, loss_amount=20.0)
        loss = record_loss(world, customer.id, loss_kind="theft", covered_risk="cargo", location_id="warehouse", verified_loss_amount=60.0, description="customer cargo damaged")
        claim = file_claim(world, policy.id, loss_event_id=loss.id, loss_amount=60.0, claim_id="claim-2")
        approve_claim(world, claim.id)
        insurer.cash = 0.0
        before = (claim.status, customer.cash)
        with self.assertRaises(ValueError):
            settle_claim(world, claim.id)
        self.assertEqual((claim.status, customer.cash), before)
        self.assertEqual(insurer_exposure(world, insurer.id)["approved_claims"], 60.0)


if __name__ == "__main__":
    unittest.main()
