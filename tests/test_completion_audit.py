import unittest

from redos.audit import conservation_errors, validate_world
from redos.bank import deposit, open_account
from redos.bootstrap import build_tiny_world
from redos.harbor import run_harbor_demonstration
from redos.insurance import approve_claim, file_claim, issue_policy, record_loss, settle_claim


class CompletionAuditTests(unittest.TestCase):
    def test_long_harbor_run_is_causally_auditable(self):
        world, report = run_harbor_demonstration(seed=31, days=90)

        self.assertGreater(len(report["journeys"]["completed"]), 20)
        self.assertGreater(len(report["journeys"]["delayed"]), 0)
        self.assertGreater(report["goods_moved"].get("grain", 0.0), 0.0)
        self.assertEqual(report["transport_costs"], report["transport_costs_settled"])
        self.assertEqual(report["transport_costs_outstanding"], 0.0)
        self.assertGreater(report["banking"]["interest_events"], 0)
        self.assertGreater(report["banking"]["fee_events"], 0)
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])
        self.assertEqual(report["invariants"]["market_balance_errors"], [])
        self.assertTrue(report["checkpoints"])
        self.assertTrue(all(not checkpoint["validation_errors"] for checkpoint in report["checkpoints"]))
        self.assertTrue(all(not checkpoint["conservation_errors"] for checkpoint in report["checkpoints"]))

        # A real loss is assessed through the canonical loss registry and can
        # settle while the rest of the world remains autonomous.
        issue_policy(
            world,
            "harbor-mutual",
            "warehouse-business",
            line="cargo",
            region_id="warehouse",
            premium=10.0,
            coverage_limit=25.0,
            policy_id="harbor-cargo-policy-2",
        )
        loss = record_loss(
            world,
            "warehouse-business",
            loss_kind="cargo damage",
            covered_risk="cargo",
            location_id="warehouse",
            verified_loss_amount=25.0,
        )
        claim = file_claim(world, "harbor-cargo-policy-2", loss_event_id=loss.id, loss_amount=25.0)
        approve_claim(world, claim.id)
        settle_claim(world, claim.id)
        self.assertEqual(claim.status, "paid")
        self.assertEqual(validate_world(world), [])
        self.assertEqual(conservation_errors(world), [])

    def test_forged_causal_event_cannot_become_an_insurance_loss(self):
        world, _report = run_harbor_demonstration(seed=32, days=1)
        forged = world.record(
            "policy_issued",
            "an unrelated event with copied loss fields",
            actors=["warehouse-business"],
            entities=["warehouse"],
            data={"loss_kind": "fire", "covered_risk": "cargo", "verified_loss_amount": 1000.0},
        )
        with self.assertRaises(ValueError):
            file_claim(world, "harbor-cargo-policy", loss_event_id=forged.id, loss_amount=10.0)

    def test_rejected_bank_operation_does_not_advance_the_ledger(self):
        world = build_tiny_world(seed=33)
        from redos.model import Business

        world.add(Business("bank", "Harbor Bank", "shop", "bank", cash=10_000.0))
        account = open_account(world, "bank", "warehouse-business", annual_interest_rate=0.365, account_id="atomic-account")
        world.advance(days=10)
        before = (account.balance, account.last_accrued_at, len(world.events))
        world.businesses["warehouse-business"].cash = 0.0
        with self.assertRaises(ValueError):
            deposit(world, account.id, 50.0)
        self.assertEqual((account.balance, account.last_accrued_at, len(world.events)), before)


if __name__ == "__main__":
    unittest.main()
