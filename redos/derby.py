"""Small Derby Stallion-derived horse-management mechanics.

This module does not create a separate stable or race world.  A ``HorseState``
is canonical state attached to an existing horse ``TransportAsset``; training
and races mutate that state, the asset's readiness and the existing money/event
ledgers.
"""

from __future__ import annotations

from .model import HorseState, World
from .transport import assign_asset


TRAINING = {
    ("grass", "light"): ("speed", 0.01, 0.05, 0.01),
    ("grass", "strong"): ("speed", 0.03, 0.15, 0.03),
    ("grass", "maximum"): ("speed", 0.05, 0.30, 0.08),
    ("dirt", "light"): ("stamina", 0.01, 0.05, 0.01),
    ("dirt", "strong"): ("stamina", 0.03, 0.15, 0.03),
    ("dirt", "maximum"): ("stamina", 0.05, 0.30, 0.08),
}


def add_horse(
    world: World,
    asset_id: str,
    *,
    age_years: int = 3,
    sex: str = "unknown",
    speed: float = 0.5,
    stamina: float = 0.5,
    temperament: float = 0.5,
) -> HorseState:
    """Attach persistent Derby-style race state to an existing horse asset."""
    asset = world.transport_assets[asset_id]
    if asset.asset_type != "horse":
        raise ValueError(f"{asset_id} is not a horse")
    if asset_id in world.horses:
        raise ValueError(f"horse state already exists for {asset_id}")
    if age_years < 0:
        raise ValueError("horse age cannot be negative")
    if any(not 0 <= value <= 1 for value in (speed, stamina, temperament)):
        raise ValueError("horse abilities must be between zero and one")
    profile = HorseState(
        id=asset_id,
        asset_id=asset_id,
        age_years=age_years,
        sex=sex,
        speed=speed,
        stamina=stamina,
        temperament=temperament,
    )
    world.add(profile)
    world.record("horse_registered", f"{asset_id} entered the stable record", entities=[asset_id])
    return profile


def train_horse(world: World, horse_id: str, *, surface: str, intensity: str) -> HorseState:
    """Train one idle horse, recording improvement, fatigue and injury risk."""
    if (surface, intensity) not in TRAINING:
        raise ValueError("unknown training surface or intensity")
    horse = world.transport_assets[horse_id]
    profile = world.horses[horse_id]
    if horse.asset_type != "horse":
        raise ValueError(f"{horse_id} is not a horse")
    if horse.assigned_shipment_id is not None:
        raise ValueError(f"horse {horse_id} is currently assigned")
    if profile.injury > 0:
        raise ValueError(f"horse {horse_id} is injured")
    ability, gain, fatigue, injury_risk = TRAINING[(surface, intensity)]
    before = getattr(profile, ability)
    setattr(profile, ability, min(1.0, before + gain))
    profile.training_points += gain
    profile.fatigue = min(1.0, profile.fatigue + fatigue)
    horse.readiness = max(0.0, horse.readiness - fatigue)
    roll = world.random.random()
    injured = roll < injury_risk * (0.5 + profile.fatigue)
    if injured:
        profile.injury = min(1.0, 0.25 + injury_risk)
        horse.available = False
        horse.unavailable_reason = "horse injured"
    world.record(
        "horse_trained",
        f"{horse_id} trained on {surface} at {intensity} intensity",
        entities=[horse_id],
        data={
            "surface": surface,
            "intensity": intensity,
            "ability": ability,
            "ability_before": before,
            "ability_after": getattr(profile, ability),
            "fatigue": profile.fatigue,
            "injury": profile.injury,
            "injury_roll": roll,
        },
    )
    return profile


def race_horses(
    world: World,
    race_id: str,
    horse_ids: tuple[str, ...],
    *,
    location_id: str,
    distance_m: int,
    purse: float,
    purse_account_id: str,
    surface: str = "grass",
) -> tuple[str, ...]:
    """Run a deterministic, auditable race among co-located horses.

    This is intentionally an event adjudicator, not a second movement system:
    the horses must already be physically present at the race location and
    cannot be assigned to another journey.  The purse is an explicit payment
    from an existing canonical account to the winning owner.
    """
    if len(horse_ids) < 2 or len(set(horse_ids)) != len(horse_ids):
        raise ValueError("a race needs at least two distinct horses")
    if distance_m <= 0 or purse < 0:
        raise ValueError("race distance and purse must be non-negative")
    if surface not in {"grass", "dirt"}:
        raise ValueError("unknown race surface")
    entries = []
    for horse_id in horse_ids:
        horse = world.transport_assets[horse_id]
        profile = world.horses[horse_id]
        if horse.asset_type != "horse" or horse.location_id != location_id:
            raise ValueError("all race entries must be co-located horses")
        if horse.assigned_shipment_id is not None or profile.injury > 0:
            raise ValueError(f"horse {horse_id} is unavailable to race")
        if profile.age_years < 3:
            raise ValueError(f"horse {horse_id} is too young to race")
        if horse.readiness <= 0:
            raise ValueError(f"horse {horse_id} is not ready to race")
        surface_ability = profile.speed if surface == "grass" else profile.stamina
        distance_factor = profile.stamina if distance_m >= 1800 else profile.speed
        condition = max(0.0, 1.0 - profile.fatigue)
        score = (0.55 * surface_ability + 0.35 * distance_factor + 0.10 * profile.temperament) * condition
        score += world.random.random() * 0.001
        entries.append((score, horse_id))
    entries.sort(reverse=True)
    order = tuple(horse_id for _score, horse_id in entries)
    winner_id = order[0]
    winner = world.transport_assets[winner_id]
    winner_profile = world.horses[winner_id]
    if purse > 0:
        world.pay(
            purse_account_id,
            winner.owner_id,
            purse,
            reason=f"{race_id} prize purse",
        )
    for _score, horse_id in entries:
        profile = world.horses[horse_id]
        profile.races += 1
        profile.last_race_at = world.now
        profile.fatigue = min(1.0, profile.fatigue + min(0.75, distance_m / 10000.0))
        world.transport_assets[horse_id].readiness = max(0.0, world.transport_assets[horse_id].readiness - 0.10)
    winner_profile.wins += 1
    winner_profile.earnings += purse
    event = world.record(
        "horse_race",
        f"{race_id} finished at {location_id}",
        entities=[race_id, location_id, *horse_ids],
        data={"order": order, "winner": winner_id, "distance_m": distance_m, "surface": surface, "purse": purse},
    )
    for horse_id in horse_ids:
        world.record(
            "horse_race_result",
            f"{horse_id} finished {order.index(horse_id) + 1} in {race_id}",
            entities=[race_id, horse_id],
            causes=(event.id,),
            data={"place": order.index(horse_id) + 1, "winner": winner_id},
        )
    return order

