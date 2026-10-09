# Riding Club — mounted travel archaeology

## Evidence examined

The donor identity is not fully resolved. No primary artifact for a standalone
1980s title named only *Riding Club* was located. The strongest surviving
artifact using that name is the archived *Riding Club Championships* material
from Artplant. A separate contemporary title, *Barbie Riding Club*, has an
official award description with overlapping stable, grooming and trail-riding
mechanics. These sources are used as behavioral evidence, not as a claim that
the two products are the same game.

- [Internet Archive record for Riding Club Championships](https://archive.org/details/riding-club)
- [Riding Club Championships FAQ](https://ridingclubchampionships.weebly.com/frequently-asked-questions.html)
- [GameFAQs overview of Riding Club Championships](https://gamefaqs.gamespot.com/pc/197472-riding-club-championships)
- [D.I.C.E. official award description of Barbie Riding Club](https://www.interactive.org/games/video_game_details.asp?idAward=1999&idGame=663)

## Mechanics verified

The available material supports these reusable phenomena:

- A horse is a persistent selected asset with state that survives between
  rides, including training or performance characteristics.
- Stable care includes feeding and grooming; energy/stamina affects whether
  the horse can continue performing.
- Riding is embodied movement along a course. Speed/pace and terrain or jump
  conditions affect progress and completion.
- A rider can choose a destination or course rather than being moved by a
  scenario teleport.

Exact formulas, original source code and the identity of the historical donor
intended by the project selection remain uncertain.

## Selected for Redos

`TransportAsset` now also covers a horse. A horse may carry one rider through
the existing route and movement system, consume named supplies such as
`energy`, and become unavailable when a required supply is exhausted. The
small care layer exposes `feed`, `groom` and `rest` as canonical transitions.
Terrain modifiers are applied by `effective_route_hours`, so a mounted trip
has ordinary elapsed time and a physical arrival event.

## Deliberately rejected

- Competition presentation, rankings, online services and cosmetic equipment.
- Barbie-specific characters and mission content.
- A second animal, map, inventory or clock model.
- Unverified numerical claims about horse stats, racing times or training.

## Canonical state translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Persistent horse | `World.transport_assets` | Asset readiness, supplies and availability |
| Feeding | Existing asset supply capacity | Named `feed` supply plus causal care events |
| Grooming/rest | Asset readiness and assignment | Readiness and availability |
| Mounted travel | `Route`, `RouteCondition`, `Movement`, actor location | Rider and horse progress, supply consumption, arrival |
| Terrain/pace consequence | Route terrain and movement mode `horse` | Effective route duration |

## Tests

`tests/test_riding_club.py` verifies that:

- a rider and horse move together through a canonical route;
- rough terrain changes mounted passage time;
- stamina/energy exhaustion pauses travel without teleporting the rider;
- feeding, grooming and rest restore only the appropriate persistent asset
  state and cannot be performed while the horse is assigned to a journey.

## Remaining uncertainty

This is a compatible Redos kernel, not a source-level port. The surviving
evidence does not establish a single definitive *Riding Club* implementation
or its exact formulas. The donor lane should be revisited if a primary binary
or manual for the originally selected title becomes available.
