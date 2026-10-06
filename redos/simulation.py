"""Autonomous time progression and aggregate-resolution helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
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


def _start_next_leg(world: World, actor: Actor, target_id: str) -> bool:
    path = route_path(world, actor.location_id, target_id)
    if not path:
        return False
    route = path[0]
    actor.traveling_to = route.destination_id
    actor.travel_remaining_hours = max(1, route.travel_days * 24)
    world.record(
        "travel_started",
        f"{actor.id} started travelling toward {target_id}",
        actors=[actor.id],
        entities=[route.id, route.destination_id],
        data={"travel_hours": actor.travel_remaining_hours},
    )
    return True


def _finish_travel(world: World, actor: Actor) -> None:
    destination = actor.traveling_to
    if destination is None:
        return
    world.move_actor(actor.id, destination, reason="autonomous actor arrived")
    actor.traveling_to = None
    actor.travel_remaining_hours = 0


def tick(world: World, hours: int = 1) -> None:
    """Advance the living world without a scripted protagonist."""
    if hours < 0:
        raise ValueError("hours cannot be negative")
    if hours == 0:
        return
    world.advance_hours(hours)
    for actor in world.actors.values():
        if actor.traveling_to is not None:
            actor.travel_remaining_hours -= hours
            if actor.travel_remaining_hours <= 0:
                _finish_travel(world, actor)
            continue
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
