"""Evidence-backed inspection helpers for the living-tavern acceptance test."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .model import World


def inventory_totals(world: World) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for lot in world.lots.values():
        if lot.quantity > 0:
            totals[lot.good_type_id] += lot.quantity
    return dict(totals)


def validate_world(world: World) -> list[str]:
    errors: list[str] = []
    for lot in world.lots.values():
        if lot.quantity < -1e-9:
            errors.append(f"negative lot {lot.id}")
        try:
            world.location_of(lot.holder_id)
        except KeyError:
            errors.append(f"lot {lot.id} has unknown holder {lot.holder_id}")
    for actor in world.actors.values():
        if actor.health <= 0:
            errors.append(f"actor {actor.id} is unhealthy")
        if actor.money < -1e-9:
            errors.append(f"actor {actor.id} has negative cash")
    return errors


def causal_chain(world: World, event_id: str) -> list[dict[str, Any]]:
    return [
        {"id": event.id, "kind": event.kind, "description": event.description, "causes": list(event.causes), "data": event.data}
        for event in world.explain(event_id)
    ]


def information_graph(world: World) -> dict[str, Any]:
    return {
        "observations": [
            {"id": observation.id, "witness": observation.witness_id, "event": observation.event_id, "content": observation.recollection or observation.content, "confidence": observation.confidence}
            for observation in world.observations.values()
        ],
        "statements": [
            {"id": statement.id, "speaker": statement.speaker_id, "listener": statement.listener_id, "proposition": statement.proposition, "content": statement.content, "truthful": statement.truthful}
            for statement in world.statements.values()
        ],
        "beliefs": {actor.id: dict(actor.beliefs) for actor in world.actors.values() if actor.beliefs},
        "trust": {actor.id: dict(actor.trust) for actor in world.actors.values() if actor.trust},
    }


def tavern_report(world: World, tavern_id: str) -> list[dict[str, Any]]:
    """Answer the tavern questions from canonical actor/event state."""
    report: list[dict[str, Any]] = []
    for actor in world.actors.values():
        if actor.location_id != tavern_id:
            continue
        known = []
        for observation_id in actor.knowledge.values():
            observation = world.observations.get(observation_id)
            if observation is not None:
                known.append({"event": observation.event_id, "content": observation.recollection or observation.content, "confidence": observation.confidence})
        report.append({
            "actor_id": actor.id,
            "why_here": actor.current_activity or actor.intention,
            "where_before": next((event.entities[0] for event in reversed(world.events) if event.kind == "movement" and actor.id in event.actors), None),
            "going_afterward": actor.intention,
            "relationships": dict(actor.relationships),
            "witnessed": known,
            "heard": [statement.content for statement in world.statements.values() if statement.listener_id == actor.id],
            "trust": dict(actor.trust),
            "beliefs": dict(actor.beliefs),
        })
    return report
