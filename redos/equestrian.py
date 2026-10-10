"""Small Riding Club-derived mounted-travel primitives.

The donor's useful lane is a persistent horse with care, stamina and skill
consequences.  Redos deliberately represents the horse as the existing
canonical ``TransportAsset``: routes, movement, supplies, ownership and
events remain shared with carts and vessels.
"""

from __future__ import annotations

from .model import HorseState, Movement, World
from .transport import board_passenger, replenish_asset


def ride(world: World, rider_id: str, horse_id: str, destination_id: str) -> Movement:
    """Start a physical mounted journey through the canonical movement system."""
    horse = world.transport_assets[horse_id]
    if horse.asset_type != "horse":
        raise ValueError(f"{horse_id} is not a horse")
    movement = board_passenger(world, rider_id, horse_id, destination_id)
    world.record(
        "horse_mounted",
        f"{rider_id} mounted {horse_id}",
        actors=[rider_id],
        entities=[horse_id, movement.id, destination_id],
        causes=(movement.id,),
    )
    return movement


def _require_idle_horse(world: World, horse_id: str):
    horse = world.transport_assets[horse_id]
    if horse.asset_type != "horse":
        raise ValueError(f"{horse_id} is not a horse")
    if horse.assigned_shipment_id is not None:
        raise ValueError(f"horse {horse_id} is currently assigned")
    # Care is the recovery path for an exhausted or injured horse. Availability
    # and readiness are outputs of care, not prerequisites for it; only an
    # active assignment makes the horse physically unavailable to the stable.
    return horse


def care_for_horse(
    world: World,
    horse_id: str,
    action: str,
    amount: float = 1.0,
    *,
    source_id: str | None = None,
) -> float:
    """Apply one ordinary care action to an idle horse.

    ``feed`` replenishes the explicitly modelled feed supply. ``groom`` and
    ``rest`` restore operational readiness.  None of these actions changes
    location or creates an inventory source; feed must already be supplied by
    a canonical holder through ``replenish_asset``.
    """
    if amount <= 0:
        raise ValueError("care amount must be positive")
    horse = _require_idle_horse(world, horse_id)
    if action == "feed":
        added = replenish_asset(world, horse_id, "feed", amount, source_id=source_id)
        world.record(
            "horse_fed",
            f"{horse_id} was fed",
            entities=[horse_id, *( [source_id] if source_id else [])],
            data={"quantity": added},
        )
        return added
    if action not in {"groom", "rest"}:
        raise ValueError(f"unknown horse care action {action!r}")
    before = horse.readiness
    horse.readiness = min(1.0, horse.readiness + amount)
    restored = horse.readiness - before
    profile = world.horses.get(horse_id)
    if action == "rest" and profile is not None:
        profile.fatigue = max(0.0, profile.fatigue - amount)
        profile.injury = max(0.0, profile.injury - amount * 0.25)
    world.record(
        "horse_groomed" if action == "groom" else "horse_rested",
        f"{horse_id} received {action}",
        entities=[horse_id],
        data={
            "readiness_before": before,
            "readiness_after": horse.readiness,
            "restored": restored,
            "fatigue": profile.fatigue if profile is not None else None,
            "injury": profile.injury if profile is not None else None,
        },
    )
    if restored > 0 and horse.condition > 0:
        horse.available = True
        horse.unavailable_reason = None
    return restored
