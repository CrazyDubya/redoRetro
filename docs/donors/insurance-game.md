# The Insurance Game — underwriting and claims kernel

## Evidence inspected

- [Fundación MAPFRE catalog record for *The Insurance Game*](https://documentacion.fundacionmapfre.org/documentacion/publico/es/bib/10826.do), Knud Hansen, second edition, 1980. The record identifies it as a business decision game simulating an insurance market and describes simulated companies writing three insurance lines in three regions while allocating resources against market development and competition.
- [Riva Insurance Game description](https://www.iris-insurance-game.com/en/), a surviving insurance-simulation description that confirms the durable business-game lane: insurers make operational decisions in a modeled market and are evaluated through effects on earnings, capital, labor and sales.

The 117-page Hansen work is listed as restricted/no multimedia at the catalog endpoint, and an original executable or source listing was not recovered in this pass. The implementation therefore preserves only mechanics directly supported by the surviving catalog evidence and ordinary insurance obligation semantics.

## Selected mechanics

- insurers write a policy for a line and region;
- the policyholder pays a premium before coverage becomes active;
- a claim must cite an existing world event linked to the policyholder;
- deductible and coverage limit determine the indemnity;
- claims remain filed/approved obligations until the insurer can actually pay;
- active policy and approved-claim exposure are derived from canonical policy and claim records.

## Deliberately rejected

Exact market-demand curves, competitive pricing, field-staff productivity, reinsurance treaties, securities portfolios, solvency regulation and the donor's multi-round business-game interface. Those need stronger primary evidence or a later donor lane. There is no insurer clock, shadow cash ledger or unlinked random claim generator.

## Canonical state translation

`InsurancePolicy` and `InsuranceClaim` live on `World`. Premiums and settlements use `World.pay`; loss causality uses `CausalEvent` IDs; claim status changes only after validation. The insurer's exposure is a derived report, not a second portfolio inventory.

## Tests and uncertainty

`tests/test_insurance_game.py` covers premium-backed issuance, event-linked claims, deductible/limit calculation, insolvent settlement preservation and derived exposure. Exact historical formulas and the original game's internal randomization remain unverified.
