"""Bounded, source-documented Lower Manhattan street slice.

This module adds geography to the existing canonical ``World``.  Streets are
ordinary ``Place`` nodes and ordinary directed ``Route`` edges, so actors,
transport assets, passengers, and any future player controller use the same
movement authority.

The names and broad landmark choices are deliberately historical, while the
coordinates and short playable graph are an explicitly approximate fixture.
They are not a claim to have reconstructed every 1770 parcel or frontage.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .harbor import build_harbor_world
from .model import Door, Place, Route, SituatedObject, World
from .simulation import route_is_accessible
from .vertical import SliceState


RATZER_LOC_URL = "https://www.loc.gov/item/91684092/"
RATZER_NYPL_URL = "https://digitalcollections.nypl.org/items/ed619490-c5aa-012f-7ed8-58d385a7bc34"


@dataclass(frozen=True)
class StreetDistrict:
    """The installed bounded district, expressed as canonical world ids."""

    street_nodes: tuple[str, ...]
    visitable_sites: tuple[str, ...]
    interior_sites: tuple[str, ...]
    street_route_ids: tuple[str, ...]


_STREET_NODES = (
    ("wall-street", "Wall Street", 2.5, 0.5),
    ("broad-street", "Broad Street", 2.0, -0.5),
    ("pearl-street", "Pearl Street", 3.0, -1.5),
    ("water-street", "Water Street", 4.0, -1.0),
)

_EXTERIOR_SITES = (
    ("royal-exchange", "Royal Exchange", 2.3, -0.7),
    ("fly-market", "Fly Market", 3.5, -0.9),
    ("trinity-churchyard", "Trinity Churchyard", 1.2, 0.1),
    # The existing dock remains the harbor's canonical waterfront site.
    ("dock", "Old Dock", 4.4, -0.8),
)

_INTERIOR_SITES = ("tavern", "shop", "workshop", "warehouse")


def _add_place(world: World, place_id: str, name: str, x: float, y: float, *, interior: bool) -> None:
    if place_id in world.places:
        place = world.places[place_id]
        place.x = x
        place.y = y
        place.is_interior = interior
        return
    world.add(Place(place_id, name, development_level=2, x=x, y=y, is_interior=interior))


def _add_walk_edge(world: World, route_id: str, origin_id: str, destination_id: str, distance: float = 0.2) -> str:
    if route_id not in world.routes:
        world.add(Route(route_id, origin_id, destination_id, distance, 0, "walk", "road", ("walk",)))
    return route_id


def install_lower_manhattan(world: World) -> StreetDistrict:
    """Install the bounded M3.1 street graph into an existing harbor world."""
    for place_id, name, x, y in _STREET_NODES:
        _add_place(world, place_id, name, x, y, interior=False)
    for place_id, name, x, y in _EXTERIOR_SITES:
        _add_place(world, place_id, name, x, y, interior=False)
    for place_id in _INTERIOR_SITES:
        place = world.places[place_id]
        place.is_interior = True

    for door in (
        Door("tavern-door", "broad-street", "tavern"),
        Door("shop-door", "wall-street", "shop"),
        Door("workshop-door", "pearl-street", "workshop"),
        Door("warehouse-door", "water-street", "warehouse", locked=True, access_tag="warehouse"),
    ):
        if door.id not in world.doors:
            world.add(door)
    for obj in (
        SituatedObject("tavern-ledger", "Tavern ledger", "tavern"),
        SituatedObject("shop-counter", "Shop counter", "shop"),
        SituatedObject("exchange-board", "Exchange board", "royal-exchange"),
        SituatedObject(
            "dock-crane",
            "Dock crane",
            "dock",
            actions=("inspect", "operate"),
            required_skill="dockwork",
            required_skill_level=1.0,
        ),
    ):
        if obj.id not in world.situated_objects:
            world.add(obj)

    # These connections are a compact, traversable interpretation of the
    # lower-city streets and waterfront landmarks shown on the Ratzer survey.
    # Every playable street edge is explicitly directional in the canonical
    # route table, with a matching reverse edge.
    edges = (
        ("wall-broad", "wall-street", "broad-street"),
        ("broad-pearl", "broad-street", "pearl-street"),
        ("pearl-water", "pearl-street", "water-street"),
        ("water-dock", "water-street", "dock"),
        ("wall-trinity", "wall-street", "trinity-churchyard"),
        ("broad-exchange", "broad-street", "royal-exchange"),
        ("pearl-market", "pearl-street", "fly-market"),
        ("broad-tavern", "broad-street", "tavern"),
        ("wall-shop", "wall-street", "shop"),
        ("pearl-workshop", "pearl-street", "workshop"),
        ("water-warehouse", "water-street", "warehouse"),
        # Existing harbor homes enter the street graph through ordinary
        # feeder edges. These prevent the physical door model from forcing
        # residents onto the old direct interior shortcuts.
        ("home-a-wall", "home-a", "wall-street"),
        ("home-b-broad", "home-b", "broad-street"),
        ("home-c-pearl", "home-c", "pearl-street"),
    )
    route_ids: list[str] = []
    for edge_id, origin_id, destination_id in edges:
        route_ids.append(_add_walk_edge(world, f"street-{edge_id}", origin_id, destination_id))
        route_ids.append(_add_walk_edge(world, f"street-{edge_id}-reverse", destination_id, origin_id))

    visitable_sites = (*_INTERIOR_SITES, *(site_id for site_id, *_ in _EXTERIOR_SITES))
    district = StreetDistrict(
        street_nodes=tuple(place_id for place_id, *_ in _STREET_NODES),
        visitable_sites=visitable_sites,
        interior_sites=_INTERIOR_SITES,
        street_route_ids=tuple(route_ids),
    )
    world.runtime["street_district"] = {
        "source": {
            "title": "Ratzer plan of New York, surveyed 1766–1767",
            "library_of_congress": RATZER_LOC_URL,
            "new_york_public_library": RATZER_NYPL_URL,
            "historical_scope": "names and broad landmark relationships",
            "fixture_scope": "bounded playable graph; approximate coordinates and connections",
        },
        "street_nodes": district.street_nodes,
        "visitable_sites": district.visitable_sites,
        "interior_sites": district.interior_sites,
        "street_route_ids": district.street_route_ids,
    }
    return district


def build_street_world(*, seed: int = 0) -> SliceState:
    """Build the harbor plus the first directly explorable street district."""
    state = build_harbor_world(seed=seed)
    install_lower_manhattan(state.world)
    return state


def street_path(world: World, origin_id: str, destination_id: str) -> list[Route]:
    """Return a currently accessible walking path through the district."""
    street_route_ids = set(world.runtime.get("street_district", {}).get("street_route_ids", ()))
    if origin_id == destination_id:
        return []
    queue: deque[tuple[str, list[Route]]] = deque([(origin_id, [])])
    visited = {origin_id}
    while queue:
        place_id, path = queue.popleft()
        for route in world.routes.values():
            if route.id not in street_route_ids or route.origin_id != place_id or not route_is_accessible(world, route, mode="walk"):
                continue
            if route.destination_id in visited:
                continue
            next_path = [*path, route]
            if route.destination_id == destination_id:
                return next_path
            visited.add(route.destination_id)
            queue.append((route.destination_id, next_path))
    return []
