# 1770 community source ledger — M4.1

Examined October 12, 2026. This phase provides records and validation, not
historical institutional decisions. The source categories below distinguish
documented context from reconstructed fixture data. The existing Lower
Manhattan and Brooklyn geography remains the M3 baseline.

| Source examined | Supported claim | Confidence | Geography and temporal/legal applicability | Modeling limit |
| --- | --- | --- | --- | --- |
| [NYC Municipal Archives, Almshouse Ledgers](https://www.archives.nyc/almshouse), institutional history and collection overview | A city almshouse opened on the Commons in 1736 under mayor-appointed overseers; the collection spans 1758–1952. | Supported archival institutional history | New York City; colonial origins relevant to 1770, but later admission examples are not colonial law. | Context for future relief authority only. No 1770 eligibility, benefit or coercive rule has been extracted from a ledger entry. No almshouse placed in the waterfront fixture. |
| [NYC Municipal Archives, Common Council records](https://www.archives.nyc/blog/2019/7/3/the-missing-common-council-records-of-the-revolutionary-war), record history | The colonial Common Council existed before wartime disruption; the page discusses the last colonial mayor and later interruption of records. | Supported archival history | City of New York, colonial municipal context; the article's specific events are in 1776 and later. | Supports a civic institution category, not a 1770 official roster, hearing site, jurisdictional remedy or access restriction. |
| [Columbia University Libraries, *A history of the parish of Trinity Church*, vol. 1, introduction](https://www.columbia.edu/cu/lweb/digital/collections/cul/texts/ldpd_6856725_001/pages/ldpd_6856725_001_00000025.html), digitized page xiii | The parish charter dates to 1697, and the corporation has rector, wardens and vestrymen. | Supported retrospective institutional history | New York parish background; publication is 1898, not an original 1770 membership record. | Establishes institutional context only. Exact membership, gathering hours, aid and admission rules remain uncertain; authorship and retrospective bias must be considered. |
| [New-York Historical / NYU, Colonial Indentures finding aid](https://findingaids.library.nyu.edu/nyhs/ms1988_new_york_indentures/contents/aspace_ref15_4w7/), colonial subseries description | The 1718–1727 volume contains apprentice indentures overseen by civic officials. | Supported catalog description of primary material | Earlier colonial New York. Post-Revolution subseries begins in 1792. | Do not transfer later age/term conventions to 1770. No specific 1770 work agreement or compulsory labor rule implemented in M4.1. |

The institutional Trinity website and the linked New-York Historical
Elizabeth Fortune PDF could not be fetched (HTTP 403). The accessible digitized
history and finding aid suffice for these narrow contextual claims, but are
not substitutes for inspecting original membership, charter or indenture
provisions before implementing historically specific restrictions.

## Fixture translation

`build_community_world(seed=...)` extends the existing street world with two
records: Trinity congregation context at the existing churchyard and a
reconstructed civic records desk at the existing Royal Exchange. The latter
is a deliberately authored reuse of a place, **not a documented hearing
venue**. Six existing fictional residents (`citizen-0` through `citizen-5`)
receive authored initial positions, memberships and four ties. Their real
identities, household, inventory, employment and money remain canonical.

Hours, one-person capacity, official roles, membership-evidence requirements
and all interpersonal affiliations are labeled `reconstructed`. No source is
claimed to prove those particulars. The two typed rule records are data for
later phases; they do not enforce historical access, decide cases, schedule
gatherings or allocate resources yet. Institution cash and storage refer to
existing holders, with no additional balance or inventory.

Every record includes a source URL, scoped claim, geographical relevance,
effective interval, confidence and explicit uncertainty. Registration checks
interval containment. A source supporting an earlier or later period cannot
silently supply a dated rule outside that record's declared applicability.

No actor is assigned historical legal standing from occupation, name,
ethnicity, religion or existing household membership. Wage work,
apprenticeship/indenture and enslavement must be distinguished in later
provenance and labor phases. The current fixture does not claim representative
coverage of those statuses or universal institutional access. Historically
specific standing and restrictions require additional primary evidence.

## Schema and migration evidence

Schema 3 adds only `social_ties`, `institutions` and `institutional_rules` to
`World`. Schema 2 migration adds empty registries in memory and otherwise
preserves every original field; the next successful Save writes schema 3.
The source snapshot is not rewritten by the migration. Invalid references,
duplicate IDs, invalid intervals, unknown rule kinds and inconsistent official
membership are rejected before canonical changes or events.

`tests/fixtures/m3-schema2.sqlite3.gz` comes from frozen M3
`68643756ea1b36f9c8ba1cf87196d6f04b080245`. Its tests compare the old encoder's
complete state digest at load and after 24 ordinary runtime hours. Separate
schema-3 tests compare uninterrupted advancement with a 12+12-hour snapshot
restart including the new records, RNG, events and all preexisting systems.

## M4.2 — household continuity and voluntary support

Household arrangements and support amounts are reconstructed fixture facts,
not a claim to implement a universal 1770 family-support statute. The archival
almshouse overview supplies context for dependency and assistance; it does
not establish the exact private duties modeled here. The three arrangements
are wage-dependent, independent tradesperson and dependent/extended household.
No birth, death, descent or real person's genealogy is generated.

An explicit support duty creates dated receivables. Default adds the owed
amount to the existing debtor's debt once; payments transfer existing cash
and retire the accounted debt. Cancelling support materializes all periods
already due, including the cancellation timestamp, and leaves arrears
attached to the original parties. Pooled resources finance an ordinary
shopper only while co-located at home. Purchase, delivery and consumption
retain a chain back to the support payment, including the actual consumed
lots. Membership and residence transitions retain history; changing residence
leaves possessions physically at the previous home and redirects future
home schedules without relocating a person.

Schema 4 adds support duties, obligations and the household arrangement field.
Both the frozen M3 schema-2 fixture and a real M4.1 schema-3 fixture migrate
without changing the next 24 hours of preexisting simulation state.
