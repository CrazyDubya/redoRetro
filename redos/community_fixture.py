"""Six situated fictional residents and two institution records for M4.1."""

from datetime import datetime

from .model import HistoricalProvenance, Institution, InstitutionalRule, ScheduleEntry, SocialTie
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
