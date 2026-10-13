# Milestone 4 — The Living Community

**Status:** Reviewed specification. M3 closure gate satisfied. Execution of all M4 phases is authorized with iterative self-review, a focused PR per phase, and completed review before merge.
**Baseline:** Frozen M3 `68643756ea1b36f9c8ba1cf87196d6f04b080245`; [M3 closure issue #32](https://github.com/CrazyDubya/redoRetro/issues/32) closed after reviewed PR #34 and passing main CI. See `docs/acceptance/milestone-3.md`.
**Period and geography:** 1770, the existing bounded Lower Manhattan waterfront district and its already-modeled Brooklyn ferry/harbor connections.
**Technical constraints:** Python 3.12-compatible, no Docker, SQLite, no mandatory runtime dependencies, vanilla HTML/CSS/JS, deterministic seed, one canonical `World`.

## 1. Decision: what M4 is

M1 proved a living block; M2 connected the harbor; M3 made a small street district playable. M4 must turn the people and businesses of that district into a **living community with enforceable relationships, labor, households, local institutions, and consequences**. It is not a second economy, a collection of minigames, a new city map, or a Revolutionary War campaign.

The testable change: a player can make and break a social/economic commitment, seek help or redress through an appropriate institution, and see NPCs and institutions react over subsequent days using the same canonical rules. NPCs must make comparable decisions autonomously.

## 2. Non-negotiable invariants

1. **One world:** use existing actors, households, businesses, locations, routes, inventories, money, debts, observations, events, time, and command gateway. No parallel social-simulation database.
2. **Consequences, not labels:** a relationship or institutional decision changes access, labor, goods, obligations, trust, or actor behavior; no cosmetic-only reputation scores.
3. **Situated authority:** an institution can only act through its members, premises, records, resources, eligibility rules, and scheduled proceedings. No omniscient instantaneous adjudication.
4. **Evidence is not truth:** testimony, documents, hearsay, and witness observation have provenance. Institutions may decide incorrectly. No privileged global-event leakage to player or NPC.
5. **Enforceability is bounded:** every obligation has parties, jurisdiction, due date, state transitions, remedies, and a path for failure. No negative inventory, money creation, duplicated wages, or silently fulfilled promises.
6. **Historical care:** distinguish free labor, apprenticeship/indenture, and enslavement without treating coercion as a neutral employment choice. Historical legal standing and institutional access differ by person and jurisdiction; do not invent universal equal access or erase restrictions. Source and uncertainty metadata are required for historically specific rules.
7. **Player agency:** the player is not autonomously redirected by NPC schedules, yet remains subject to the same travel, resources, obligations, access restrictions, and consequences.
8. **No hidden migrations:** version every persisted schema addition; demonstrate loading a frozen M3 snapshot into M4 with an explicit migration or compatible decoder, never `pickle`.
9. **Review gates:** one focused PR per phase, full regression suite, review before merge. Resolve each phase's findings before advancing to the next.

## 3. Bounded M4 scenario

Reuse the existing M3 district, shop, tavern, warehouse, dock, ferry, employers, households and residents. Add **at most four** historically supported institutional sites/roles to the existing places, rather than extending the map: a ward/civic officer or magistrate's hearing venue, a congregation/meeting place, a mutual-aid or poor-relief administrator, and an apprenticeship/trade authority where sources justify it. Roles may share an existing physical site. Seed **three household types** (wage-dependent, independent tradesperson, and dependent/extended household) and at least **two differentiated labor arrangements**. Use existing people wherever possible.

The 1770 New York source ledger must cite primary maps/records or credible scholarship, mark reconstructed details and disputed assumptions, and explain any modeled restriction by jurisdiction and date. Ratzer-derived map geometry remains the M3 baseline, not proof of every institution or address.

## 4. Canonical additions (minimum coherent model)

Add focused dataclasses and `World` registries only as needed:

- **`SocialTie`**: id, two actor IDs, kind (kin, patronage, work, apprenticeship, mutual aid, congregation, etc.), start/end, visibility, evidence references; trust/beliefs continue to use existing actor systems.
- **`WorkAgreement`**: parties, role, place, effective dates, hours/term, compensation or support, eligibility/standing constraints, obligation IDs, status and breach reason. Reuse existing employer, work hours, wages, debt, and payment kernels; never pay wages twice.
- **`Institution`**: id, type, place, member/official actor IDs, jurisdiction, eligibility rules, operating schedule, capacity, cash and physical goods holders, provenance. The institution is not an unlocated global rules engine.
- **`PetitionOrCase`**: claimant, respondent, institution, claim type, supporting observations/statements/records, filing date, hearing date, stage, decision and resulting existing obligations; records distinguish allegation from finding.
- **`ServiceRequest`**: actor/household, institution, need, eligibility evidence, requested resource, status, allocation, decision cause. Food, money and goods transfer through canonical inventory/finance.
- **`HistoricalStanding`** only if needed for access/labor rules: actor, jurisdiction, effective interval, status, provenance, uncertainty. Do not encode human worth or silently derive standing from occupation, name, ethnicity or religion.

Prefer extending existing `Household`, `Actor`, `Business`, `Employment`, and `Obligation` structures over duplicating them. All transitions must create causally linked events. Build a registry of explicit state machines and reject illegal transitions before mutation.

## 5. Milestone phases and deliverables

### M4.0 — M3 closure gate (no M4 code)
- Resolve issue #32; test failed Reload with absent/corrupt snapshot, retry after repair, and failed ledger persistence; full CI green.
- Independently confirm M3 command tape, safe snapshot, 30-day streets, 90-day harbor, and no open P1/P2 correctness findings.
- Record frozen M3 commit SHA and reproducible commands in `docs/acceptance/milestone-3.md`. Do not label M3 closed until these checks pass.

### M4.1 — Provenance and institution/relationship schema
- Commit `docs/history/1770-community-sources.md` with source, claim, confidence, geographic relevance and legal/temporal applicability.
- Add only the minimum `SocialTie`, `Institution`, and typed institutional rule records to the canonical model. Explicit invariants, no duplicate IDs, valid references, temporal validity.
- Add snapshot schema migration from frozen M3 and deterministic round-trip/replay tests.
- Add a tiny fixture with two institutions and six situated people/relationships. **No autonomous institutional decisions or new UI yet.**
- Acceptance: M3 fixture loads and produces identical next 24h behavior; invalid relationships and institutional memberships reject atomically; existing tests green.
- Complete review and resolve findings before M4.2.

### M4.2 — Household obligations and social continuity
- Establish documented household membership changes, support duties, and shared resources. Model consequences for shortage, dependency, and changes of residence through existing economic kernels.
- At least three household arrangements; no fabricated births/deaths or ungrounded genealogies.
- Acceptance: 30-day autonomous run with bounded resource use, preserved provenance and no duplicated cash/goods; one actor's changed support commitment alters another actor's options.

### M4.3 — Labor, apprenticeships and agreements
- Implement `WorkAgreement` and its state machine (offered → active → fulfilled/expired/breached/terminated), with schedule, work evidence, pay or maintenance, dispute path.
- At least one wage agreement and one historically appropriate apprenticeship/term agreement. Treat coercive statuses as distinct constraints, not as a generic optional contract.
- Acceptance: actual work is recorded, wage/support settled once, missed work creates a traceable consequence, termination does not erase arrears, actor cannot be simultaneously booked for incompatible work.

### M4.4 — Petitions, records and local dispute resolution
- A situated official receives a petition, schedules a hearing, considers accessible evidence, decides within bounded authority and creates enforceable obligations or a denial.
- Include contested evidence and an intentionally incorrect decision case; preserve what the institution knew when it acted.
- Acceptance: a claim cannot adjudicate without proper filing, access, time and evidence; judgment does not teleport goods or create money; defaults remain visible.

### M4.5 — Congregation, mutual aid and relief
- Introduce one recurring gathering and one resource-constrained assistance service with capacity, access/eligibility and scheduled decisions. Avoid assuming all people can participate.
- Relief consumes actual stores or cash and has opportunity costs; social encounters propagate only through co-presence or legitimate communication.
- Acceptance: at least two competing requests produce a grounded allocation and unmet demand; decisions differ when resources or eligibility change.

### M4.6 — Player actions and observable consequences
- Extend shared action gateway and mobile client: inspect institution, request work, accept/decline agreement, file petition, offer testimony, request relief, fulfill or contest obligation.
- All actions have preflight reachability/access checks and idempotent command IDs. Journal exposes only witnessed/learned events and received notices; never raw global court or household state.
- Acceptance: browser command tape exercises a multi-day chain; retries and invalid attempts leave world unchanged; player choices affect NPC/institution decisions.

### M4.7 — Autonomous community loop
- Schedule household care, work fulfillment, institutional opening hours, gatherings, case hearings, requests, arrears and follow-up decisions through ordinary world-clock adjudication.
- Decisions must be bounded and deterministic under fixed seed; institutions cannot act when unavailable, and queues/capacity are real.
- Acceptance: without player input, at least one labor agreement, one relief decision and one petition progress through real state transitions over 30 days; no scripted forced outcomes.

### M4.8 — Integrated 90-day acceptance and freeze
- Three fixed seeds for 30 days and one for 90 days, plus two same-seed player-intervention counterfactuals.
- Produce machine-readable audit: obligations due/paid/defaulted, labor hours and wages, household resources, institutional queue/capacity, petitions filed/heard/decided, witness provenance, market/finance/inventory conservation, and unresolved cases.
- Show a playable journey: work or support obligation → missed/fulfilled duty → petition or aid request → hearing/allocation → lasting consequence, with physically situated travel.
- Replay 45+45 days with a save/reload at day 45 and compare against uninterrupted 90 days including RNG, ledgers, queues, events and obligations.
- Benchmark relative to frozen M3 at equal simulated days/actors, and explain any >2x per-day slowdown; no silent performance regression.
- Full M1/M2/M3 regression suite plus M4 tests, Ruff, Python 3.12 CI; no P1/P2 findings; independent review and explicit freeze SHA.

## 6. Rejected scope

No whole-Manhattan expansion, new map engine, national politics, election or Revolution campaign, military combat, colony-wide diplomacy, full ecclesiastical simulation, generic procedural courtroom drama, omniscient gossip, birth-to-death generational simulation, multiplayer, AI-generated authoritative legal decisions, or new donor-game subsystem unless separately justified and approved. No new external service, database or frontend framework.

## 7. Agent instructions and gate discipline

1. **Do not start M4 code until M3 issue #32 is closed and the M3 acceptance document records a reviewed freeze SHA.**
2. Implement one phase at a time on a focused branch/PR. Show schema, migrations, source ledger, invariants, and test results. Complete review and resolve findings before merging and proceeding.
3. Preserve old tests and public APIs where practical; avoid compatibility shims for features that never shipped, but preserve M3 saved-game data as required.
4. Never mark a phase complete from documentation alone; point to executed tests, commit SHA, and review outcome.
5. Any material historical uncertainty is documented as a bounded assumption rather than asserted as fact.

**Definition of done for M4:** an autonomous and player-influenced community where household obligations, labor, institutional access, disputes and relief have physically and financially grounded consequences in the same 1770 World, with auditable causal provenance and deterministic persistence.
