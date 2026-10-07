# Donor archaeology audit: Mystery Mansion through M.U.L.E. (donors 4–15)

This is an implementation audit, not a claim that Redos ports these games.
The Redos translation column records the smallest useful mechanism and the
canonical state it reads and mutates. “Rejected” is important: it prevents a
summary of a donor from silently becoming a feature specification.

## 4. Mystery Mansion

- **Phenomenon/lane:** autonomous people continue moving through rooms while
  the player investigates; room occupancy and time make incidents observable.
- **Actual mechanism:** the IF Archive preserves the original FORTRAN and the
  line-oriented C/F2C port. The surviving game is a room-and-time text
  mystery with characters, a murderer/victim situation, and interrogation.
- **Evidence inspected:** [IF Archive source index](https://ukrestrict.ifarchive.org/indexes/if-archive/games/source/),
  [IFDB archive contents](https://ifdb.org/viewgame?id=mcxu2tvxxhpvtyxp), and
  [James Garnett’s C port](https://github.com/garnett1966/Mystery-Mansion).
- **Preserve:** a world clock, occupancy, character movement, event records,
  and answers limited by a character’s observations.
- **Rejected:** murder logic, parser/UI, and a special omniscient detective
  state.
- **Redos translation:** `World.now`, `Actor.location_id`, schedules, movement
  events, `Observation`, `Statement`, and `tavern_report`.
- **Canonical read/mutate:** reads routes, schedules, and current positions;
  mutates actor movement and causal observation/statement records.
- **Remaining uncertainty:** exact original character scheduling and how much
  of the C port is behavior-preserving rather than a maintenance rewrite.

## 5. The Sumerian Game

- **Phenomenon/lane:** multi-period population, food, labor, development, and
  disaster consequences at aggregate resolution.
- **Actual mechanism:** the original source is not known to survive. The
  recovered classroom material describes an annual economic decision loop with
  population, grain allocation, land/crops, trade/colonization, and shocks;
  it is not an individual-person simulation.
- **Evidence inspected:** [ERIC’s preserved historical account and
  analysis](https://files.eric.ed.gov/fulltext/ED014227.pdf) and the
  [The Strong collection record](https://www.museumofplay.org/games/the-sumerian-game/).
- **Preserve:** a resolution hierarchy and causal aggregate period update.
- **Rejected:** inventing a surviving source listing or expanding the donor
  into a full ancient-city rule set.
- **Redos translation:** `AggregatePopulation`, `tick_aggregate`, and the
  reconciliation report against resolved local actors.
- **Canonical read/mutate:** reads food, labor, development, and local
  resolution counts; mutates aggregate population, food, development, and
  disaster events.
- **Remaining uncertainty:** the exact original arithmetic and which later
  classroom revisions correspond to which release.

## 6. Ultima VII

- **Phenomenon/lane:** persistent NPC schedules, spatial object/container
  relationships, and usecode-driven interactions.
- **Actual mechanism:** Exult exposes NPC schedule data and schedule editing;
  its source has actors with schedule type/location, containers, timers,
  path-walking, and usecode properties. A schedule is a target/action
  instruction, not a teleport guarantee.
- **Evidence inspected:** [Exult Studio schedule documentation](https://exult.sourceforge.io/studio.html),
  [Exult actor source](https://sources.debian.org/src/exult/1.2-16.2/actors.h),
  [Exult source repository](https://github.com/exult/exult), and
  [schedule/usecode technical notes](https://bootstrike.com/Ultima/Online/u7tech.php).
- **Preserve:** schedule intention, path traversal, interruption, and physical
  object/container ownership.
- **Rejected:** Exult’s map/tile format, usecode VM, plot scripting, and a
  separate party/player object model.
- **Redos translation:** `ScheduleEntry`, `Actor.intention`, canonical
  `Movement`, inventory lots, and runtime task interruption.
- **Canonical read/mutate:** reads schedule and route state; mutates actor
  position, attendance, inventory, and causal events.
- **Remaining uncertainty:** some Exult schedules are reconstructed from
  original data and are not evidence that every original schedule behaved
  identically.

## 7. Grand Theft Auto (1997)

- **Phenomenon/lane:** embodied top-down movement through continuous urban
  space, streets, collision/navigation affordances, and pedestrians sharing
  the map.
- **Actual mechanism:** the original game’s public archaeology describes a
  grid/city map with roads, pavements, buildings, and pedestrians; OpenGTA is
  an independent engine reimplementation. The map documentation distinguishes
  road/pavement traversal from non-walkable terrain rather than treating the
  city as a list of abstract destinations.
- **Evidence inspected:** [OpenGTA source](https://github.com/madebr/OpenGTA),
  [GTA1 CityScape format notes](https://misc.daniel-marschall.de/spiele/gta1/cds.pdf),
  [DMA design document archive](https://www.gamedevs.org/uploads/grand-theft-auto.pdf),
  and the [GTA map-editor notes](https://github.com/VBGAMER45/gta1-mapeditor).
- **Preserve:** continuous position, route traversal, shared player/NPC
  movement authority, and eventual building-entry targets.
- **Rejected:** crime, vehicles, weapons, mission scoring, and streaming the
  whole city.
- **Redos translation:** `Place` coordinates, `Route`, `Movement`,
  `simulation.walk`, and `World.advance_movements`.
- **Canonical read/mutate:** reads route geometry and actor position; mutates
  only canonical actor movement and arrival events.
- **Remaining uncertainty:** OpenGTA and format documents are archaeological
  assistance, not the original 1997 engine source.

## 8. Trust & Betrayal: The Legacy of Siboot

- **Phenomenon/lane:** trust, statements, persuasion, and different agents
  maintaining different social beliefs.
- **Actual mechanism:** Crawford’s design centers social language and trust;
  the original source was publicly released in 2013, while the surviving public
  design material is more accessible than a complete, buildable historical
  toolchain.
- **Evidence inspected:** [Crawford’s Siboot design diary](https://www.erasmatazz.com/library/design-diaries/design-diary-siboot/january-2013/the-beginning.html),
  [source-release record](https://en.wikipedia.org/wiki/Trust_%26_Betrayal%3A_The_Legacy_of_Siboot),
  and [game documentation](https://www.mobygames.com/game/24452/trust-and-betrayal-the-legacy-of-siboot/).
- **Preserve:** truth, observation, recollection, statement, belief, and trust
  as separate edges/state.
- **Rejected:** Crawford’s inverse word parser, emotional UI, and a global
  persuasion score standing in for information provenance.
- **Redos translation:** `Observation`, `recollect`, `Statement`, `tell`,
  `propagate_information`, `Actor.beliefs`, and `Actor.trust`.
- **Canonical read/mutate:** reads physical co-presence and prior statements;
  mutates only listener belief/trust and causal statement records.
- **Remaining uncertainty:** exact source-available implementation details were
  not required for this milestone and are not asserted here.

## 9. Alter Ego

- **Phenomenon/lane:** life-course state and long-term consequences of events.
- **Actual mechanism:** a large indexed matrix of age/stage/category events
  drives the experience; it is a structured life-course table, not a general
  autonomous society model.
- **Evidence inspected:** [official credits and product history](https://www.playalterego.com/credits.html),
  [archived manual](https://mirrors.apple2.org.za/ftp.apple.asimov.net/documentation/applications/misc/Alter%20Ego%20manual.pdf),
  and [development discussion](https://www.sockmonsters.com/TheMakingOfAlterEgo.html).
- **Preserve:** age, developmental stage, durable life events, and relationship
  consequences.
- **Rejected:** importing the questionnaire tree and making every person a
  scripted protagonist.
- **Redos translation:** `Actor.age`, `developmental_stage`, `life_events`,
  relationships, and `age_one_year`.
- **Canonical read/mutate:** reads actor age and relationships; mutates actor
  life-course state and causal birthday/event records.
- **Remaining uncertainty:** the original event matrix is proprietary/content
  data and is intentionally not copied.

## 10. Little Computer People

- **Phenomenon/lane:** an ordinary household routine driven by needs, fixed
  appointments, scripted sequences, and bounded random idle behavior.
- **Actual mechanism:** reverse-engineered memory-map work identifies a
  priority arbiter, food/water needs, fixed appointments, scripted action
  buffers, and a weekday-dependent activity pool with anti-repetition.
- **Evidence inspected:** [memory-map schedule analysis](https://gavingraham.com/little-computer-people-memory-map/),
  [arbiter/scheduler analysis](https://gavingraham.com/little-computer-people-inside-the-machine/),
  and the [historical description](https://en.wikipedia.org/wiki/Little_Computer_People).
- **Preserve:** needs can pre-empt routine; eating, sleeping, leisure, and room
  use are ordinary state transitions.
- **Rejected:** a single resident, pet/computer presentation, and a fixed
  house-specific action vocabulary.
- **Redos translation:** food need, task interruption, `eat` schedules,
  household inventory, and home return through movement.
- **Canonical read/mutate:** reads household stock, schedules, and physical
  location; mutates lots, health, tasks, and events.
- **Remaining uncertainty:** reverse-engineered behavior is not the original
  publisher’s source listing.

## 11. Jones in the Fast Lane

- **Phenomenon/lane:** jobs consume time, depend on qualifications, pay wages,
  and interact with rent/education/expenses.
- **Actual mechanism:** the game’s job model uses experience, dependability,
  education, work sessions, wage progression, rent, and debt consequences; its
  board-like locations abstract travel but work is still a time-consuming
  decision.
- **Evidence inspected:** [Jones job mechanics reference](https://jonesinthefastlane.fandom.com/wiki/Jobs),
  [game overview](https://en.wikipedia.org/wiki/Jones_in_the_Fast_Lane), and the
  archived manual used by the project’s initial research notes.
- **Preserve:** job opening, employer, qualification, work hours, attendance,
  wage, rent/expense, debt, and job interruption.
- **Rejected:** happiness/status win conditions and the board-game ring as the
  canonical geography.
- **Redos translation:** `JobOpening`, work attendance records, `pay_wages`,
  `charge_household_expense`, schedules, and interruption events.
- **Canonical read/mutate:** reads actual actor location and work hours;
  mutates actor/business/household cash and causal payroll events.
- **Remaining uncertainty:** exact wage tables and promotion rules are not yet
  needed for the small slice.

## 12. Market

- **Phenomenon/lane:** competing firms choose production, price, advertising,
  and inventory under demand and disruptions.
- **Actual mechanism:** the preserved educational description uses periodic
  firm decisions and reports units, stock, cash, sales, market share, and
  shocks; it is not merely a buy/sell price table.
- **Evidence inspected:** [ERIC business-management simulation record](https://files.eric.ed.gov/fulltext/ED089740.pdf)
  and the project’s extracted implementation notes.
- **Preserve:** firms compete against observable inventory, offers, demand,
  and market share; disruptions and shortages remain possible.
- **Rejected:** a second market universe or abstract stock independent of
  physical lots.
- **Redos translation:** `Business`, `Market`, `market_balance_errors`,
  `refresh_market`, `compete`, and physical market transactions.
- **Canonical read/mutate:** reads physical place stock and firm inventory;
  mutates derived balances/price history, cash, lots, and events.
- **Remaining uncertainty:** the exact period length and random shock schedule
  in the classroom release are not treated as Redos requirements.

## 13. Cartels & Cutthroats

- **Phenomenon/lane:** firm-level production planning, labor/capacity,
  warehousing, financing, marketing, and competition.
- **Actual mechanism:** educational descriptions and reviews describe setting
  production, purchasing inputs, financing, marketing, and competitive outcomes
  with business-level financial consequences.
- **Evidence inspected:** [ERIC source PDF](https://files.eric.ed.gov/fulltext/ED278852.pdf),
  [ERIC instructional analysis](https://files.eric.ed.gov/fulltext/ED234772.pdf),
  and the [historical implementation review](https://datadrivengamer.blogspot.com/2021/04/game-250-cartels-cutthroat.html).
- **Preserve:** financing, debt, research, inventory targets, production
  planning, and competitive pressure where they add to Market.
- **Rejected:** duplicate market pricing and cartel-specific scenario rules.
- **Redos translation:** `borrow`, `repay`, `invest_in_research`, `Business.debt`,
  `inventory_targets`, and endogenous recipe adjudication.
- **Canonical read/mutate:** reads business cash, debt, employees, stock, and
  demand; mutates those same entities and causal finance/production events.
- **Remaining uncertainty:** source/manual fidelity is weaker than for Exult;
  no claim is made that every review detail is original game code.

## 14. INTOP / INTOPIA

- **Phenomenon/lane:** autonomous businesses transact with other businesses;
  intercompany sales, services, finance, and multiple markets are first-class.
- **Actual mechanism:** the business-game literature describes weekly decision
  sessions and explicit intra/intercompany transactions. INTOPIA is a
  management simulation in which companies may buy from and sell to one
  another.
- **Evidence inspected:** [INTOP conference paper](https://files.eric.ed.gov/fulltext/ED066875.pdf),
  [business-simulation literature on INTOPIA](https://citeseerx.ist.psu.edu/document?doi=9bbded1dc218fabd563af14c2d27183d6a4c66e4&repid=rep1&type=pdf),
  and the [INTOPIA overview](https://en.wikipedia.org/wiki/Intopia).
- **Preserve:** contracts as obligations between businesses, with physical
  allocation, dispatch, transit, delivery, payment, and failure.
- **Rejected:** a separate ledger-only intercompany universe and instant
  seller-to-buyer transfers.
- **Redos translation:** `Contract`, `Shipment`, `allocate_contract`,
  `dispatch_contract`, `advance_shipments`, absolute `due_at`, and settlement.
- **Canonical read/mutate:** reads physical lots, routes, business cash, and
  contract endpoints; mutates shipment holders, lots, cash, statuses, and
  causal events.
- **Remaining uncertainty:** exact currencies and weekly decision UI are
  intentionally deferred.

## 15. M.U.L.E.

- **Phenomenon/lane:** production scarcity, supply/demand price movement,
  auctions, withholding, and strategic buyer/seller interaction.
- **Actual mechanism:** the manual describes production affected by base
  production, energy, learning/adjacency bonuses, and store supply; prices use
  supply/demand and recent auction prices, with shortages and strategic
  withholding.
- **Evidence inspected:** [M.U.L.E. manual economics section](https://www.niksula.hut.fi/~eesko/kamaa/mulemanual/Muleman.htm)
  and [manual overview](https://www.scribd.com/document/31814106/MULE-Manual).
- **Preserve:** scarcity pressure, auctions, bid settlement, and recent-price
  discovery over actual lots.
- **Rejected:** land-claiming, M.U.L.E. unit production, and the full four-player
  turn structure.
- **Redos translation:** `auction`, `mule_bid`, physical inventory, demand
  backlog, market price history, and competition.
- **Canonical read/mutate:** reads physical stock, bids, demand, and cash;
  mutates ownership, cash, price history, and causal auction events.
- **Remaining uncertainty:** the first integrated slice has only a small price
  response model; it does not yet reproduce all M.U.L.E. learning/adjacency
  production effects.

## Audit conclusion

Donors 5–15 have been re-audited as evidence for narrow mechanisms, not as
claims that the full games are integrated. The corrective pass changes the
Redos implementation where the archaeology matters: movement is physical,
contracts are obligations with cargo, work is attendance-based, household
needs trigger acquisition, and information propagates through bounded causal
exchanges.
