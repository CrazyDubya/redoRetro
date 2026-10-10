"""Bank Management Simulation financial-service kernels.

Bank accounts and loans are explicit obligations backed by the existing
canonical cash fields.  The module does not create a second money system:
deposits and withdrawals move cash through ``World.pay`` and loans feed the
borrower's existing debt aggregate.
"""

from __future__ import annotations

from datetime import timedelta
import math

from .model import BankAccount, BankLoan, Business, Household, World, require_finite


def _money_holder(world: World, holder_id: str):
    holder = world.actors.get(holder_id) or world.businesses.get(holder_id) or world.households.get(holder_id)
    if holder is None:
        raise KeyError(f"unknown money holder {holder_id!r}")
    return holder


def _bank(world: World, bank_id: str) -> Business:
    bank = world.businesses.get(bank_id)
    if bank is None or bank.kind != "bank":
        raise ValueError(f"{bank_id} is not a bank business")
    return bank


def _debt_holder(world: World, borrower_id: str):
    return _money_holder(world, borrower_id)


def _add_debt(holder, amount: float) -> None:
    if not hasattr(holder, "debt"):
        raise ValueError(f"{holder.id} cannot carry debt")
    holder.debt += amount


def _reduce_debt(holder, amount: float) -> None:
    if not hasattr(holder, "debt"):
        raise ValueError(f"{holder.id} cannot carry debt")
    holder.debt = max(0.0, holder.debt - amount)


def _finite(value: float, label: str) -> None:
    require_finite(value, label)


def _projected_deposit_interest(world: World, account: BankAccount) -> tuple[float, float]:
    """Return elapsed interest and resulting balance without mutating the account."""
    _finite(account.balance, f"{account.id} balance")
    last = account.last_accrued_at or account.opened_at or world.now
    elapsed_days = max(0.0, (world.now - last).total_seconds() / 86400.0)
    interest = account.balance * account.annual_interest_rate * elapsed_days / 365.0
    _finite(interest, f"{account.id} interest")
    _finite(account.balance + interest, f"{account.id} balance")
    return interest, account.balance + interest


def open_account(
    world: World,
    bank_id: str,
    customer_id: str,
    *,
    account_type: str = "demand",
    annual_interest_rate: float = 0.0,
    minimum_balance: float = 0.0,
    service_charge: float = 0.0,
    account_id: str | None = None,
) -> BankAccount:
    _bank(world, bank_id)
    _money_holder(world, customer_id)
    if account_type not in {"demand", "time"}:
        raise ValueError("account type must be demand or time")
    for value, label in ((annual_interest_rate, "annual interest rate"), (minimum_balance, "minimum balance"), (service_charge, "service charge")):
        _finite(value, label)
    if annual_interest_rate < 0 or minimum_balance < 0 or service_charge < 0:
        raise ValueError("bank account terms cannot be negative")
    account_id = account_id or f"bank-account-{len(world.bank_accounts) + 1}"
    if account_id in world.bank_accounts:
        raise ValueError(f"bank account {account_id} already exists")
    account = BankAccount(
        id=account_id,
        bank_id=bank_id,
        customer_id=customer_id,
        account_type=account_type,
        annual_interest_rate=annual_interest_rate,
        minimum_balance=minimum_balance,
        service_charge=service_charge,
        opened_at=world.now,
        last_accrued_at=world.now,
    )
    world.add(account)
    world.record(
        "bank_account_opened",
        f"{customer_id} opened {account_type} account at {bank_id}",
        actors=[bank_id, customer_id],
        entities=[account.id],
        data={"account_type": account_type, "annual_interest_rate": annual_interest_rate},
    )
    return account


def deposit(world: World, account_id: str, amount: float) -> None:
    _finite(amount, "deposit")
    if amount <= 0:
        raise ValueError("deposit must be positive")
    account = world.bank_accounts[account_id]
    if account.status != "open":
        raise ValueError("account is not open")
    customer = _money_holder(world, account.customer_id)
    if account.customer_id == account.bank_id:
        raise ValueError("account customer and bank must be distinct")
    customer_field = "money" if hasattr(customer, "money") else "cash"
    customer_balance = getattr(customer, customer_field)
    if not math.isfinite(customer_balance) or customer_balance + 1e-9 < amount:
        raise ValueError(f"{account.customer_id} cannot fund deposit")
    bank = _bank(world, account.bank_id)
    if not math.isfinite(bank.cash):
        raise ValueError(f"{account.bank_id} has non-finite cash")
    interest, projected_balance = _projected_deposit_interest(world, account)
    _finite(projected_balance + amount, f"{account.id} balance")
    # Close the old balance's interest period before adding new principal;
    # otherwise a deposit made later would earn interest retroactively.
    accrue_deposit_interest(world, account_id)
    world.pay(account.customer_id, account.bank_id, amount, reason=f"deposit into {account.id}")
    account.balance += amount
    world.record(
        "bank_deposit",
        f"{account.customer_id} deposited into {account.id}",
        actors=[account.customer_id, account.bank_id],
        entities=[account.id],
        data={"amount": amount, "balance": account.balance},
    )


