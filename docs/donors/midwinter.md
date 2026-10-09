# Midwinter (1989) — traversal archaeology

## Primary evidence examined

- [Midwinter Amiga manual transcription](https://www.lemonamiga.com/doc/midwinter/1081)
- [Midwinter DOS manual PDF](https://dosdays.co.uk/media/games/midwintr/Midwinter%20Manual.pdf)
- [MobyGames overview and manual references](https://www.mobygames.com/game/1479/midwinter/)

The Amiga transcription is the most useful primary manual evidence available in
the current environment. The DOS PDF is a short manual extract rather than a
source listing or executable, so implementation claims are limited to mechanics
described by those materials.

## Mechanics verified

- Skiing is the always-available default movement method while health permits.
- Snow-buggies are faster but are poor on rough or steep terrain and can be
  lost in a crash.
- Mountain terrain can be nearly impassable by ordinary travel; cable cars
  provide a constrained alternative where stations exist.
- Travel mode, terrain and the route chosen therefore change traversal time and
  accessibility.
- The manual describes refueling, repair and supplies at appropriate
  facilities, but those asset and supply systems are translated in Redos from
  the already merged Carrier Command kernel rather than duplicated here.

## Selected for Redos

1. Routes declare terrain and optional allowed movement modes.
2. The canonical world stores a changing `RouteCondition` for a route.
3. Terrain, movement method and current conditions determine effective travel
   time.
4. An inaccessible route is not selected by pathfinding and cannot be entered
   directly.
5. If a route becomes inaccessible while an actor or freight shipment is
   travelling, progress pauses with an auditable delay event and resumes when
   the route reopens.

## Deliberately rejected

- Midwinter's combat, sabotage, recruitment campaign, hostile installations and
  fictional setting.
- First-person control, weapon handling and the game's special two-hour recruit
  turn presentation.
- Snow-specific equipment, because this milestone needs generic 1770 transport
  conditions rather than a second vehicle model.
- A probabilistic crash or loss rule; no such rule is introduced without a
  persistent condition, capacity or recovery state that can explain it.

## Redos translation

| Donor phenomenon | Canonical state read | Canonical state changed |
| --- | --- | --- |
| Rough or mountainous passage | `Route.terrain`, movement mode | Effective route duration |
| Vehicle/method restriction | `Route.allowed_modes` | Path eligibility |
| Storm, ice or other disruption | `RouteCondition` | Accessibility and travel multiplier |
| Disrupted actor journey | `Movement`, actor location | Delay event; elapsed movement remains unchanged while blocked |
| Disrupted freight journey | `Shipment`, `TransportAsset`, route condition | `freight_delayed`; cargo remains aboard the carrier |

## Tests

`tests/test_midwinter.py` demonstrates:

- terrain and method changing effective passage time;
- blocked routes being excluded and direct entry rejected;
- an actor pausing on a route that becomes blocked;
- freight remaining aboard its carrier while a route is blocked, then
  completing after recovery.

## Remaining uncertainty

The original game’s exact terrain-speed tables, vehicle damage thresholds and
weather generation are not recoverable from the inspected material alone. This
checkpoint therefore implements deterministic route conditions and explicit
terrain factors, not a claim of numerical emulation.
