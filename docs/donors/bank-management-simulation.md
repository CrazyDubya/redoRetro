# Bank Management Simulation — financial-service kernel

## Evidence inspected

- [MobyGames entry for Bank Management Simulation](https://www.mobygames.com/game/199144/bank-management-simulation/), which identifies the 1960 IBM/McKinsey mainframe serious game and describes managing a bank's assets through rates, service charges, administration and promotion.
- [BMSim Decision Manual](https://www.gsblsu.org/wp-content/uploads/2020/04/BMSim-Decision-Manual-2020-v1.1.pdf), a later manual for the BankSim lineage. Its overview and balance-sheet reports describe deposits, loans, interest income/expense, liquidity and quarter-based management decisions. The manual is evidence for the durable banking mechanisms, not a claim that its later product set is the 1960 implementation.
- [Stanford Bank Management Simulation player-instructions record](https://texashistory.unt.edu/ark:/67531/metapth1374705/), a catalog record for surviving period player instructions covering the bank's purpose, decisions, statement of condition and income statement. The scan was not available through the text endpoint during this pass.

## Verified and selected

The durable mechanic worth translating is an intermediary bank that allocates cash between customer deposits and loans while pricing those products with interest and service charges. Redos now represents that as:

- `BankAccount`: an explicit customer liability backed by cash held by a bank business;
- deposits and withdrawals through `World.pay`, so customer cash and bank cash remain canonical;
- time-based deposit interest, capitalized as a recorded liability change;
- `BankLoan`: an explicit bank obligation with principal, accrued interest, due date and status;
- loan disbursement and repayment through `World.pay`, with the borrower's existing `debt` aggregate updated as a projection of open principal;
- a derived balance-sheet view for cash, deposits, loan principal and accrued loan interest.

## Rejected for this checkpoint

The later BMSim manual includes securities portfolios, swaps, reserve regulation, capital issuance, stock price, tax treatment, detailed customer segments and quarter-specific reports. Those are intentionally not imported yet. They would add scope without improving the canonical money/obligation boundary needed here. The historical source also does not justify a separate bank clock or a separate cash ledger.

## Canonical state boundary

The bank reads and mutates `Business.cash`, customer money/cash, `BankAccount`, `BankLoan`, and causal events. Account balances are financial claims, not physical money or inventory. Loan principal contributes to the existing borrower debt field; accrued interest remains attached to the loan until paid. Failed payments occur before account/loan ledger mutation, so an insolvent customer cannot receive an unbacked financial state.

## Tests and uncertainty

`tests/test_bank_management.py` covers deposit/withdrawal cash backing, minimum balances, interest over elapsed time, loan funding and repayment, insolvency atomicity, and a derived balance sheet. Exact historical formulas, customer-demand curves, competitive pricing and regulatory rules remain uncertain and are not claimed as recovered.