def withdraw(world: World, account_id: str, amount: float) -> None:
    _finite(amount, "withdrawal")
    if amount <= 0:
        raise ValueError("withdrawal must be positive")
    account = world.bank_accounts[account_id]
    bank = _bank(world, account.bank_id)
    if account.status != "open":
        raise ValueError("account is not open")
    if account.customer_id == account.bank_id:
        raise ValueError("account customer and bank must be distinct")
    interest, projected_balance = _projected_deposit_interest(world, account)
    if projected_balance - amount < account.minimum_balance - 1e-9:
        raise ValueError("withdrawal would breach minimum balance")
    if bank.cash + 1e-9 < amount:
        raise ValueError("bank cannot fund withdrawal")
    customer = _money_holder(world, account.customer_id)
    customer_field = "money" if hasattr(customer, "money") else "cash"
    if not math.isfinite(getattr(customer, customer_field)):
        raise ValueError(f"{account.customer_id} has non-finite cash")
    accrue_deposit_interest(world, account_id)
    # World.pay validates bank liquidity before the account ledger changes.
    world.pay(account.bank_id, account.customer_id, amount, reason=f"withdrawal from {account.id}")
    account.balance -= amount
    world.record(
        "bank_withdrawal",
        f"{account.customer_id} withdrew from {account.id}",
        actors=[account.customer_id, bank.id],
        entities=[account.id],
        data={"amount": amount, "balance": account.balance},
    )


def accrue_deposit_interest(world: World, account_id: str) -> float:
    account = world.bank_accounts[account_id]
    if account.status != "open":
        raise ValueError("account is not open")
    last = account.last_accrued_at or account.opened_at or world.now
    elapsed_days = max(0.0, (world.now - last).total_seconds() / 86400.0)
    interest = account.balance * account.annual_interest_rate * elapsed_days / 365.0
    _finite(interest, f"{account.id} interest")
    account.last_accrued_at = world.now
    if interest <= 0:
        return 0.0
    account.balance += interest
    world.record(
        "deposit_interest_accrued",
        f"interest accrued on {account.id}",
        actors=[account.bank_id, account.customer_id],
        entities=[account.id],
        data={"amount": interest, "balance": account.balance, "days": elapsed_days},
    )
    return interest


def originate_loan(
    world: World,
    bank_id: str,
    borrower_id: str,
    principal: float,
    *,
    annual_interest_rate: float = 0.0,
    term_days: int | None = None,
    loan_id: str | None = None,
) -> BankLoan:
    bank = _bank(world, bank_id)
    borrower = _debt_holder(world, borrower_id)
    _finite(principal, "loan principal")
    _finite(annual_interest_rate, "loan interest rate")
    if principal <= 0 or annual_interest_rate < 0 or (term_days is not None and term_days <= 0):
        raise ValueError("invalid loan terms")
    if bank.cash + 1e-9 < principal:
        raise ValueError("bank cannot fund loan")
    if not hasattr(borrower, "debt"):
        raise ValueError(f"{borrower_id} cannot carry debt")
    loan_id = loan_id or f"bank-loan-{len(world.bank_loans) + 1}"
    if loan_id in world.bank_loans:
        raise ValueError(f"bank loan {loan_id} already exists")
    due_at = world.now + timedelta(days=term_days) if term_days is not None else None
    # Payment is the only cash mutation; all loan fields are changed after it succeeds.
    payment = world.pay(bank_id, borrower_id, principal, reason=f"loan disbursement {loan_id}")
    loan = BankLoan(
        id=loan_id,
        bank_id=bank_id,
        borrower_id=borrower_id,
        principal=principal,
        outstanding_principal=principal,
        annual_interest_rate=annual_interest_rate,
        issued_at=world.now,
        due_at=due_at,
        last_accrued_at=world.now,
    )
    world.add(loan)
    _add_debt(borrower, principal)
    world.record(
        "bank_loan_originated",
        f"{bank_id} lent to {borrower_id}",
        actors=[bank_id, borrower_id],
        entities=[loan.id],
        causes=[payment.id],
        data={"principal": principal, "annual_interest_rate": annual_interest_rate, "due_at": due_at.isoformat() if due_at else None},
    )
    return loan


