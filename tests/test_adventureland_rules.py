import unittest

from redos.bootstrap import build_tiny_world
from redos.model import GoodType
from redos.rules import RuleBook


class AdventurelandRuleTests(unittest.TestCase):
    def test_data_defined_multi_room_object_rule(self) -> None:
        world = build_tiny_world()
        world.add(GoodType("barrel", "Barrel", 10.0))
        barrel = world.create_lot("barrel", 1, holder_id="cellar", owner_id="tavern-business")
        book = RuleBook.from_data([
            {
                "id": "move-barrel-from-cellar",
                "verb": "move",
                "noun": "barrel",
                "when": [
                    {"op": "entity_field_eq", "entity": "$actor", "field": "location_id", "value": "tavern"},
                    {"op": "object_at", "object": "$barrel", "place": "cellar"},
                    {"op": "actor_has_access", "actor": "$actor", "place": "cellar"},
                ],
                "then": [{"op": "move_object", "object": "$barrel", "to_holder": "$actor"}],
            }
        ])
        # The actor must first be in the tavern, while the object remains in a
        # distinct nested room.  No bespoke Python action is needed.
        world.actors["merchant"].location_id = "tavern"
        result = book.invoke(world, context={"actor": "merchant", "barrel": barrel.id}, verb="move", noun="barrel")
        self.assertTrue(result)
        self.assertEqual(world.quantity_held("merchant", "barrel"), 1)
        self.assertEqual(world.quantity_held("cellar", "barrel"), 0)
        self.assertEqual(world.events[-2].kind, "goods_transfer")

    def test_command_rules_are_first_match_and_occurrences_are_separate(self) -> None:
        world = build_tiny_world()
        world.actors["merchant"].location_id = "tavern"
        book = RuleBook.from_data([
            {"id": "specific", "verb": "look", "noun": "bar", "when": [{"op": "always"}], "then": [{"op": "record", "kind": "specific", "description": "specific"}]},
            {"id": "generic", "verb": "look", "when": [{"op": "always"}], "then": [{"op": "record", "kind": "generic", "description": "generic"}]},
            {"id": "occurrence", "when": [{"op": "always"}], "then": [{"op": "record", "kind": "occurrence", "description": "tick"}]},
        ])
        book.invoke(world, context={}, verb="look", noun="bar")
        self.assertEqual([event.kind for event in world.events[-2:]], ["specific", "rule_fired"])
        book.occurrences(world, context={})
        self.assertEqual(world.events[-2].kind, "occurrence")


if __name__ == "__main__":
    unittest.main()
