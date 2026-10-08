"""Autonomous time progression and aggregate-resolution helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from .living import activity_for_hour
from .model import Actor, AggregatePopulation, Route, World


def route_path(world: World, origin_id: str, destination_id: str) -> list[Route]:
    if origin_id == destination_id:
        return []
    queue: deque[tuple[str, list[Route]]] = deque([(origin_id, [])])
    visited = {origin_id}
    while queue:
        place_id, path = queue.popleft()
        for route in world.routes.values():
            if route.origin_id != place_id or route.destination_id in visited:
                continue
            next_path = [*path, route]
            if route.destination_id == destination_id:
                return next_path
            visited.add(route.destination_id)
            queue.append((route.destination_id, next_path))
    return []


def walk(world: World, actor_id: str, destination_id: str):
    """Start embodied movement for either a player or an autonomous actor."""
    actor = world.actors[actor_id]
    path = route_path(world, actor.location_id, destination_id)
    if not path:
        raise ValueError(f"no walkable path from {actor.location_id} to {destination_id}")
    actor.journey_destination_id = destination_id
    movement = world.begin_movement(actor_id, path[0].id)
    world.record(
        "travel_started",
        f"{actor_id} started travelling toward {destination_id}",
        actors=[actor_id],
        entities=[path[0].id, path[0].destination_id],
        data={"travel_hours": movement.duration_hours, "distance": path[0].distance},
    )
    return movement


def _start_next_leg(world: World, actor: Actor, target_id: str) -> bool:
    path = route_path(world, actor.location_id, target_id)
    if not path:
        return False
    route = path[0]
    movement = world.begin_movement(actor.id, route.id)
    world.record(
        "travel_started",
        f"{actor.id} started travelling toward {target_id}",
        actors=[actor.id],
        entities=[route.id, route.destination_id],
        data={"travel_hours": movement.duration_hours, "distance": route.distance},
    )
    return True


def _tick_step(world: World, hours: float) -> None:
    if hours < 0:
        raise ValueError("hours cannot be negative")
    if hours == 0:
        return
    world.advance_hours(hours)
    world.advance_movements(hours)
    for actor in world.actors.values():
        if actor.traveling_to is not None:
            continue
        if actor.journey_destination_id is not None:
            if actor.location_id == actor.journey_destination_id:
                actor.journey_destination_id = None
            else:
                if not _start_next_leg(world, actor, actor.journey_destination_id):
                    world.record(
                        "travel_failed",
                        f"{actor.id} could not continue toward {actor.journey_destination_id}",
                        actors=[actor.id],
                        entities=[actor.journey_destination_id],
                    )
                    actor.journey_destination_id = None
                continue
        if actor.active_task and actor.task_target_location_id:
            actor.current_activity = actor.intention = actor.active_task
            if actor.location_id != actor.task_target_location_id:
                _start_next_leg(world, actor, actor.task_target_location_id)
            else:
                world.record("activity", f"{actor.id} continued task {actor.active_task}", actors=[actor.id], entities=[actor.task_target_location_id])
            continue
        if actor.schedule_override_until is not None and world.now < actor.schedule_override_until:
            activity = actor.temporary_activity
            target = actor.temporary_target_location_id
            if activity is None or target is None:
                continue
            actor.current_activity = activity
            actor.intention = activity
            if actor.location_id != target:
                _start_next_leg(world, actor, target)
            else:
                world.record("activity", f"{actor.id} continued interrupted {activity}", actors=[actor.id], entities=[target])
            continue
        actor.schedule_override_until = None
        actor.temporary_activity = None
        actor.temporary_target_location_id = None
        entry = activity_for_hour(world, actor.id)
        if entry is None:
            actor.current_activity = None
            actor.intention = None
            continue
        actor.current_activity = entry.activity
        actor.intention = entry.activity
        if actor.location_id != entry.target_location_id:
            _start_next_leg(world, actor, entry.target_location_id)
        else:
            world.record("activity", f"{actor.id} began {entry.activity}", actors=[actor.id], entities=[entry.target_location_id])
            if entry.activity.startswith("work") or entry.activity.startswith("inspect"):
                employer_id = actor.employer_id
                if employer_id and employer_id in world.businesses and (world.businesses[employer_id].location_id == actor.location_id or entry.activity.startswith("inspect")):
                    day_key = world.now.date().isoformat()
                    actor.work_hours_by_day[day_key] = actor.work_hours_by_day.get(day_key, 0.0) + 1.0
                    world.record("work", f"{actor.id} worked one qualifying hour", actors=[actor.id, employer_id], entities=[entry.target_location_id], data={"day": day_key, "hours": 1})


def tick(world: World, hours: float = 1) -> None:
    """Advance the living world with tick-size-independent movement.

    Large caller ticks are decomposed at the same adjudication boundary used
    by the normal hourly runtime.  This lets a multi-leg journey consume all
    available time, rather than waiting until the next external tick to start
    its next route leg.
    """
    if hours < 0:
        raise ValueError("hours cannot be negative")
    remaining = float(hours)
    while remaining > 1e-9:
        step = min(1.0, remaining)
        _tick_step(world, step)
        remaining -= step


def interrupt(
    world: World,
    actor_id: str,
    activity: str,
    target_location_id: str,
    *,
    hours: int,
    reason: str,
    causes: Iterable[str] = (),
) -> None:
    if hours <= 0:
        raise ValueError("an interruption must last at least one hour")
    actor = world.actors[actor_id]
    actor.schedule_override_until = world.now + timedelta(hours=hours)
    actor.temporary_activity = activity
    actor.temporary_target_location_id = target_location_id
    actor.intention = activity
    world.record(
        "schedule_interrupted",
        f"{actor_id} interrupted schedule for {activity}",
        actors=[actor_id],
        entities=[target_location_id],
        causes=causes,
        data={"reason": reason, "hours": hours},
    )


def interrupt_for_family_problem(
    world: World,
    actor_id: str,
    activity: str,
    target_location_id: str,
    *,
    hours: int,
    description: str,
) -> str:
    """Create a household problem that interrupts work through canonical state."""
    actor = world.actors[actor_id]
    household_id = actor.household_id
    if household_id is None:
        raise ValueError(f"{actor_id} does not belong to a household")
    problem = world.record(
        "family_problem",
        description,
        actors=[actor_id],
        entities=[household_id],
    )
    interrupt(
        world,
        actor_id,
        activity,
        target_location_id,
        hours=hours,
        reason=description,
        causes=[problem.id],
    )
    return problem.id


def run_days(world: World, days: int) -> None:
    for _ in range(days):
        for _hour in range(24):
            tick(world, 1)


def ask_about(world: World, actor_id: str, event_id: str) -> str:
    """Return only what the actor's own observation/memory can support."""
    actor = world.actors[actor_id]
    observation_id = actor.knowledge.get(event_id)
    if not observation_id or observation_id not in world.observations:
        return "I do not know anything about that."
    observation = world.observations[observation_id]
    return observation.recollection or observation.content


