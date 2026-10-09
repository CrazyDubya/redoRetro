# High Seas Trader

## Evidence inspected

- [High Seas Trader manual transcription](https://www.abandonwaredos.com/docawd.php?idg=2184&sf=highseastmanual.txt&sg=High+Seas+Trader&st=manual) documents the port-centered merchant role and ship/crew management.
- [Amiga Reviews review](https://www.amigareviews.leveluphost.com/highseas.htm) describes the selected operational mechanics: buying and selling between ports, maintaining crew conditions and supplies, and setting wages/morale consequences.
- [High Seas Trader overview](https://en.wikipedia.org/wiki/High_Seas_Trader) confirms its port trade, ship, crew and cargo-management focus.

## Selected mechanism

The reusable Redos kernel is operational readiness: a transport assignment requires an existing crew when an asset declares a minimum crew, and voyage supplies are consumed over the same physical freight movement. A shortage fails the voyage while preserving cargo custody on the carrier for recovery.

## Rejected

Naval combat, piracy, cannon loadouts, national relations, rank progression, charts as a separate information game, and the original narrative/ranking layers are excluded. Crew is represented as existing canonical `Actor` identities, not a second population.

## Canonical translation

`TransportAsset.crew_ids` and `minimum_crew` constrain `assign_asset`; `assign_crew` only links existing actors. Existing `supplies` and `supply_burn_per_hour` are consumed by freight and reposition movement. Failures use the canonical `_fail` path, retaining physical cargo and an auditable carrier-clearance state.

## Tests and uncertainty

Tests cover crew-gated dispatch, supply consumption, and failure with cargo preserved. The available manual/review evidence does not establish exact original wage, morale, or crew sickness formulas, so those are not claimed or implemented here.
