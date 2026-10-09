import unittest

from redos.bank import (
    accrue_deposit_interest,
    accrue_loan_interest,
    balance_sheet,
    deposit,
    open_account,
    originate_loan,
    repay_loan,
    withdraw,
)
from redos.bootstrap import build_tiny_world
from redos.model import Business


class BankManagementSimulationTests(unittest.TestCase):
    def _world(self):
        world = build_tiny_world(seed=61)
        world.add(Business("bank", "Harbor Bank", "shop", "bank", cash=1_000.0))
        customer = world.businesses["warehouse-business"]
        customer.cash = 500.0
        return world, world.businesses["bank"], customer

    def test_deposits_are_cash_backed_and_withdrawals_are_atomic(self):
        world, bank, customer = self._world()
        account = open_account(world, bank.id, customer.id, minimum_balance=50.0, account_id="checking")
        deposit(world, account.id, 200.0)
        self.assertEqual(account.balance, 200.0)
        self.assertEqual(customer.cash, 300.0)
        self.assertEqual(bank.cash, 1_200.0)
        withdraw(world, account.id, 100.0)
        self.assertEqual(account.balance, 100.0)
        self.assertEqual(customer.cash, 400.0)
        before = (account.balance, customer.cash, bank.cash)
        with self.assertRaises(ValueError):
            withdraw(world, account.id, 60.1)
        self.assertEqual((account.balance, customer.cash, bank.cash), before)

    def test_interest_is_time_based_and_auditable(self):
        world, bank, customer = self._world()
        account = open_account(world, bank.id, customer.id, annual_interest_rate=0.365, account_id="savings")
        deposit(world, account.id, 100.0)
        world.advance(days=10)
        interest = accrue_deposit_interest(world, account.id)
        self.assertAlmostEqual(interest, 1.0, places=6)
        self.assertAlmostEqual(account.balance, 101.0, places=6)
        self.assertTrue(any(event.kind == "deposit_interest_accrued" for event in world.events))

    def test_loan_updates_existing_debt_and_settles_interest_before_principal(self):
        world, bank, customer = self._world()
        loan = originate_loan(world, bank.id, customer.id, 200.0, annual_interest_rate=0.365, term_days=30, loan_id="loan-1")
        self.assertEqual(customer.cash, 700.0)
        self.assertEqual(customer.debt, 200.0)
        world.advance(days=10)
        self.assertAlmostEqual(accrue_loan_interest(world, loan.id), 2.0, places=6)
        self.assertAlmostEqual(repay_loan(world, loan.id, 50.0), 50.0, places=6)
        self.assertAlmostEqual(loan.accrued_interest, 0.0, places=6)
        self.assertAlmostEqual(loan.outstanding_principal, 152.0, places=6)
        self.assertAlmostEqual(customer.debt, 152.0, places=6)
        self.assertEqual(loan.status, "open")

    def test_insolvent_loan_and_withdrawal_do_not_mutate_ledgers(self):
        world, bank, customer = self._world()
        account = open_account(world, bank.id, customer.id, account_id="thin")
        deposit(world, account.id, 20.0)
        customer.cash = 0.0
        before_account = account.balance
        with self.assertRaises(ValueError):
            deposit(world, account.id, 1.0)
        self.assertEqual(account.balance, before_account)
        loan = originate_loan(world, bank.id, customer.id, 10.0, loan_id="loan-2")
        customer.cash = 0.0
        before = (loan.outstanding_principal, loan.accrued_interest, bank.cash)
        with self.assertRaises(ValueError):
            repay_loan(world, loan.id, 1.0)
        self.assertEqual((loan.outstanding_principal, loan.accrued_interest, bank.cash), before)

    def test_balance_sheet_is_derived_from_open_obligations(self):
        world, bank, customer = self._world()
        account = open_account(world, bank.id, customer.id, account_id="ledger")
        deposit(world, account.id, 100.0)
        loan = originate_loan(world, bank.id, customer.id, 50.0, annual_interest_rate=0.365, loan_id="loan-3")
        world.advance(days=1)
        accrue_loan_interest(world, loan.id)
        sheet = balance_sheet(world, bank.id)
        self.assertEqual(sheet["cash"], bank.cash)
        self.assertEqual(sheet["deposits"], 100.0)
        self.assertEqual(sheet["loans"], 50.0)
        self.assertGreater(sheet["accrued_loan_interest"], 0.0)


if __name__ == "__main__":
    unittest.main()
