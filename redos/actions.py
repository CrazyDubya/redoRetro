"""Shared embodied actions for players and autonomous actors.

The action gateway delegates to the existing canonical kernels. It does not
create a player-only location, inventory, market, or information model.
"""

from __future__ import annotations

from typing import Iterable

from .interactions import interact_with_object, reachable_path
from .living import tell
from .market import TradeQuote, buy
from .model import Statement, World, require_finite
from .transport import board_passenger


def move(world: World, actor_id: str, destination_id: str):
    """Start a canonical walking journey that respects doors and routes."""
    actor = world.actors[actor_id]
    path = reachable_path(world, actor_id, destination_id)
    if not path:
        raise ValueError(f"no walkable path from {actor.location_id} to {destination_id}")
    # begin_movement performs the rejection checks before allocating an event
    # or changing actor travel state.  Set the multi-leg intention only after
    # that transition has committed; a rejected second command must not
    # overwrite the destination of the journey already in progress.
    movement = world.begin_movement(actor_id, path[0].id)
    actor.journey_destination_id = destination_id
    world.record(
        "travel_started",
        f"{actor_id} started travelling toward {destination_id}",
        actors=[actor_id],
        entities=[path[0].id, path[0].destination_id],
        data={"travel_hours": movement.duration_hours, "distance": path[0].distance},
    )
    return movement


def inspect(world: World, actor_id: str, object_id: str) -> dict[str, object]:
    """Inspect a situated object through the canonical access gateway."""
    return interact_with_object(world, actor_id, object_id, "inspect")


def converse(
    world: World,
    speaker_id: str,
    listener_id: str,
    proposition: str,
    content: str,
    *,
    truthful: bool,
    trust_delta: float = 0.0,
) -> Statement:
    """Exchange one statement between actors who are physically co-present."""
    speaker = world.actors[speaker_id]
    listener = world.actors[listener_id]
    if speaker_id == listener_id:
        raise ValueError("an actor cannot converse with itself")
    if speaker.traveling_to is not None or listener.traveling_to is not None:
        raise ValueError("conversation requires stationary actors")
    if speaker.location_id != listener.location_id:
        raise ValueError("conversation requires physical co-location")
    return tell(
        world,
        speaker_id,
        listener_id,
        proposition,
        content,
        truthful=truthful,
        trust_delta=trust_delta,
    )


def purchase(
    world: World,
    buyer_id: str,
    market_id: str,
    good_type_id: str,
    quantity: float,
    *,
    offer: float | None = None,
) -> TradeQuote:
    """Buy physical stock through the existing canonical market operation."""
    buyer = world.actors[buyer_id]
    if buyer.traveling_to is not None:
        raise ValueError("buyer must be stationary for purchase")
    return buy(world, buyer_id, market_id, good_type_id, quantity, offer=offer)


def board(world: World, actor_id: str, asset_id: str, destination_id: str):
    """Board a physically present passenger carrier through the movement kernel."""
    return board_passenger(world, actor_id, asset_id, destination_id)


def deliver(
    world: World,
    seller_id: str,
    recipient_id: str,
    good_type_id: str,
    quantity: float,
    *,
    causes: Iterable[str] = (),
) -> list[str]:
    """Deliver seller-owned goods between co-located, stationary holders."""
    cause_ids = tuple(causes)
    require_finite(quantity, "delivery quantity")
    if quantity <= 0:
        raise ValueError("delivery quantity must be positive")
    seller = world.actors.get(seller_id)
    recipient_location = world.location_of(recipient_id)
    if seller is None:
        raise KeyError(seller_id)
    if seller.traveling_to is not None:
        raise ValueError("seller must be stationary for delivery")
    if world.location_of(seller_id) != recipient_location:
        raise ValueError("delivery requires physical co-location")
    recipient_actor = world.actors.get(recipient_id)
    if recipient_actor is not None and recipient_actor.traveling_to is not None:
        raise ValueError("recipient must be stationary for delivery")
    lots = world.transfer_owned_goods_at(
        seller_id,
        recipient_location,
        good_type_id,
        quantity,
        to_holder=recipient_id,
        from_holder_id=seller_id,
        causes=cause_ids,
        reason="physical delivery",
    )
    transfer_event = world.events[-1]
    world.record(
        "delivery",
        f"{seller_id} delivered {quantity} {good_type_id} to {recipient_id}",
        actors=[seller_id],
        entities=[recipient_id, good_type_id, *(lot.id for lot in lots)],
        causes=[transfer_event.id, *cause_ids],
        data={"quantity": quantity, "good_type_id": good_type_id, "place_id": recipient_location},
    )
    return [lot.id for lot in lots]
