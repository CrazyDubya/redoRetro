"""Autonomous time progression and aggregate-resolution helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
import heapq
from typing import Iterable

from .living import activity_for_hour
from .model import Actor, AggregatePopulation, Route, RouteCondition, World


TERRAIN_TRAVEL_MULTIPLIERS = {
    "road": 1.0,
    "plain": 1.0,
    "rough": 1.5,
    "mountain": 2.5,
    "water": 1.0,
}

# Midwinter's useful distinction is that the movement method changes how
# terrain is negotiated. These are small, inspectable factors, not a second
# movement model.
METHOD_TERRAIN_MULTIPLIERS = {
    ("walk", "rough"): 1.2,
    ("cart", "rough"): 1.4,
    ("cart", "mountain"): 1.8,
    # Riding Club translation: a mounted journey is still ordinary canonical
    # movement, but terrain changes the horse's passage time rather than
    # teleporting the rider between named destinations.
    ("horse", "rough"): 1.1,
    ("horse", "mountain"): 1.7,
    ("vessel", "water"): 1.0,
}

WATERWAY_TRAVEL_MULTIPLIERS = {
    "calm": 1.0,
    "choppy": 1.25,
    "storm": 2.0,
    "ice": 3.0,
}


def route_condition(world: World, route_id: str) -> RouteCondition:
    return world.route_conditions.get(route_id, RouteCondition(route_id))


def route_is_accessible(world: World, route: Route, *, mode: str | None = None) -> bool:
    condition = route_condition(world, route.id)
    if not condition.accessible:
        return False
    return not (mode is not None and route.allowed_modes and mode not in route.allowed_modes)


def effective_route_hours(world: World, route: Route, *, mode: str | None = None) -> float:
    """Return passage time after terrain and current conditions are applied."""
    effective_mode = mode or route.mode
    # A generic map search (mode=None) may traverse a route whose nominal
    # mode is road/water while a later carrier-specific adjudication applies
    # the route's allowed_modes constraint.
    if not route_is_accessible(world, route, mode=mode):
        raise ValueError(f"route {route.id} is inaccessible for {effective_mode}")
    condition = route_condition(world, route.id)
    terrain_multiplier = TERRAIN_TRAVEL_MULTIPLIERS.get(route.terrain, 1.0)
    method_multiplier = METHOD_TERRAIN_MULTIPLIERS.get((effective_mode, route.terrain), 1.0)
    return max(1.0, route.travel_days * 24.0 * terrain_multiplier * method_multiplier * condition.travel_multiplier)


def _weather_multiplier(route: Route, *, wind: float, waterway: str) -> float:
    if route.mode not in {"water", "vessel"} and route.terrain != "water":
        return 1.0
    return WATERWAY_TRAVEL_MULTIPLIERS[waterway] * (1.0 + 0.25 * abs(wind))


def set_route_condition(
    world: World,
    route_id: str,
    *,
    accessible: bool = True,
    travel_multiplier: float = 1.0,
    hazard: str | None = None,
    wind: float = 0.0,
    waterway: str = "calm",
    causes: tuple[str, ...] = (),
) -> RouteCondition:
    if route_id not in world.routes:
        raise KeyError(route_id)
    if travel_multiplier <= 0:
        raise ValueError("route travel multiplier must be positive")
    if not -1.0 <= wind <= 1.0:
        raise ValueError("wind must be normalized between -1 and 1")
    if waterway not in WATERWAY_TRAVEL_MULTIPLIERS:
        raise ValueError(f"unknown waterway condition {waterway!r}")
    route = world.routes[route_id]
    effective_multiplier = travel_multiplier * _weather_multiplier(route, wind=wind, waterway=waterway)
    condition = RouteCondition(route_id, accessible, effective_multiplier, hazard, wind, waterway)
    world.route_conditions[route_id] = condition
    world.record(
        "route_condition_changed",
        f"route {route_id} conditions changed",
        entities=[route_id],
        causes=causes,
        data={
            "accessible": accessible,
            "travel_multiplier": travel_multiplier,
            "hazard": hazard,
            "wind": wind,
            "waterway": waterway,
        },
    )
    return condition


def apply_transport_weather(
    world: World,
    route_ids: Iterable[str],
    *,
    weather: str,
    wind: float = 0.0,
    waterway: str = "calm",
    accessible: bool | None = None,
    travel_multiplier: float = 1.0,
    causes: tuple[str, ...] = (),
) -> str:
    """Inject one auditable weather stimulus across selected transport routes."""
    selected = tuple(route_ids)
    if not selected:
        raise ValueError("weather must affect at least one route")
    # Validate the complete update before recording the external stimulus or
    # changing any route.  A malformed multi-route weather report is atomic.
    for route_id in selected:
        if route_id not in world.routes:
            raise KeyError(route_id)
    if not -1.0 <= wind <= 1.0:
        raise ValueError("wind must be normalized between -1 and 1")
    if waterway not in WATERWAY_TRAVEL_MULTIPLIERS:
        raise ValueError(f"unknown waterway condition {waterway!r}")
    if travel_multiplier <= 0:
        raise ValueError("route travel multiplier must be positive")
    event = world.record(
        "transport_weather",
        f"{weather} affected transport routes",
        entities=selected,
        causes=causes,
        data={"wind": wind, "waterway": waterway},
    )
    blocked = accessible if accessible is not None else waterway in {"storm", "ice"}
    route_accessible = accessible if accessible is not None else not blocked
    for route_id in selected:
        set_route_condition(
            world,
            route_id,
            accessible=route_accessible,
            travel_multiplier=travel_multiplier,
            hazard=weather,
            wind=wind,
            waterway=waterway,
            causes=(event.id,),
        )
    return event.id


def route_path(world: World, origin_id: str, destination_id: str, *, mode: str | None = None) -> list[Route]:
    if origin_id == destination_id:
        return []
    queue: deque[tuple[str, list[Route]]] = deque([(origin_id, [])])
    visited = {origin_id}
    while queue:
        place_id, path = queue.popleft()
        for route in world.routes.values():
            if route.origin_id != place_id or route.destination_id in visited or not route_is_accessible(world, route, mode=mode):
                continue
            next_path = [*path, route]
            if route.destination_id == destination_id:
                return next_path
            visited.add(route.destination_id)
            queue.append((route.destination_id, next_path))
    return []


def best_route(
    world: World,
    origin_id: str,
    destination_id: str,
    *,
    mode: str | None = None,
    max_hours: float | None = None,
) -> list[Route]:
    """Choose the fastest currently accessible route, including waypoints."""
    if origin_id == destination_id:
        return []
    frontier: list[tuple[float, str, tuple[str, ...]]] = [(0.0, origin_id, ())]
    best_seen: dict[str, float] = {origin_id: 0.0}
    while frontier:
        elapsed, place_id, route_ids = heapq.heappop(frontier)
        if place_id == destination_id:
            return [world.routes[route_id] for route_id in route_ids]
        if elapsed > best_seen.get(place_id, float("inf")) + 1e-9:
            continue
        for route in world.routes.values():
            if route.origin_id != place_id or route.destination_id in route_ids or not route_is_accessible(world, route, mode=mode):
                continue
            next_elapsed = elapsed + effective_route_hours(world, route, mode=mode)
            if max_hours is not None and next_elapsed > max_hours + 1e-9:
                continue
            if next_elapsed + 1e-9 >= best_seen.get(route.destination_id, float("inf")):
                continue
            best_seen[route.destination_id] = next_elapsed
            heapq.heappush(frontier, (next_elapsed, route.destination_id, (*route_ids, route.id)))
    return []


def walk(world: World, actor_id: str, destination_id: str):
    """Start embodied movement for either a player or an autonomous actor."""
    actor = world.actors[actor_id]
    path = route_path(world, actor.location_id, destination_id, mode="walk")
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
    # Passenger services are ordinary route choices declared in world data.
    # The actor first walks to the boarding place, then boards if the carrier
    # is physically present and available; there is no teleporting fallback.
    services = [
        service for service in world.runtime.get("passenger_services", ())
        if len(service) >= 3 and service[2] == target_id and service[0] in world.transport_assets
    ]
    # Prefer a physically present service, trying every candidate before
    # deciding that a passenger must wait or use an ordinary land route.
    for service in services:
        asset_id, boarding_place_id, _destination_id = service[:3]
        if actor.location_id != boarding_place_id:
            continue
        from .transport import board_passenger

        try:
            board_passenger(world, actor.id, asset_id, target_id)
            return True
        except ValueError:
            continue
    for service in services:
        asset_id, boarding_place_id, _destination_id = service[:3]
        boarding_path = route_path(world, actor.location_id, boarding_place_id, mode="walk")
        if not boarding_path:
            continue
        route = boarding_path[0]
        movement = world.begin_movement(actor.id, route.id)
        world.record(
            "travel_started",
            f"{actor.id} travelled toward passenger boarding at {boarding_place_id}",
            actors=[actor.id],
            entities=[route.id, boarding_place_id],
            data={"travel_hours": movement.duration_hours, "distance": route.distance, "service": asset_id},
        )
        return True
    if services:
        if not any(
            event.kind == "passenger_service_unavailable"
            and actor.id in event.actors
            and event.at == world.now
            for event in world.events
        ):
            world.record(
                "passenger_service_unavailable",
                f"{actor.id} could not board any service toward {target_id}",
                actors=[actor.id],
                entities=[target_id, *(service[0] for service in services)],
            )
        return False
    path = route_path(world, actor.location_id, target_id, mode="walk")
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
                    actor.work_hours_by_day[day_key] = actor.work_hours_by_day.get(day_key, 0.0) + hours
                    world.record("work", f"{actor.id} worked qualifying time", actors=[actor.id, employer_id], entities=[entry.target_location_id], data={"day": day_key, "hours": hours})


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
