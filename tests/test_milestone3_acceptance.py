import json
import unittest

from redos.runtime import run
from redos.streets import build_street_world, street_audit
from redos.vertical import default_dock_incident


class Milestone3AcceptanceTests(unittest.TestCase):
    def test_thirty_day_street_audit_is_canonical_and_machine_readable(self) -> None:
        state = build_street_world(seed=51)
        world = run(state.world, 30, external_events=(default_dock_incident(state),))
        report = street_audit(world)

        self.assertEqual(world.now.day, 31)
        self.assertEqual(report["schema"], "redos.street-audit.v1")
        self.assertEqual(report["invariants"]["validation_errors"], [])
        self.assertEqual(report["invariants"]["conservation_errors"], [])
        self.assertEqual(report["invariants"]["market_balance_errors"], [])
        self.assertGreater(report["events"].get("movement", 0), 20)
        self.assertGreater(report["events"].get("work", 0), 100)
        self.assertGreater(report["events"].get("meeting", 0), 20)
        self.assertGreaterEqual(len(report["incident_beliefs"]), 2)
        self.assertGreaterEqual(len(set(report["incident_beliefs"].values())), 2)
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
