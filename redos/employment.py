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
        actor = world.actors[actor_id]
        day_key = world.now.date().isoformat()
        if day_key in actor.paid_work_days:
            continue
        qualifying_hours = actor.work_hours_by_day.get(day_key, 0.0)
        amount = opening.wage_per_day * days * min(1.0, qualifying_hours / max(1, opening.end_hour - opening.start_hour))
        if amount <= 0:
            world.record("wage_missed", f"{actor_id} received no wages because no qualifying work was recorded", actors=[actor_id, employer_id], entities=[opening.id], data={"hours": qualifying_hours})
            continue
        world.pay(employer_id, actor_id, amount, reason="wages paid for recorded work")
        actor.paid_work_days.add(day_key)
        total += amount
    return total


def charge_household_expense(world: World, actor_id: str, amount: float, *, expense: str, payee_id: str | None = None) -> None:
    actor = world.actors[actor_id]
    household = world.households.get(actor.household_id or "")
    payer_id = household.id if household is not None and household.cash >= amount else actor_id
    payer = household if payer_id == household.id else actor
    available = household.cash if household is not None and payer_id == household.id else actor.money
    if payee_id is not None and available >= amount:
        world.pay(payer_id, payee_id, amount, reason=f"household expense: {expense}")
    elif available >= amount:
        if household is not None and payer_id == household.id:
            household.cash -= amount
        else:
            actor.money -= amount
        world.record("expense", f"{payer_id} paid {expense}", actors=[actor_id], entities=[payer_id], data={"amount": amount})
    else:
        if household is not None:
            household.debt += amount
        else:
            actor.debt += amount
        world.record("debt", f"{payer_id} missed {expense}", actors=[actor_id], entities=[payer_id], data={"amount": amount})


def age_one_year(world: World, actor_id: str) -> None:
    actor = world.actors[actor_id]
    actor.age += 1
    actor.developmental_stage = "child" if actor.age < 14 else "youth" if actor.age < 18 else "adult" if actor.age < 60 else "elder"
    actor.life_events.append(f"turned {actor.age}")
    world.record("birthday", f"{actor_id} turned {actor.age}", actors=[actor_id], data={"age": actor.age, "stage": actor.developmental_stage})
