# Inside Trader (1987) — securities and information kernel

## Evidence inspected

- [MobyGames entry for *Inside Trader: The Authentic Stock Trading Game*](https://www.mobygames.com/game/2439/inside-trader-the-authentic-stock-trading-game/), which describes the 1987 DOS simulation's buy/sell commands, wire-service reports, paid information and SEC consequences.
- [Computer Gaming World Issue 43 review](https://www.cgwmuseum.org/galleries/issues/cgw_43.pdf), which describes ordinary news reports plus informants offering different reliability levels about industries or corporations.
- [My Abandonware description](https://www.myabandonware.com/game/inside-trader-the-authentic-stock-trading-game-b7), used only as a secondary cross-check for the command set and the information/SEC framing; it is not treated as source code.

No original source listing was located. The executable is available through archival/emulation listings, but this pass does not claim behavioral recovery from running it.

## Selected mechanics

- a business can issue a finite tradable security;
- ownership is represented by canonical security holdings;
- a trade moves money and shares together and records the execution price;
- wire news is a causal event and does not automatically rewrite beliefs;
- paid information is a statement through the existing belief/trust system, so the listener can hold a claim without the world truth changing;
- portfolio value is derived from current market prices and holdings.

## Deliberately rejected

SEC investigation/jail gameplay, evidence destruction, exact price generator, charts/UI, insider-detection probabilities, margin trading and a separate securities clock. Regulatory consequences can later consume the same trade/news events if a later donor or primary source justifies them.

## Canonical state translation

`Security`, `SecurityHolding` and `TradeOrder` are world entities. Trades use `World.pay` and mutate exactly one seller and one buyer holding. Information uses `CausalEvent`, `Statement`, `BeliefRevision` and trust; paid information never becomes world truth merely because it was purchased.

## Tests and uncertainty

`tests/test_inside_trader.py` verifies finite issuance, share/money conservation, price history, insolvency atomicity, private information purchase and portfolio valuation. Exact historical market-generation and enforcement formulas remain uncertain.
