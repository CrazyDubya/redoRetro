"""The canonical, deliberately small world model.

There is one source of truth for locations, ownership, money, and goods.  Systems
such as rules and markets operate on this object rather than keeping shadow
inventories or player-only state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable


@dataclass
class Place:
    id: str
    name: str
    development_level: int = 1
    parent_id: str | None = None
    exits: dict[str, str] = field(default_factory=dict)


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


@dataclass
class Actor:
    id: str
    name: str
    location_id: str
    age: int = 20
    household_id: str | None = None
    occupation: str | None = None
    employer_id: str | None = None
    skills: dict[str, float] = field(default_factory=dict)
    money: float = 0.0
    debt: float = 0.0
    health: float = 1.0
    intention: str | None = None
    knowledge: dict[str, str] = field(default_factory=dict)
    beliefs: dict[str, str] = field(default_factory=dict)
    trust: dict[str, float] = field(default_factory=dict)
    relationships: dict[str, float] = field(default_factory=dict)


@dataclass
class Business:
    id: str
    name: str
    location_id: str
    kind: str
    cash: float = 0.0
    employees: list[str] = field(default_factory=list)
    production_rates: dict[str, float] = field(default_factory=dict)


@dataclass
class Market:
    id: str
    place_id: str
    fixed_prices: dict[str, float] = field(default_factory=dict)
    balances: dict[str, float] = field(default_factory=dict)
    production_rates: dict[str, float] = field(default_factory=dict)
    demand_rates: dict[str, float] = field(default_factory=dict)
    last_updated_day: int = 0


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

    def __init__(self, *, start: datetime | None = None) -> None:
        self.now = start or datetime(1770, 1, 1)
        self.places: dict[str, Place] = {}
        self.routes: dict[str, Route] = {}
        self.goods: dict[str, GoodType] = {}
        self.lots: dict[str, InventoryLot] = {}
        self.households: dict[str, Household] = {}
        self.actors: dict[str, Actor] = {}
        self.businesses: dict[str, Business] = {}
        self.markets: dict[str, Market] = {}
        self.events: list[CausalEvent] = []
        self._event_number = 0
        self._lot_number = 0

    def add(self, entity: Any) -> Any:
        collection = {
            Place: self.places,
            Route: self.routes,
            GoodType: self.goods,
            InventoryLot: self.lots,
            Household: self.households,
            Actor: self.actors,
            Business: self.businesses,
            Market: self.markets,
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

    def location_of(self, holder_id: str) -> str:
        if holder_id in self.actors:
            return self.actors[holder_id].location_id
        if holder_id in self.businesses:
            return self.businesses[holder_id].location_id
        if holder_id in self.places:
            return holder_id
        raise KeyError(f"unknown holder {holder_id!r}")

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
    ) -> InventoryLot:
        if quantity <= 0:
            raise ValueError("lot quantity must be positive")
        if good_type_id not in self.goods:
            raise KeyError(good_type_id)
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
        return lot

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
        return new_lots

    def move_actor(self, actor_id: str, destination_id: str, *, causes: Iterable[str] = (), reason: str = "actor moved") -> CausalEvent:
        actor = self.actors[actor_id]
        origin = actor.location_id
        actor.location_id = destination_id
        return self.record(
            "movement",
            reason,
            actors=[actor_id],
            entities=[origin, destination_id],
            causes=causes,
        )

    def pay(self, payer_id: str, payee_id: str, amount: float, *, causes: Iterable[str] = (), reason: str = "payment") -> CausalEvent:
        if amount < 0:
            raise ValueError("payment cannot be negative")
        payer = self.actors.get(payer_id) or self.businesses.get(payer_id)
        payee = self.actors.get(payee_id) or self.businesses.get(payee_id)
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
