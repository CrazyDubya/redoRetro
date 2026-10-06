"""Employment and household cash-flow mechanics."""

from __future__ import annotations

from .model import Actor, Business, JobOpening, ScheduleEntry, World


def hire(world: World, actor_id: str, opening_id: str) -> None:
    actor = world.actors[actor_id]
    opening = world.job_openings[opening_id]
    employer = world.businesses[opening.employer_id]
    if opening.qualification and actor.skills.get(opening.qualification, 0.0) <= 0:
        raise ValueError(f"{actor_id} does not qualify for {opening.occupation}")
    if actor.employer_id and actor.id in world.businesses.get(actor.employer_id, Business("", "", "", "")).employees:
        raise ValueError("actor already employed")
    actor.employer_id = employer.id
    actor.occupation = opening.occupation
    employer.employees.append(actor.id)
    actor.schedule.append(ScheduleEntry(opening.start_hour, opening.end_hour, f"work as {opening.occupation}", employer.location_id, priority=10, interruptible=False))
    world.record("hired", f"{actor_id} hired by {employer.id}", actors=[actor_id], entities=[opening_id, employer.id])


def pay_wages(world: World, employer_id: str, *, days: int = 1) -> float:
    employer = world.businesses[employer_id]
    opening_by_actor = {
        actor.id: next((opening for opening in world.job_openings.values() if opening.employer_id == employer_id and opening.occupation == actor.occupation), None)
        for actor in (world.actors[actor_id] for actor_id in employer.employees)
    }
    total = 0.0
    for actor_id, opening in opening_by_actor.items():
        if opening is None:
            continue
        amount = opening.wage_per_day * days
        world.pay(employer_id, actor_id, amount, reason="wages paid")
        total += amount
    return total


def charge_household_expense(world: World, actor_id: str, amount: float, *, expense: str, payee_id: str | None = None) -> None:
    actor = world.actors[actor_id]
    household = world.households.get(actor.household_id or "")
    if household is not None:
        household.debt += amount if actor.money < amount else 0.0
    if payee_id is not None and actor.money >= amount:
        world.pay(actor_id, payee_id, amount, reason=f"household expense: {expense}")
    elif actor.money >= amount:
        actor.money -= amount
        world.record("expense", f"{actor_id} paid {expense}", actors=[actor_id], data={"amount": amount})
    else:
        actor.debt += amount
        world.record("debt", f"{actor_id} missed {expense}", actors=[actor_id], data={"amount": amount})


def age_one_year(world: World, actor_id: str) -> None:
    actor = world.actors[actor_id]
    actor.age += 1
    world.record("birthday", f"{actor_id} turned {actor.age}", actors=[actor_id], data={"age": actor.age})
