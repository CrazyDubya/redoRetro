# Oregon Trail II (1995) — journey-resource archaeology

## Primary evidence examined

- [Oregon Trail II educational manual record](https://eric.ed.gov/?id=ED385482)
- [Oregon Trail II guidebook excerpts](https://oregon-trail-ii.fandom.com/wiki/Guidebook)
- [Oregon Trail II overview of event and consequence mechanics](https://en.wikipedia.org/wiki/Oregon_Trail_II)

The ERIC record establishes the 1995 CD manual and its planning/journey
sections. The accessible guidebook excerpts provide the clearest operational
evidence for pace, supplies, animals, rugged terrain, river conditions and
waiting for safer crossing conditions. A complete original source listing was
not located; the translation below is therefore behavioral and deliberately
small.

## Mechanics verified

- A journey is managed as a continuing party/wagon state rather than a single
  instantaneous move.
- Pace is a tradeoff: steady travel is preferred, while pushing animals or
  traveling under adverse conditions increases strain and can reduce progress.
- Food, medicine, tools, spare parts and draft animals are journey supplies;
  supplies consume carrying capacity and shortages can stop or damage a trip.
- Rough trails, weather and river conditions can delay travel or make a route
  unsafe; waiting for conditions to improve is a valid outcome.
- Wagon/party condition and repairs persist beyond the immediate incident.

## Selected for Redos

1. Existing `Shipment` is the journey record; no parallel journey universe is
   introduced.
2. A journey may be explicitly interrupted for a causal duration while cargo
   and carrier remain in place.
3. A journey may divert only at a physical route boundary, with every new leg
   validated against the carrier's current location and contracted destination.
4. A journey may be abandoned, failing the contract while preserving cargo
   custody and a causal event chain.
5. Journey pace is recorded (`slow`, `steady`, or `urgent`) and affects the
   effective duration of later legs.
6. Existing Carrier Command named supplies and asset condition provide the
   persistent supply/repair state; resource exhaustion already prevents silent
   continuation and can be recovered through replenishment.

## Deliberately rejected

- The fictional historical campaign, named educational characters and scripted
  encounters.
- Disease, hunting, combat, wagon-party mortality and a large event-choice
  system; these require later canonical health/resource work and are not needed
  to prove transport causality here.
- A hidden random failure table. Disruption must come from route conditions,
  explicit interruption, asset condition or named supply exhaustion.

## Redos translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Pace choice | `Shipment.pace`, route duration | Effective journey duration |
| Waiting for conditions | `RouteCondition`, `Shipment.delay_remaining_hours` | `freight_interrupted` or `freight_delayed`; cargo stays put |
| Alternate trail | Carrier location, route graph, destination | Remaining `Shipment.route_ids`, `freight_diverted` |
| Abandoned journey | Shipment/cargo/contract state | `freight_abandoned`, failed contract, auditable custody |
| Supply/condition failure | `TransportAsset.supplies`, condition | Existing asset-unavailable and recovery events |

## Tests

`tests/test_oregon_trail.py` demonstrates:

- interruption consuming journey time without releasing cargo;
- diversion through two physical legs to the original destination;
- rejection of mid-leg diversion;
- abandonment failing the commercial obligation without deleting or
  teleporting cargo.

## Remaining uncertainty

The exact Oregon Trail II numerical formulas for animal exhaustion, wagon
damage, river crossing risk and supply weight are not established by the
available material. This checkpoint preserves the causal structure and
recoverable state, not a claim of numerical emulation.
