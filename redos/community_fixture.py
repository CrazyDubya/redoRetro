"""Six situated fictional residents and two institution records for M4.1."""

from datetime import datetime

from .model import HistoricalProvenance, Institution, InstitutionalRule, ScheduleEntry, SocialTie, SupportDuty
from .streets import build_street_world
from .vertical import SliceState


TRINITY_SOURCE = "https://www.columbia.edu/cu/lweb/digital/collections/cul/texts/ldpd_6856725_001/pages/ldpd_6856725_001_00000025.html"
CIVIC_SOURCE = "https://www.archives.nyc/blog/2019/7/3/the-missing-common-council-records-of-the-revolutionary-war"


def build_community_world(*, seed: int = 0) -> SliceState:
    """Extend the existing street world without installing decision systems.

    Residents, memberships, hours, and the civic desk's location are expressly
    reconstructed test data, not biographies or documented 1770 proceedings.
    """
    state = build_street_world(seed=seed)
    world = state.world
    end = datetime(1771, 1, 1)
    for institution_id, name, kind, place_id, people, source in (
        ("trinity-community", "Trinity congregation records", "congregation", "trinity-churchyard",
         ("citizen-0", "citizen-1", "citizen-2"), TRINITY_SOURCE),
        ("civic-records", "Civic records desk (reconstructed)", "civic", "royal-exchange",
         ("citizen-3", "citizen-4", "citizen-5"), CIVIC_SOURCE),
    ):
        provenance = HistoricalProvenance(
            source, "Institutional context only; fixture people, premises use and hours are reconstructed",
            "New York City, bounded Lower Manhattan fixture", world.now, end,
            "reconstructed", "No claim of a documented membership, official, or 1770 access rule",
        )
        placements = []
        for actor_id in people:
            event = world.move_actor(actor_id, place_id, reason="M4.1 authored initial placement")
            placements.append(event.id)
        world.add(Institution(
            institution_id, name, kind, place_id, (place_id,), people, (people[0],),
            world.now, end, provenance, capacity=1,
            operating_hours=(ScheduleEntry(9, 12, "record keeping", place_id),),
            cash_holder_id=people[0], inventory_holder_id=place_id,
        ))
        for index, (actor_a, actor_b) in enumerate(zip(people, people[1:])):
            world.add(SocialTie(
                f"{institution_id}-tie-{index}", actor_a, actor_b,
                "congregation" if kind == "congregation" else "work",
                world.now, end, provenance, evidence_event_ids=tuple(placements),
            ))
        # A typed, explicitly reconstructed rule record, not an adjudicator.
        world.add(InstitutionalRule(
            f"{institution_id}-records-rule", institution_id, "membership", "documented_evidence",
            world.now, end, provenance,
        ))
    return state


def build_household_world(*, seed: int = 0) -> SliceState:
    """Three reconstructed household arrangements with a genuine support loop."""
    state = build_community_world(seed=seed)
    world = state.world
    world.households["household-a"].arrangement = "wage_dependent"
    world.households["merchant-household"].arrangement = "independent_tradesperson"
    dependent = world.households["household-c"]
    dependent.arrangement = "dependent_extended"
    for member_id in dependent.members:
        actor = world.actors[member_id]
        if actor.employer_id is not None:
            world.businesses[actor.employer_id].employees.remove(actor.id)
        actor.employer_id = None
        actor.occupation = "household dependent"
        actor.schedule = [ScheduleEntry(0, 7, "sleep", dependent.residence_id),
                          ScheduleEntry(7, 8, "eat", dependent.residence_id),
                          ScheduleEntry(8, 24, "leisure at home", dependent.residence_id)]
        if actor.money:
            world.pay(actor.id, "citizen-0", actor.money, reason="authored initial household savings distribution")
    world.pay(dependent.id, "citizen-0", dependent.cash, reason="authored initial household savings distribution")
    world.pay("warehouse-business", "citizen-0", 4000, reason="authored initial savings distribution")
    provenance = HistoricalProvenance(
        "https://www.archives.nyc/almshouse", "Voluntary household support is a reconstructed economic commitment",
        "Bounded Lower Manhattan", world.now, datetime(1771, 1, 1), "reconstructed",
        "Amount, parties and recurrence are test data; no statutory family duty or genealogy is claimed",
    )
    world.add(SupportDuty("household-support", "citizen-0", dependent.id, 48.0, 24.0, world.now,
                          dependent.residence_id, world.now, datetime(1771, 1, 1), provenance))
    return state
