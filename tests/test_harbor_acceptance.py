import unittest

from redos.harbor import build_harbor_world, harbor_audit
from redos.runtime import advance_world, run
from redos.simulation import apply_transport_weather, set_route_condition


class LivingHarborAcceptanceTests(unittest.TestCase):
    def test_harbor_fixture_has_regional_assets_and_runs_thirty_days(self) -> None:
        state = build_harbor_world(seed=11)
        world = run(state.world, 30)
        report = harbor_audit(world)
        self.assertEqual(world.now.day, 31)
        self.assertEqual(len(world.transport_facilities), 6)
        self.assertGreaterEqual(len(world.transport_assets), 3)
        self.assertTrue(report["journeys"]["completed"])
        self.assertGreater(report["goods_moved"].get("grain", 0), 0)
        assignments = {asset_id: details["assignments"] for asset_id, details in report["asset_utilization"].items()}
        self.assertGreaterEqual(assignments["staten-sloop"], 2)
        self.assertGreaterEqual(assignments["warehouse-cart"], 2)
        self.assertGreaterEqual(assignments["dock-cart"], 2)
        self.assertGreaterEqual(assignments["manhattan-sloop"], 1)
        self.assertGreaterEqual(report["facility_utilization"]["manhattan-dock"]["completed_operations"], 1)
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])
        self.assertEqual(report["invariants"]["market_balance_errors"], [])

    def test_weather_disruption_delays_supply_then_recovery_completes_it(self) -> None:
        state = build_harbor_world(seed=12)
        world = state.world
        # Let ordinary business adjudication create and load the Staten-to-
        # Manhattan obligation before the external disruption is injected.
        for _ in range(18):
            advance_world(world, 1)
        weather_id = apply_transport_weather(
            world,
            ("staten-dock",),
            weather="harbor ice storm",
            wind=0.9,
            waterway="storm",
        )
        run(world, 5)
        self.assertTrue(any(event.kind == "freight_delayed" for event in world.events))
        self.assertEqual(sum(1 for event in world.events if event.kind == "freight_delayed"), 1)
        set_route_condition(world, "staten-dock", accessible=True, wind=0.0, waterway="calm")
        run(world, 25)
        report = harbor_audit(world)
        self.assertTrue(report["journeys"]["completed"])
        self.assertIn(weather_id, {cause for event in world.events if event.kind == "route_condition_changed" for cause in event.causes})
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])
        self.assertEqual(report["invariants"]["market_balance_errors"], [])

    def test_supply_disruption_changes_downstream_production(self) -> None:
        baseline = build_harbor_world(seed=12).world
        disrupted = build_harbor_world(seed=12).world
        for _ in range(18):
            advance_world(baseline, 1)
            advance_world(disrupted, 1)
        apply_transport_weather(
            disrupted,
            ("staten-dock", "newjersey-dock"),
            weather="regional storm",
            wind=0.8,
            waterway="storm",
        )
        for _ in range(120):
            advance_world(baseline, 1)
            advance_world(disrupted, 1)
        baseline_production = sum(event.kind == "production" for event in baseline.events)
        disrupted_production = sum(event.kind == "production" for event in disrupted.events)
        self.assertGreater(baseline_production, disrupted_production)
        self.assertGreater(baseline.quantity_held("workshop-business", "grain"), disrupted.quantity_held("workshop-business", "grain"))
        self.assertTrue(any(event.kind == "freight_delayed" for event in disrupted.events))
        self.assertEqual(harbor_audit(disrupted)["invariants"]["conservation_errors"], [])


if __name__ == "__main__":
    unittest.main()
