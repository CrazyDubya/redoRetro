"""A small declarative rule engine inspired by the Scott Adams data model.

Adventureland's useful boundary was not its parser: the interpreter owned the
generic execution loop, while rooms, objects, conditions, and actions lived in
the game database.  Redos keeps that boundary and makes the predicates/actions
world-oriented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .model import World


Condition = Callable[[World, dict[str, Any]], bool]
Action = Callable[[World, dict[str, Any]], Any]


def _resolve(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return context[value[1:]]
    return value


@dataclass(frozen=True)
class Rule:
    id: str
    conditions: tuple[Condition, ...]
    actions: tuple[Action, ...]
    verb: str | None = None
    noun: str | None = None

    def applies(self, world: World, context: dict[str, Any]) -> bool:
        return all(condition(world, context) for condition in self.conditions)

    def execute(self, world: World, context: dict[str, Any]) -> list[Any]:
        if not self.applies(world, context):
            return []
        results = [action(world, context) for action in self.actions]
        world.record("rule_fired", f"rule {self.id} fired", entities=[self.id])
        return results

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "Rule":
        conditions = tuple(_condition_from_data(item) for item in data.get("when", []))
        actions = tuple(_action_from_data(item) for item in data.get("then", []))
        return cls(data["id"], conditions, actions, data.get("verb"), data.get("noun"))


class RuleBook:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = rules or []

    @classmethod
    def from_data(cls, data: list[dict[str, Any]]) -> "RuleBook":
        return cls([Rule.from_data(rule) for rule in data])

    def add(self, rule: Rule) -> None:
        self.rules.append(rule)

    def invoke(self, world: World, *, context: dict[str, Any], verb: str | None = None, noun: str | None = None) -> list[Any]:
        """Run the first matching command rule, like the original action scan."""
        for rule in self.rules:
            if rule.verb not in (None, verb) or rule.noun not in (None, noun):
                continue
            result = rule.execute(world, context)
            if result:
                return result
        return []

    def occurrences(self, world: World, *, context: dict[str, Any]) -> list[Any]:
        """Run every applicable non-command rule, analogous to occurrences."""
        results: list[Any] = []
        for rule in self.rules:
            if rule.verb is None and rule.noun is None:
                results.extend(rule.execute(world, context))
        return results


def _condition_from_data(data: dict[str, Any]) -> Condition:
    op = data["op"]
    if op == "entity_field_eq":
        entity_key, field, expected = data["entity"], data["field"], data["value"]

        def check(world: World, context: dict[str, Any]) -> bool:
            entity = _resolve(entity_key, context)
            expected_value = _resolve(expected, context)
            collection = next((getattr(world, name) for name in ("actors", "places", "businesses", "lots") if entity in getattr(world, name)), None)
            return collection is not None and getattr(collection[entity], field) == expected_value

        return check
    if op == "object_at":
        object_key, place_key = data["object"], data["place"]

        def check(world: World, context: dict[str, Any]) -> bool:
            object_id = _resolve(object_key, context)
            place_id = _resolve(place_key, context)
            lot = world.lots.get(object_id)
            return lot is not None and world.location_of(lot.holder_id) == place_id

        return check
    if op == "actor_has_access":
        actor_key, place_key = data["actor"], data["place"]

        def check(world: World, context: dict[str, Any]) -> bool:
            actor_id = _resolve(actor_key, context)
            place_id = _resolve(place_key, context)
            actor = world.actors[actor_id]
            allowed = set(actor.skills.get("access", [])) if isinstance(actor.skills.get("access"), list) else set()
            return actor.location_id == place_id or place_id in allowed

        return check
    if op == "has_quantity":
        holder_key, good_key, quantity = data["holder"], data["good"], data["quantity"]

        def check(world: World, context: dict[str, Any]) -> bool:
            return world.quantity_held(_resolve(holder_key, context), _resolve(good_key, context)) >= _resolve(quantity, context)

        return check
    if op == "always":
        return lambda world, context: True
    raise ValueError(f"unknown rule condition {op!r}")


def _action_from_data(data: dict[str, Any]) -> Action:
    op = data["op"]
    if op == "move_object":
        object_key, holder_key = data["object"], data["to_holder"]

        def action(world: World, context: dict[str, Any]) -> Any:
            object_id = _resolve(object_key, context)
            target = _resolve(holder_key, context)
            lot = world.lots[object_id]
            return world.transfer_goods(lot.good_type_id, lot.quantity, from_holder=lot.holder_id, to_holder=target, to_owner=target, reason=f"rule moved {object_id}")

        return action
    if op == "move_actor":
        actor_key, place_key = data["actor"], data["to"]

        def action(world: World, context: dict[str, Any]) -> Any:
            from .simulation import walk
            return walk(world, _resolve(actor_key, context), _resolve(place_key, context))

        return action
    if op == "record":
        kind, description = data["kind"], data["description"]

        def action(world: World, context: dict[str, Any]) -> Any:
            return world.record(kind, description, actors=[_resolve(actor, context) for actor in data.get("actors", [])])

        return action
    raise ValueError(f"unknown rule action {op!r}")
