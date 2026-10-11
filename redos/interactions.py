"""Physical access and situated-object interaction gateways.

These operations intentionally sit on top of the canonical ``World``. They do
not create a player inventory, player location, or remote interaction path.
The same functions are available to NPC rules and a future browser client.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .model import Door, Route, World
from .simulation import route_is_accessible


def _access_tags(world: World, actor_id: str) -> set[str]:
    raw = world.actors[actor_id].skills.get("access", ())
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(tag) for tag in raw}
    return set()


def can_open_door(world: World, actor_id: str, door_id: str) -> bool:
    """Return whether the actor is authorized to pass the current door."""
    door = world.doors[door_id]
    if not door.open:
        return False
    if not door.locked:
        return True
    return door.access_tag is not None and door.access_tag in _access_tags(world, actor_id)


def _door_for_transition(world: World, origin_id: str, destination_id: str) -> Door | None:
    for door in world.doors.values():
        if {door.origin_id, door.destination_id} == {origin_id, destination_id}:
            return door
    return None


def _transition_door_is_required(world: World, origin_id: str, destination_id: str) -> bool:
    """Prevent legacy shortcut routes from bypassing an interior threshold."""
    return any(
        world.places[place_id].is_interior
        for place_id in (origin_id, destination_id)
        if place_id in world.places
    ) and any(
        origin_id in {door.origin_id, door.destination_id}
        or destination_id in {door.origin_id, door.destination_id}
        for door in world.doors.values()
    )


def reachable_path(world: World, actor_id: str, destination_id: str) -> list[Route]:
    """Find a walking route that respects doors and current route conditions."""
    actor = world.actors[actor_id]
    if destination_id not in world.places:
        raise KeyError(destination_id)
    if actor.location_id == destination_id:
        return []
    queue: deque[tuple[str, list[Route]]] = deque([(actor.location_id, [])])
    visited = {actor.location_id}
    while queue:
        place_id, path = queue.popleft()
        for route in world.routes.values():
            if route.origin_id != place_id or route.destination_id in visited:
                continue
            if not route_is_accessible(world, route, mode="walk"):
                continue
            door = _door_for_transition(world, route.origin_id, route.destination_id)
            if door is None and _transition_door_is_required(world, route.origin_id, route.destination_id):
                continue
            if door is not None and not can_open_door(world, actor_id, door.id):
                continue
            next_path = [*path, route]
            if route.destination_id == destination_id:
                return next_path
            visited.add(route.destination_id)
            queue.append((route.destination_id, next_path))
    return []


def enter_door(world: World, actor_id: str, door_id: str) -> str:
    """Begin timed movement through a co-located, authorized door."""
    actor = world.actors[actor_id]
    door = world.doors[door_id]
    if actor.traveling_to is not None:
        raise ValueError(f"{actor_id} is moving and cannot use a door")
    if actor.location_id not in {door.origin_id, door.destination_id}:
        raise ValueError(f"{actor_id} is not at door {door_id}")
    if not can_open_door(world, actor_id, door_id):
        raise PermissionError(f"{actor_id} cannot pass door {door_id}")
    destination_id = door.destination_id if actor.location_id == door.origin_id else door.origin_id
    route = next(
        (
            candidate
            for candidate in world.routes.values()
            if candidate.origin_id == actor.location_id and candidate.destination_id == destination_id
            and candidate.mode == "walk"
        ),
        None,
    )
    if route is None:
        raise ValueError(f"door {door_id} has no canonical walking route")
    movement = world.begin_movement(actor_id, route.id)
    movement.door_id = door_id
    world.record(
        "door_passage_started",
        f"{actor_id} started passing {door_id}",
        actors=[actor_id],
        entities=[door_id, movement.id, destination_id],
        data={"destination_id": destination_id, "duration_hours": movement.duration_hours},
    )
    return destination_id


def interact_with_object(world: World, actor_id: str, object_id: str, action: str) -> dict[str, Any]:
    """Perform one authorized action on a physically co-located object."""
    actor = world.actors[actor_id]
    obj = world.situated_objects[object_id]
    if actor.traveling_to is not None:
        raise ValueError(f"{actor_id} is moving and cannot interact")
    if actor.location_id != obj.place_id:
        raise ValueError(f"{actor_id} is not co-located with {object_id}")
    if action not in obj.actions:
        raise ValueError(f"{object_id} does not support {action}")
    if obj.required_skill is not None and actor.skills.get(obj.required_skill, 0.0) < obj.required_skill_level:
        raise PermissionError(f"{actor_id} lacks skill {obj.required_skill}")
    if action == "open":
        obj.state["open"] = True
    elif action == "close":
        obj.state["open"] = False
    event = world.record(
        "object_interaction",
        f"{actor_id} performed {action} on {object_id}",
        actors=[actor_id],
        entities=[object_id, obj.place_id],
        data={"action": action, "state": dict(obj.state)},
    )
    return {"object_id": object_id, "action": action, "state": dict(obj.state), "event_id": event.id}
