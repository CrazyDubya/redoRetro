import unittest

from redos.bootstrap import build_tiny_world
from redos.enterprise import invest_in_capacity
from redos.living import Recipe
from redos.model import GoodType
from redos.runtime import _adjudicate_businesses


class CapitalismTests(unittest.TestCase):
    def test_capacity_investment_changes_existing_recipe_without_bypassing_inputs(self):
        world = build_tiny_world(seed=41)
        world.add(GoodType("grain", "Grain", 4.0))
        world.add(GoodType("flour", "Flour", 8.0))
        business = world.businesses["workshop-business"]
        worker = world.actors["cooper"]
        recipe = Recipe("mill-flour", {"grain": 1.0}, "flour", 1.0)
        world.recipes[business.id] = [recipe]
        business.inventory_targets["flour"] = 2.0
        world.create_lot("grain", 2.0, holder_id=business.id, owner_id=business.id, provenance=("capitalism-test-input",))
        worker.work_hours_by_day[world.now.date().isoformat()] = 8.0
        before_cash = business.cash

        invest_in_capacity(world, business.id, recipe.id, 100.0, capacity_gain=1.0)
        _adjudicate_businesses(world)

        self.assertEqual(business.cash, before_cash - 100.0)
        self.assertEqual(business.capital, 100.0)
        self.assertEqual(business.production_capacity[recipe.id], 2.0)
        self.assertEqual(world.quantity_held(business.id, "flour"), 2.0)
        self.assertEqual(world.quantity_held(business.id, "grain"), 0.0)
        production = [event for event in world.events if event.kind == "production"]
        self.assertEqual(production[-1].data["quantity"], 2.0)
        self.assertTrue(any(event.kind == "capacity_investment" for event in world.events))

    def test_capacity_does_not_create_output_when_inputs_are_missing(self):
        world = build_tiny_world(seed=42)
        world.add(GoodType("grain", "Grain", 4.0))
        world.add(GoodType("flour", "Flour", 8.0))
        business = world.businesses["workshop-business"]
        worker = world.actors["cooper"]
        recipe = Recipe("mill-flour", {"grain": 1.0}, "flour", 1.0)
        world.recipes[business.id] = [recipe]
        business.inventory_targets["flour"] = 3.0
        business.production_capacity[recipe.id] = 10.0
        worker.work_hours_by_day[world.now.date().isoformat()] = 8.0
        _adjudicate_businesses(world)
        self.assertEqual(world.quantity_held(business.id, "flour"), 0.0)
        self.assertFalse(any(event.kind == "production" for event in world.events))


if __name__ == "__main__":
    unittest.main()
