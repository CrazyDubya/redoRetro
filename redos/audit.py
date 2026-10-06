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


def conservation_report(world: World) -> dict[str, dict[str, float]]:
    """Reconcile all created lots against current stock and consumption."""
    created: dict[str, float] = defaultdict(float)
    current: dict[str, float] = defaultdict(float)
    consumed: dict[str, float] = defaultdict(float)
    for lot_id, quantity in world._lot_original_quantity.items():
        lot = world.lots[lot_id]
        if world._lot_counts_as_creation.get(lot_id, True):
            created[lot.good_type_id] += quantity
        current[lot.good_type_id] += lot.quantity
    for event in world.events:
        if event.kind == "consumption":
            consumed[event.data["good_type_id"]] += event.data["quantity"]
    goods = set(created) | set(current) | set(consumed)
    return {
        good_id: {
            "created": created[good_id],
            "consumed": consumed[good_id],
            "current": current[good_id],
            "difference": created[good_id] - consumed[good_id] - current[good_id],
        }
        for good_id in sorted(goods)
    }


def conservation_errors(world: World, tolerance: float = 1e-6) -> list[str]:
    return [
        f"{good_id} conservation difference {values['difference']}"
        for good_id, values in conservation_report(world).items()
        if abs(values["difference"]) > tolerance
    ]


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
        next_entries = [entry for entry in actor.schedule if entry.start_hour > world.now.hour]
        next_entry = min(next_entries, key=lambda entry: entry.start_hour, default=(min(actor.schedule, key=lambda entry: entry.start_hour) if actor.schedule else None))
        previous_places = [event.entities[0] for event in reversed(world.events) if event.kind == "movement" and actor.id in event.actors]
        heard = [
            {"from": statement.speaker_id, "content": statement.content, "trust": actor.trust.get(statement.speaker_id, 0.5)}
            for statement in world.statements.values()
            if statement.listener_id == actor.id
        ]
        report.append({
            "actor_id": actor.id,
            "why_here": actor.current_activity or actor.intention,
            "where_before": previous_places[0] if previous_places else None,
            "going_afterward": next_entry.activity if next_entry else None,
            "relationships": dict(actor.relationships),
            "witnessed": known,
            "heard": heard,
            "trust": dict(actor.trust),
            "beliefs": dict(actor.beliefs),
        })
    return report
