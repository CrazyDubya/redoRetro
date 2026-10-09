# Derby Stallion — horse management and racing archaeology

## Evidence examined

- [Derby Stallion series overview](https://en.wikipedia.org/wiki/Derby_Stallion),
  used only as a release/genre cross-check.
- [GameFAQs guide to the original Best Keiba / Derby Stallion](https://gamefaqs.gamespot.com/nes/570626-best-keiba-derby-stallion/faqs/73078),
  including horse records, breeding, training, race entry, classes and purse
  outcomes.
- [Japanese first-game mechanics notes](https://www2u.biglobe.ne.jp/kakeru/old/fc/ds1_memo.htm),
  which expose the training menu, surface/intensity effects, fatigue and
  injury risks.
- [Derby Stallion III manual scan](https://www.gamingalexandria.com/highquality/sfc/Derby%20Stallion%20III/Derby%20Stallion%20III%20-%20Manual.pdf),
  located as supporting manual evidence but not machine-readable enough here
  to establish exact formulas.

An original source listing was not located. The implementation therefore uses
the documented behavioral mechanisms and explicitly does not claim numerical
emulation.

## Mechanics verified

- A horse record persists across training and races, including age, pedigree or
  owner-facing record, race count and earnings.
- Training has a surface and intensity choice. The surviving notes associate
  grass work with speed, dirt work with stamina, and harder work with greater
  weight/fatigue and injury risk.
- Races are scheduled against age/class/distance and award prize money. A race
  changes the horse's record and causes fatigue.
- Recovery and retirement are meaningful stable decisions; breeding is a
  multi-period process rather than an instant stat rewrite.

## Selected for Redos

This checkpoint adds only the smallest kernel that matters to the shared
world:

- `HorseState` is canonical state attached to an existing horse
  `TransportAsset`.
- `train_horse` updates speed or stamina, fatigue, readiness and explicit
  injury state, with the random draw recorded in the causal event.
- `race_horses` requires co-location and an unassigned horse, ranks entrants
  deterministically from persistent abilities plus the seeded world RNG, and
  transfers an explicit purse through the existing money gateway.
- Riding, cargo custody, routes and elapsed time remain owned by the existing
  movement/transport system.

## Deliberately rejected

- Full bloodline and breeding formulae, because the available sources do not
  establish the exact calculations and the milestone does not need a second
  population system yet.
- Race calendars, jockey rosters, class promotion and betting UI.
- Save/reset exploits, presentation, and an independent race clock or stable
  inventory.

## Canonical state translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Horse record | `World.horses`, `TransportAsset.owner_id` | Persistent ability, age, record and earnings |
| Training | Horse state, asset readiness, seeded RNG | Ability, fatigue, injury and causal events |
| Race entry | Horse location, assignment, age and readiness | Race result, fatigue, asset readiness |
| Prize money | Existing payer/payee gateway | Owner money and payment event |

## Tests

`tests/test_derby_stallion.py` verifies:

- training changes the selected ability and records fatigue/risk;
- an injured or assigned horse cannot be used as a race entry or transport
  assignment;
- co-located horses race without teleporting and the purse is paid to the
  winner's owner;
- race fatigue persists and recovery is handled through existing horse care.

## Remaining uncertainty

The original Derby Stallion series changed across platforms and releases. The
available evidence is strongest for the first Famicom/NES-era mechanics, while
the selected project donor is named at series level. This is a transparent,
compatible extraction of the stable-management lane, not a claim that every
later Derby Stallion feature has been recovered.