def add_aggregate_population(world: World, population: AggregatePopulation) -> None:
    world.add(population)


def tick_aggregate(world: World, population_id: str, *, days: int = 1, food_per_person: float = 1.0) -> None:
    """Advance an offscreen population using cheap aggregate causality."""
    population = world.aggregate_populations[population_id]
    if days < 0:
        raise ValueError("days cannot be negative")
    for _ in range(days):
        produced = population.labor * (0.25 + population.development * 0.02)
        population.food += produced
        need = population.population * food_per_person
        population.food -= need
        if population.food < 0:
            deaths = min(population.population, max(0, int(-population.food // food_per_person)))
            population.population -= deaths
            population.food = 0
            world.record("aggregate_disaster", f"food shortage reduced {population.id}", entities=[population.id], data={"deaths": deaths})
        else:
            population.development += population.labor * 0.001
        world.record("aggregate_tick", f"{population.id} advanced one period", entities=[population.id], data={"population": population.population, "food": population.food})
    world.advance(days)


def reconcile_population(world: World, population_id: str) -> dict[str, int]:
    """Compare an aggregate total with individually resolved actors."""
    population = world.aggregate_populations[population_id]
    local_count = sum(1 for actor in world.actors.values() if actor.location_id == population.place_id)
    return {"aggregate_population": population.population, "resolved_local_people": local_count, "unresolved": max(0, population.population - local_count)}