def accrue_loan_interest(world: World, loan_id: str) -> float:
    loan = world.bank_loans[loan_id]
    if loan.status != "open":
        raise ValueError("loan is not open")
    last = loan.last_accrued_at or loan.issued_at
    elapsed_days = max(0.0, (world.now - last).total_seconds() / 86400.0)
    interest = loan.outstanding_principal * loan.annual_interest_rate * elapsed_days / 365.0
    _finite(interest, f"{loan.id} interest")
    _finite(loan.accrued_interest + interest, f"{loan.id} accrued interest")
    loan.last_accrued_at = world.now
    if interest <= 0:
        return 0.0
    loan.accrued_interest += interest
    world.record(
        "loan_interest_accrued",
        f"interest accrued on {loan.id}",
        actors=[loan.bank_id, loan.borrower_id],
        entities=[loan.id],
        data={"amount": interest, "accrued_interest": loan.accrued_interest, "days": elapsed_days},
    )
    return interest


def repay_loan(world: World, loan_id: str, amount: float) -> float:
    _finite(amount, "repayment")
    if amount <= 0:
        raise ValueError("repayment must be positive")
    loan = world.bank_loans[loan_id]
    if loan.status != "open":
        raise ValueError("loan is not open")
    # Preflight the elapsed interest and the resulting payment before
    # mutating the loan.  The final repayment must include interest earned
    # since the last explicit accrual call.
    last = loan.last_accrued_at or loan.issued_at
    elapsed_days = max(0.0, (world.now - last).total_seconds() / 86400.0)
    projected_interest = loan.outstanding_principal * loan.annual_interest_rate * elapsed_days / 365.0
    due = loan.accrued_interest + projected_interest + loan.outstanding_principal
    payment_amount = min(amount, due)
    borrower = _debt_holder(world, loan.borrower_id)
    if getattr(borrower, "money", getattr(borrower, "cash", 0.0)) + 1e-9 < payment_amount:
        raise ValueError(f"{loan.borrower_id} cannot pay {payment_amount}")
    if projected_interest > 0:
        loan.accrued_interest += projected_interest
    loan.last_accrued_at = world.now
    payment = world.pay(loan.borrower_id, loan.bank_id, payment_amount, reason=f"loan repayment {loan.id}")
    interest_paid = min(payment_amount, loan.accrued_interest)
    principal_paid = payment_amount - interest_paid
    loan.accrued_interest -= interest_paid
    loan.outstanding_principal -= principal_paid
    _reduce_debt(_debt_holder(world, loan.borrower_id), principal_paid)
    if loan.outstanding_principal <= 1e-9 and loan.accrued_interest <= 1e-9:
        loan.outstanding_principal = 0.0
        loan.accrued_interest = 0.0
        loan.status = "repaid"
    world.record(
        "bank_loan_repayment",
        f"{loan.borrower_id} repaid {loan.id}",
        actors=[loan.bank_id, loan.borrower_id],
        entities=[loan.id],
        causes=[payment.id],
        data={"amount": payment_amount, "principal_paid": principal_paid, "interest_paid": interest_paid, "status": loan.status},
    )
    return payment_amount


def charge_account_fee(world: World, account_id: str, amount: float | None = None) -> float:
    account = world.bank_accounts[account_id]
    fee = account.service_charge if amount is None else amount
    _finite(fee, "service charge")
    if fee <= 0:
        raise ValueError("service charge must be positive")
    _interest, projected_balance = _projected_deposit_interest(world, account)
    if projected_balance - fee < account.minimum_balance - 1e-9:
        raise ValueError("service charge would breach minimum balance after interest accrual")
    accrue_deposit_interest(world, account_id)
    # A deposit-account fee reduces the bank's deposit liability.  Calling
    # withdraw here would incorrectly send the fee from the bank back to the
    # customer and reverse the intended income.
    account.balance -= fee
    world.record(
        "bank_service_charge",
        f"service charge assessed on {account.id}",
        actors=[account.bank_id, account.customer_id],
        entities=[account.id],
        data={"amount": fee, "balance": account.balance},
    )
    return fee


def balance_sheet(world: World, bank_id: str) -> dict[str, float]:
    bank = _bank(world, bank_id)
    deposits = sum(account.balance for account in world.bank_accounts.values() if account.bank_id == bank_id and account.status == "open")
    loans = sum(loan.outstanding_principal for loan in world.bank_loans.values() if loan.bank_id == bank_id and loan.status == "open")
    accrued_interest = sum(loan.accrued_interest for loan in world.bank_loans.values() if loan.bank_id == bank_id and loan.status == "open")
    return {"cash": bank.cash, "deposits": deposits, "loans": loans, "accrued_loan_interest": accrued_interest}
