import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

from redos.actions import purchase
from redos.persistence import execute_once, load_snapshot, save_snapshot
from redos.streets import build_street_world


class PersistenceTests(unittest.TestCase):
    def test_sqlite_snapshot_round_trip_restores_canonical_world(self) -> None:
        world = build_street_world(seed=31).world
        world.runtime["test_marker"] = {"source": "canonical"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.sqlite3"
            info = save_snapshot(world, path)
            world.actors["merchant"].location_id = "dock"
            world.runtime["test_marker"] = {"source": "mutated"}

            restored = load_snapshot(path)

        self.assertEqual(info.snapshot_id, "latest")
        self.assertEqual(restored.seed, 31)
        self.assertEqual(restored.now, world.now)
        self.assertEqual(restored.actors["merchant"].location_id, "shop")
        self.assertEqual(restored.runtime["test_marker"], {"source": "canonical"})
        self.assertEqual([event.id for event in restored.events], [event.id for event in world.events[: info.event_count]])
        self.assertEqual(restored.routes["street-wall-broad"].origin_id, "wall-street")

    def test_command_retry_is_a_noop_and_survives_reload(self) -> None:
        world = build_street_world(seed=32).world
        buyer_id = "merchant"
        before_money = world.actors[buyer_id].money
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.sqlite3"
            first = execute_once(
                world,
                "buy-metals-1",
                purchase,
                world,
                buyer_id,
                "shop-market",
                "metals",
                1.0,
            )
            lots_after_first = world.quantity_held(buyer_id, "metals")
            events_after_first = len(world.events)
            save_snapshot(world, path)

            second = execute_once(
                world,
                "buy-metals-1",
                purchase,
                world,
                buyer_id,
                "shop-market",
                "metals",
                1.0,
            )
            restored = load_snapshot(path)
            third = execute_once(
                restored,
                "buy-metals-1",
                purchase,
                restored,
                buyer_id,
                "shop-market",
                "metals",
                1.0,
            )

        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(world.quantity_held(buyer_id, "metals"), lots_after_first)
        self.assertEqual(len(world.events), events_after_first)
        self.assertAlmostEqual(world.actors[buyer_id].money, before_money - first.total)

    def test_corrupt_snapshot_payload_is_rejected(self) -> None:
        world = build_street_world(seed=33).world
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.sqlite3"
            save_snapshot(world, path)
            connection = sqlite3.connect(path)
            connection.execute("UPDATE world_snapshots SET payload = ? WHERE snapshot_id = 'latest'", (b"corrupt",))
            connection.commit()
            connection.close()
            with self.assertRaises(ValueError):
                load_snapshot(path)

    def test_snapshot_payload_is_explicit_json_not_executable_serialization(self) -> None:
        world = build_street_world(seed=36).world
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "format.sqlite3"
            save_snapshot(world, path)
            connection = sqlite3.connect(path)
            payload = connection.execute("SELECT payload FROM world_snapshots WHERE snapshot_id = 'latest'").fetchone()[0]
            schema_version = connection.execute("SELECT schema_version FROM world_snapshots WHERE snapshot_id = 'latest'").fetchone()[0]
            connection.close()

        self.assertEqual(schema_version, 2)
        document = json.loads(payload.decode("utf-8"))
        self.assertEqual(document["format"], "redos.world")

    def test_command_id_conflict_is_rejected_even_after_reload(self) -> None:
        world = build_street_world(seed=34).world
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.sqlite3"
            execute_once(world, "same-id", purchase, world, "merchant", "shop-market", "metals", 1.0)
            save_snapshot(world, path)
            restored = load_snapshot(path)
            with self.assertRaises(ValueError):
                execute_once(restored, "same-id", purchase, restored, "merchant", "shop-market", "metals", 2.0)

    def test_snapshot_preserves_rng_for_72_plus_72_hour_equivalent_run(self) -> None:
        uninterrupted = build_street_world(seed=35).world
        resumed = build_street_world(seed=35).world
        from redos.runtime import advance_world

        for _ in range(144):
            advance_world(uninterrupted, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equivalence.sqlite3"
            for _ in range(72):
                advance_world(resumed, 1)
            save_snapshot(resumed, path)
            resumed = load_snapshot(path)
            for _ in range(72):
                advance_world(resumed, 1)

        self.assertEqual(uninterrupted.now, resumed.now)
        self.assertEqual(uninterrupted.random.getstate(), resumed.random.getstate())
        self.assertEqual([event.kind for event in uninterrupted.events], [event.kind for event in resumed.events])
        self.assertEqual(uninterrupted._event_number, resumed._event_number)


if __name__ == "__main__":
    unittest.main()
