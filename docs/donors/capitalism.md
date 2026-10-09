# Capitalism (1995) — capital allocation archaeology

## Evidence examined

- [Capitalism series overview](https://en.wikipedia.org/wiki/Capitalism_%28video_game%29),
  used as a release and feature cross-check.
- [Capitalism Lab beginner guide](https://www.capitalismlab.com/beginners-guide-gameplay-basics/),
  an official successor-family source describing supply, inventory, demand,
  competitor sales, debt and share financing.
- [Capitalism Lab educational guide](https://www.capitalismlab.com/cap_lab_files/education/CapLab_Educational_Use_Guide.pdf),
  used for the documented business-simulation and supply-chain framing.
- [Capitalism II educational material](https://www.enlight.com/capitalism2/resources/Sim_VG_Bus_School_Teaching_Tool.pdf),
  used as a related official-era source for vertically connected production and
  retail.

The original 1995 source listing was not located. Successor documentation is
useful for the persistent business phenomena but does not establish the
original numerical formulas.

## Mechanics verified

- Firms coordinate production, supply, inventory and retail across a physical
  supply chain.
- Capital is scarce: firms choose between operating cash, debt and investment
  in productive or research capability.
- Productive capacity and input availability constrain output; unsold stock and
  weak demand remain economic consequences rather than disappearing into a
  central market ledger.
- Competition, pricing and advertising are business decisions already covered
  by Redos' Market/Cartels kernels.

## Selected for Redos

Redos already had contracts, competition, research accounting and physical
input/output recipes. This checkpoint adds only the missing capital-to-capacity
link:

- `Business.capital` records the capitalized outlay.
- `Business.production_capacity` records recipe-specific capacity.
- `invest_in_capacity` debits business cash and records the investment.
- Runtime production uses the capacity ceiling but still clamps batches to
  actual physical inputs and inventory targets.

## Deliberately rejected

- A second firm, supply-chain, market or accounting universe.
- Stock-market shares, acquisitions, real-estate layout and corporate UI.
- Exact successor-game formulas, product-quality ratings and seasonal demand
  until primary evidence and a concrete Redos need justify them.

## Canonical state translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Capital budget | `Business.cash`, `Business.debt` | Cash, capital and investment event |
| Productive capacity | `Business.production_capacity`, `Recipe` | Maximum recipe batch |
| Input constraint | Physical `InventoryLot` quantities | Consumed inputs and traceable output |
| Supply-chain consequence | Existing contracts, markets and production events | Downstream inventory and prices |

## Tests

`tests/test_capitalism.py` verifies that capacity investment is paid from a
business account, increases one recipe's available batch size, never creates
outputs without physical inputs, and leaves provenance intact.

## Remaining uncertainty

The exact Capitalism (1995) capacity, cost-accounting and R&D formulas remain
unverified. This is a compatible kernel extracted from documented business
phenomena, not a claim of source-level or numerical emulation.
