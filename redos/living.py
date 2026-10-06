"""Shared kernels from the small Stimulating Simulations programs.

These are intentionally mechanics, not game-specific scenarios.  Every
operation mutates the canonical World and records a causal event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import EnvironmentCell, Observation, ScheduleEntry, Statement, World


@dataclass(frozen=True)
class Recipe:
    id: str
    inputs: dict[str, float]
    output_good_id: str
    output_quantity: float
    work_days: int = 1


def produce(world: World, business_id: str, recipe: Recipe, *, causes: Iterable[str] = ()) -> str:
    """Consume physical inputs and create a traceable output lot."""
    consumed: list[str] = []
    for good_id, quantity in recipe.inputs.items():
        consumed.extend(world.consume_goods(business_id, good_id, quantity, causes=causes, reason=f"{recipe.id} input consumed"))
    event = world.record(
        "production",
        f"{business_id} produced {recipe.output_quantity} {recipe.output_good_id}",
        entities=[business_id, recipe.id, recipe.output_good_id],
        causes=[*causes, *consumed],
        data={"inputs": recipe.inputs, "quantity": recipe.output_quantity},
    )
    world.create_lot(recipe.output_good_id, recipe.output_quantity, holder_id=business_id, owner_id=business_id, provenance=(event.id, *consumed))
    return event.id


def witness_event(
    world: World,
    *,
    event_id: str,
    content: str,
    witnesses: Iterable[str],
    confidence: float = 1.0,
) -> list[Observation]:
    """Give only the named witnesses an observation of an event."""
    observations: list[Observation] = []
    for witness_id in witnesses:
        world._observation_number += 1
        observation = Observation(
            id=f"observation-{world._observation_number}",
            witness_id=witness_id,
            event_id=event_id,
            observed_at=world.now,
            content=content,
            confidence=max(0.0, min(1.0, confidence)),
        )
        world.observations[observation.id] = observation
        world.actors[witness_id].knowledge[event_id] = observation.id
        observations.append(observation)
        world.record("observation", f"{witness_id} observed {event_id}", actors=[witness_id], entities=[event_id, observation.id])
    return observations


def recollect(world: World, observation_id: str, *, content: str, confidence: float) -> Observation:
    observation = world.observations[observation_id]
    observation.recollection = content
    observation.confidence = max(0.0, min(1.0, confidence))
    world.record("recollection", f"{observation.witness_id} recalled {observation.event_id}", actors=[observation.witness_id], entities=[observation_id])
    return observation


def tell(
    world: World,
    speaker_id: str,
    listener_id: str,
    proposition: str,
    content: str,
    *,
    truthful: bool,
    trust_delta: float = 0.0,
) -> Statement:
    """Transfer a statement, not world truth, into another actor's belief."""
    world._statement_number += 1
    statement = Statement(
        id=f"statement-{world._statement_number}",
        speaker_id=speaker_id,
        listener_id=listener_id,
        proposition=proposition,
        content=content,
        truthful=truthful,
        at=world.now,
    )
    world.statements[statement.id] = statement
    listener = world.actors[listener_id]
    listener.beliefs[proposition] = content
    listener.trust[speaker_id] = max(0.0, min(1.0, listener.trust.get(speaker_id, 0.5) + trust_delta))
    world.record(
        "statement",
        f"{speaker_id} told {listener_id} about {proposition}",
        actors=[speaker_id, listener_id],
        entities=[statement.id, proposition],
        data={"truthful": truthful, "content": content},
    )
    return statement


def add_environment_cell(world: World, cell: EnvironmentCell) -> None:
    world.add(cell)


def propagate(
    world: World,
    *,
    source_cell_id: str,
    from_state: str,
    to_state: str,
    probability: float,
    causes: Iterable[str] = (),
) -> list[str]:
    """Propagate a state through neighboring cells under local conditions."""
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    source = world.environment_cells[source_cell_id]
    if source.state != from_state:
        return []
    # Deterministic threshold makes tests reproducible while retaining local
    # environmental conditions: fuel raises spread, moisture suppresses it.
    changed: list[str] = []
    for neighbor_id in source.neighbors:
        neighbor = world.environment_cells[neighbor_id]
        local_probability = probability * max(0.0, min(1.0, neighbor.fuel)) * (1.0 - max(0.0, min(1.0, neighbor.moisture)))
        if neighbor.state != from_state and local_probability >= 0.5:
            neighbor.state = to_state
            changed.append(neighbor_id)
            world.record(
                "environment_propagation",
                f"{source_cell_id} propagated {to_state} to {neighbor_id}",
                entities=[source_cell_id, neighbor_id],
                causes=causes,
                data={"probability": local_probability},
            )
    return changed


@dataclass(frozen=True)
class Bid:
    bidder_id: str
    amount: float


def auction(world: World, seller_id: str, good_type_id: str, quantity: float, bids: Iterable[Bid]) -> tuple[str, float]:
    """Run a simple sealed auction and transfer canonical inventory."""
    candidates = sorted(bids, key=lambda bid: bid.amount, reverse=True)
    for bid in candidates:
        if bid.amount <= 0:
            continue
        try:
            payment = world.pay(bid.bidder_id, seller_id, bid.amount, reason="auction settlement")
        except ValueError:
            continue
        world.transfer_goods(good_type_id, quantity, from_holder=seller_id, to_holder=bid.bidder_id, to_owner=bid.bidder_id, causes=[payment.id], reason="auction ownership transfer")
        world.record("auction", f"{bid.bidder_id} won {good_type_id}", actors=[seller_id, bid.bidder_id], entities=[good_type_id], causes=[payment.id], data={"amount": bid.amount})
        return bid.bidder_id, bid.amount
    raise ValueError("no solvent bid")


def activity_for_hour(world: World, actor_id: str) -> ScheduleEntry | None:
    actor = world.actors[actor_id]
    hour = world.now.hour
    candidates = [entry for entry in actor.schedule if entry.start_hour <= hour < entry.end_hour]
    return max(candidates, key=lambda entry: entry.priority, default=None)


def apply_schedule_intention(world: World, actor_id: str) -> ScheduleEntry | None:
    actor = world.actors[actor_id]
    entry = activity_for_hour(world, actor_id)
    if entry is None:
        actor.current_activity = None
        actor.intention = None
        return None
    actor.current_activity = entry.activity
    actor.intention = entry.activity
    world.record("intention", f"{actor_id} intends to {entry.activity}", actors=[actor_id], entities=[entry.target_location_id])
    return entry
