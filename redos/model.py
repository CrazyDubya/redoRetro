"""The canonical, deliberately small world model.

There is one source of truth for locations, ownership, money, and goods.  Systems
such as rules and markets operate on this object rather than keeping shadow
inventories or player-only state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random
from typing import Any, Iterable


@dataclass
class Place:
    id: str
    name: str
    development_level: int = 1
    parent_id: str | None = None
    exits: dict[str, str] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    is_interior: bool = False


@dataclass
class Route:
    id: str
    origin_id: str
    destination_id: str
    distance: float
    travel_days: int
    mode: str = "walk"


@dataclass
class GoodType:
    id: str
    name: str
    base_price: float
    weight: float = 1.0
    perishable_days: int | None = None


@dataclass
class InventoryLot:
    id: str
    good_type_id: str
    quantity: float
    holder_id: str
    owner_id: str
    provenance: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass
class Household:
    id: str
    name: str
    residence_id: str
    members: list[str] = field(default_factory=list)
    cash: float = 0.0
    debt: float = 0.0
    daily_expenses: float = 0.0


@dataclass
class Actor:
    id: str
    name: str
    location_id: str
    age: int = 20
    developmental_stage: str = "adult"
    life_events: list[str] = field(default_factory=list)
    household_id: str | None = None
    occupation: str | None = None
    employer_id: str | None = None
    skills: dict[str, float] = field(default_factory=dict)
    money: float = 0.0
    debt: float = 0.0
    health: float = 1.0
    intention: str | None = None
    knowledge: dict[str, Any] = field(default_factory=dict)
    beliefs: dict[str, str] = field(default_factory=dict)
    trust: dict[str, float] = field(default_factory=dict)
    relationships: dict[str, float] = field(default_factory=dict)
    schedule: list[ScheduleEntry] = field(default_factory=list)
    current_activity: str | None = None
    schedule_override_until: datetime | None = None
    traveling_to: str | None = None
    travel_remaining_days: int = 0
    travel_remaining_hours: int = 0
    temporary_activity: str | None = None
    temporary_target_location_id: str | None = None
    is_player: bool = False
    position: tuple[float, float] | None = None
    work_hours_by_day: dict[str, float] = field(default_factory=dict)
    paid_work_days: set[str] = field(default_factory=set)
    needs: dict[str, float] = field(default_factory=dict)
    active_task: str | None = None
    task_target_location_id: str | None = None
    journey_destination_id: str | None = None


@dataclass
class Business:
    id: str
    name: str
    location_id: str
    kind: str
    cash: float = 0.0
    employees: list[str] = field(default_factory=list)
    production_rates: dict[str, float] = field(default_factory=dict)
    advertising: float = 0.0
    price_markup: dict[str, float] = field(default_factory=dict)
    market_share: dict[str, float] = field(default_factory=dict)
    debt: float = 0.0
    research: float = 0.0
    inventory_targets: dict[str, float] = field(default_factory=dict)


@dataclass
class JobOpening:
    id: str
    employer_id: str
    occupation: str
    wage_per_day: float
    start_hour: int
    end_hour: int
    qualification: str | None = None


@dataclass
class Contract:
    id: str
    seller_id: str
    buyer_id: str
    good_type_id: str
    quantity: float
    unit_price: float
    origin_id: str
    destination_id: str
    due_day: int
    due_at: datetime | None = None
    status: str = "open"
    shipment_id: str | None = None
    signed_at: datetime | None = None
    allocated_at: datetime | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    failure_reason: str | None = None
    causal_event_ids: list[str] = field(default_factory=list)
    late_reported: bool = False


@dataclass(frozen=True)
class ScheduleEntry:
    start_hour: int
    end_hour: int
    activity: str
    target_location_id: str
    priority: int = 0
    interruptible: bool = True


@dataclass
class Observation:
    id: str
    witness_id: str
    event_id: str
    observed_at: datetime
    content: str
    confidence: float = 1.0
    recollection: str | None = None


@dataclass
class Statement:
    id: str
    speaker_id: str
    listener_id: str
    proposition: str
    content: str
    truthful: bool
    at: datetime


@dataclass
class EnvironmentCell:
    id: str
    location_id: str
    state: str
    fuel: float = 0.0
    moisture: float = 0.0
    neighbors: tuple[str, ...] = ()


@dataclass
class Movement:
    id: str
    actor_id: str
    route_id: str
    origin_id: str
    destination_id: str
    elapsed_hours: float
    duration_hours: float
    progress: float = 0.0


@dataclass
class Shipment:
    id: str
    contract_id: str
    origin_id: str
    destination_id: str
    route_ids: tuple[str, ...]
    current_route_index: int = 0
    elapsed_hours: float = 0.0
    cargo_lot_ids: list[str] = field(default_factory=list)
    status: str = "dispatched"


@dataclass
class AggregatePopulation:
    id: str
    place_id: str
    population: int
    food: float
    labor: float
    development: float = 0.0
    resolved_households: int = 0


@dataclass
class Market:
    id: str
    place_id: str
    fixed_prices: dict[str, float] = field(default_factory=dict)
    balances: dict[str, float] = field(default_factory=dict)
    production_rates: dict[str, float] = field(default_factory=dict)
    demand_rates: dict[str, float] = field(default_factory=dict)
    demand_backlog: dict[str, float] = field(default_factory=dict)
    price_history: dict[str, list[float]] = field(default_factory=dict)
    last_updated_day: int = 0
    production_source: str | None = None
    production_account_id: str | None = None


@dataclass
class CausalEvent:
    id: str
    kind: str
    at: datetime
    description: str
    actors: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    causes: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


class World:
    """Canonical world state and mutation gateway."""

    def __init__(self, *, start: datetime | None = None, seed: int = 0) -> None:
        self.now = start or datetime(1770, 1, 1)
        self.seed = seed
        self.random = random.Random(seed)
        self.places: dict[str, Place] = {}
        self.routes: dict[str, Route] = {}
        self.goods: dict[str, GoodType] = {}
        self.lots: dict[str, InventoryLot] = {}
        self.households: dict[str, Household] = {}
        self.actors: dict[str, Actor] = {}
        self.businesses: dict[str, Business] = {}
        self.job_openings: dict[str, JobOpening] = {}
        self.contracts: dict[str, Contract] = {}
        self.markets: dict[str, Market] = {}
        self.observations: dict[str, Observation] = {}
        self.statements: dict[str, Statement] = {}
        self.environment_cells: dict[str, EnvironmentCell] = {}
        self.aggregate_populations: dict[str, AggregatePopulation] = {}
        self.movements: dict[str, Movement] = {}
        self.shipments: dict[str, Shipment] = {}
        self.recipes: dict[str, list[Any]] = {}
        self.runtime: dict[str, Any] = {}
        self.events: list[CausalEvent] = []
        self._event_number = 0
        self._lot_number = 0
        self._lot_original_quantity: dict[str, float] = {}
        self._lot_counts_as_creation: dict[str, bool] = {}
        self._observation_number = 0
        self._statement_number = 0

    def add(self, entity: Any) -> Any:
        collection = {
            Place: self.places,
            Route: self.routes,
            GoodType: self.goods,
            InventoryLot: self.lots,
            Household: self.households,
            Actor: self.actors,
            Business: self.businesses,
            JobOpening: self.job_openings,
            Contract: self.contracts,
            Market: self.markets,
            Observation: self.observations,
            Statement: self.statements,
            EnvironmentCell: self.environment_cells,
            AggregatePopulation: self.aggregate_populations,
            Movement: self.movements,
            Shipment: self.shipments,
        }.get(type(entity))
        if collection is None:
            raise TypeError(f"unsupported world entity: {type(entity)!r}")
        collection[entity.id] = entity
        if isinstance(entity, Household):
            for actor_id in entity.members:
                if actor_id in self.actors:
                    self.actors[actor_id].household_id = entity.id
        return entity

    def record(
        self,
        kind: str,
        description: str,
        *,
        actors: Iterable[str] = (),
        entities: Iterable[str] = (),
        causes: Iterable[str] = (),
        data: dict[str, Any] | None = None,
    ) -> CausalEvent:
        self._event_number += 1
        event = CausalEvent(
            id=f"event-{self._event_number}",
            kind=kind,
            at=self.now,
            description=description,
            actors=tuple(actors),
            entities=tuple(entities),
            causes=tuple(causes),
            data=data or {},
        )
        self.events.append(event)
        return event

    def advance(self, days: int = 1) -> None:
        if days < 0:
            raise ValueError("time cannot move backwards")
        self.now += timedelta(days=days)

    def advance_hours(self, hours: int = 1) -> None:
        if hours < 0:
            raise ValueError("time cannot move backwards")
        self.now += timedelta(hours=hours)

    def location_of(self, holder_id: str) -> str:
        if holder_id in self.actors:
            return self.actors[holder_id].location_id
        if holder_id in self.businesses:
            return self.businesses[holder_id].location_id
        if holder_id in self.places:
            return holder_id
        if holder_id in self.households:
            return self.households[holder_id].residence_id
        if holder_id in self.shipments:
            shipment = self.shipments[holder_id]
            if shipment.status == "delivered":
                return shipment.destination_id
            if shipment.status == "lost":
                return shipment.origin_id
            if shipment.current_route_index < len(shipment.route_ids):
                route = self.routes[shipment.route_ids[shipment.current_route_index]]
                return route.origin_id
            return shipment.destination_id
        raise KeyError(f"unknown holder {holder_id!r}")

    def position_of(self, holder_id: str) -> tuple[float, float]:
        if holder_id in self.actors and self.actors[holder_id].position is not None:
            return self.actors[holder_id].position  # type: ignore[return-value]
        place_id = self.location_of(holder_id)
        place = self.places[place_id]
        return (place.x, place.y)

    def lots_held_by(self, holder_id: str, good_type_id: str | None = None) -> list[InventoryLot]:
        return [
            lot for lot in self.lots.values()
            if lot.holder_id == holder_id and (good_type_id is None or lot.good_type_id == good_type_id)
            and lot.quantity > 0
        ]

    def quantity_held(self, holder_id: str, good_type_id: str) -> float:
        return sum(lot.quantity for lot in self.lots_held_by(holder_id, good_type_id))

    def create_lot(
        self,
        good_type_id: str,
        quantity: float,
        *,
        holder_id: str,
        owner_id: str | None = None,
        provenance: Iterable[str] = (),
        counts_as_creation: bool = True,
    ) -> InventoryLot:
        if quantity <= 0:
            raise ValueError("lot quantity must be positive")
        if good_type_id not in self.goods:
            raise KeyError(good_type_id)
        if not self._holder_exists(holder_id):
            raise KeyError(f"unknown holder {holder_id!r}")
        self._lot_number += 1
        lot = InventoryLot(
            id=f"lot-{self._lot_number}",
            good_type_id=good_type_id,
            quantity=quantity,
            holder_id=holder_id,
            owner_id=owner_id or holder_id,
            provenance=tuple(provenance),
            created_at=self.now,
        )
        self.lots[lot.id] = lot
        self._lot_original_quantity[lot.id] = quantity
        self._lot_counts_as_creation[lot.id] = counts_as_creation
        self._sync_market_balances(self.location_of(holder_id))
        return lot

    def _holder_exists(self, holder_id: str) -> bool:
        return holder_id in self.actors or holder_id in self.businesses or holder_id in self.places or holder_id in self.households or holder_id in self.shipments

    def _sync_market_balances(self, place_id: str) -> None:
        for market in self.markets.values():
            if market.place_id != place_id:
                continue
            for good_id in market.fixed_prices:
                market.balances[good_id] = self.quantity_held(place_id, good_id)

    def transfer_goods(
        self,
        good_type_id: str,
        quantity: float,
        *,
        from_holder: str,
        to_holder: str,
        to_owner: str | None = None,
        causes: Iterable[str] = (),
        reason: str = "goods transferred",
    ) -> list[InventoryLot]:
        if quantity <= 0:
            raise ValueError("transfer quantity must be positive")
        available = self.quantity_held(from_holder, good_type_id)
        if available + 1e-9 < quantity:
            raise ValueError(f"{from_holder} holds {available}, cannot transfer {quantity}")
        remaining = quantity
        new_lots: list[InventoryLot] = []
        for lot in list(self.lots_held_by(from_holder, good_type_id)):
            moved = min(remaining, lot.quantity)
            lot.quantity -= moved
            new_lot = self.create_lot(
                good_type_id,
                moved,
                holder_id=to_holder,
                owner_id=to_owner or to_holder,
                provenance=(*lot.provenance, lot.id),
                counts_as_creation=False,
            )
            new_lots.append(new_lot)
            remaining -= moved
            if remaining <= 1e-9:
                break
        self.record(
            "goods_transfer",
            reason,
            entities=[good_type_id, from_holder, to_holder, *(lot.id for lot in new_lots)],
            causes=causes,
            data={"quantity": quantity, "good_type_id": good_type_id},
        )
        self._sync_market_balances(self.location_of(from_holder))
        self._sync_market_balances(self.location_of(to_holder))
        return new_lots

    def consume_goods(
        self,
        holder_id: str,
        good_type_id: str,
        quantity: float,
        *,
        causes: Iterable[str] = (),
        reason: str = "goods consumed",
    ) -> list[str]:
        if quantity <= 0:
            raise ValueError("consumption quantity must be positive")
        if self.quantity_held(holder_id, good_type_id) + 1e-9 < quantity:
            raise ValueError(f"{holder_id} does not hold enough {good_type_id}")
        remaining = quantity
        consumed: list[str] = []
        for lot in list(self.lots_held_by(holder_id, good_type_id)):
            used = min(remaining, lot.quantity)
            lot.quantity -= used
            consumed.append(lot.id)
            remaining -= used
            if remaining <= 1e-9:
                break
        self.record(
            "consumption",
            reason,
            entities=[holder_id, good_type_id, *consumed],
            causes=causes,
            data={"quantity": quantity, "good_type_id": good_type_id},
        )
        self._sync_market_balances(self.location_of(holder_id))
        return consumed

    def move_actor(self, actor_id: str, destination_id: str, *, causes: Iterable[str] = (), reason: str = "actor moved") -> CausalEvent:
        actor = self.actors[actor_id]
        origin = actor.location_id
        actor.location_id = destination_id
        destination = self.places[destination_id]
        actor.position = (destination.x, destination.y)
        return self.record(
            "movement",
            reason,
            actors=[actor_id],
            entities=[origin, destination_id],
            causes=causes,
        )

    def begin_movement(self, actor_id: str, route_id: str) -> Movement:
        actor = self.actors[actor_id]
        route = self.routes[route_id]
        if actor.traveling_to is not None:
            raise ValueError(f"{actor_id} is already moving")
        if actor.location_id != route.origin_id:
            raise ValueError(f"route {route_id} does not start at {actor.location_id}")
        origin = self.places[route.origin_id]
        actor.position = (origin.x, origin.y)
        self._event_number += 1
        movement = Movement(
            id=f"movement-{self._event_number}",
            actor_id=actor_id,
            route_id=route_id,
            origin_id=route.origin_id,
            destination_id=route.destination_id,
            elapsed_hours=0.0,
            duration_hours=max(1.0, route.travel_days * 24.0),
        )
        self.movements[movement.id] = movement
        actor.traveling_to = route.destination_id
        actor.travel_remaining_hours = int(movement.duration_hours)
        return movement

    def advance_movements(self, hours: float) -> list[str]:
        if hours < 0:
            raise ValueError("movement time cannot move backwards")
        arrived: list[str] = []
        for movement_id, movement in list(self.movements.items()):
            movement.elapsed_hours += hours
            movement.progress = min(1.0, movement.elapsed_hours / movement.duration_hours)
            actor = self.actors[movement.actor_id]
            origin = self.places[movement.origin_id]
            destination = self.places[movement.destination_id]
            actor.position = (
                origin.x + (destination.x - origin.x) * movement.progress,
                origin.y + (destination.y - origin.y) * movement.progress,
            )
            actor.travel_remaining_hours = max(0, int(movement.duration_hours - movement.elapsed_hours))
            if movement.progress >= 1.0:
                self.move_actor(actor.id, movement.destination_id, reason=f"arrived via {movement.route_id}")
                actor.traveling_to = None
                actor.travel_remaining_hours = 0
                del self.movements[movement_id]
                arrived.append(actor.id)
        return arrived

    def pay(self, payer_id: str, payee_id: str, amount: float, *, causes: Iterable[str] = (), reason: str = "payment") -> CausalEvent:
        if amount < 0:
            raise ValueError("payment cannot be negative")
        payer = self.actors.get(payer_id) or self.businesses.get(payer_id) or self.households.get(payer_id)
        payee = self.actors.get(payee_id) or self.businesses.get(payee_id) or self.households.get(payee_id)
        if payer is None or payee is None:
            raise KeyError("money must move between an actor or business")
        money_field = "money" if isinstance(payer, Actor) else "cash"
        if getattr(payer, money_field) + 1e-9 < amount:
            raise ValueError(f"{payer_id} cannot pay {amount}")
        setattr(payer, money_field, getattr(payer, money_field) - amount)
        money_field = "money" if isinstance(payee, Actor) else "cash"
        setattr(payee, money_field, getattr(payee, money_field) + amount)
        return self.record(
            "payment",
            reason,
            actors=[payer_id, payee_id],
            causes=causes,
            data={"amount": amount},
        )

    def explain(self, event_id: str) -> list[CausalEvent]:
        """Return an event and its recursively recorded causes."""
        by_id = {event.id: event for event in self.events}
        result: list[CausalEvent] = []
        seen: set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in seen or current_id not in by_id:
                return
            seen.add(current_id)
            event = by_id[current_id]
            result.append(event)
            for cause in event.causes:
                visit(cause)

        visit(event_id)
        return result
