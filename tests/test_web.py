import json
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from redos.streets import build_street_world
from redos.web import create_server


class WebClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _get(self, path: str) -> dict | str:
        with urlopen(self.base + path) as response:
            body = response.read().decode()
            return body if "text/html" in response.headers.get("Content-Type", "") else json.loads(body)

    def _post(self, body: dict) -> dict:
        request = Request(
            self.base + "/api/command",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            return json.loads(response.read())

    def test_browser_shell_and_canonical_state_endpoint(self) -> None:
        page = self._get("/")
        state = self._get("/api/state")
        versioned_state = self._get("/v1/state")
        self.assertIn("Redos — The Living Streets", page)
        self.assertEqual(state["player"]["id"], "merchant")
        self.assertEqual(versioned_state["player"]["id"], "merchant")
        self.assertIn("shop", {place["id"] for place in state["places"]})
        self.assertIn("shop-counter", {obj["id"] for obj in state["objects"]})
        self.assertNotIn("tavern-ledger", {obj["id"] for obj in state["objects"]})

    def test_browser_commands_use_shared_actions_and_are_idempotent(self) -> None:
        inspected = self._post({"command_id": "inspect-1", "action": "inspect", "object_id": "shop-counter"})
        repeated = self._post({"command_id": "inspect-1", "action": "inspect", "object_id": "shop-counter"})
        self.assertEqual(inspected["result"], repeated["result"])
        self.assertEqual(inspected["state"]["event_count"], repeated["state"]["event_count"])

        purchased = self._post({
            "command_id": "purchase-1",
            "action": "purchase",
            "market_id": "shop-market",
            "good_type_id": "metals",
            "quantity": 1,
        })
        self.assertEqual(purchased["result"]["side"], "buy")
        self.assertEqual(purchased["state"]["player"]["goods"]["metals"], 1.0)

    def test_browser_move_is_physical_and_wait_uses_world_clock(self) -> None:
        moved = self._post({"command_id": "move-1", "action": "move", "destination_id": "royal-exchange"})
        self.assertEqual(moved["state"]["player"]["location_id"], "shop")
        self.assertEqual(moved["state"]["player"]["traveling_to"], "wall-street")
        for index in range(3):
            waited = self._post({"command_id": f"wait-{index}", "action": "wait", "hours": 1})
        self.assertEqual(waited["state"]["player"]["location_id"], "royal-exchange")
        self.assertEqual(waited["state"]["player"]["traveling_to"], "broad-street")

    def test_browser_can_board_the_canonical_bidirectional_ferry(self) -> None:
        world = build_street_world(seed=35).world
        world.actors["merchant"].location_id = "dock"
        world.actors["merchant"].schedule = []
        world.transport_assets["brooklyn-ferry"].location_id = "dock"
        server = create_server(world=world, port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(
                base + "/api/command",
                data=json.dumps({
                    "command_id": "ferry-1",
                    "action": "board",
                    "asset_id": "brooklyn-ferry",
                    "destination_id": "brooklyn-landing",
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                boarded = json.loads(response.read())
            self.assertEqual(boarded["state"]["player"]["traveling_to"], "brooklyn-landing")
            duration = boarded["result"]["duration_hours"]
            request = Request(
                base + "/api/command",
                data=json.dumps({"command_id": "ferry-wait", "action": "wait", "hours": duration}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                arrived = json.loads(response.read())
            self.assertEqual(arrived["state"]["player"]["location_id"], "brooklyn-landing")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_concurrent_duplicate_commands_execute_once(self) -> None:
        body = {
            "command_id": "concurrent-buy",
            "action": "purchase",
            "market_id": "shop-market",
            "good_type_id": "metals",
            "quantity": 1,
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(self._post, (body, body)))
        self.assertEqual(responses[0]["result"], responses[1]["result"])
        self.assertEqual(responses[0]["state"]["player"]["goods"]["metals"], 1.0)
        self.assertEqual(responses[0]["state"]["event_count"], responses[1]["state"]["event_count"])

    def test_command_id_reuse_with_different_arguments_is_rejected(self) -> None:
        self._post({
            "command_id": "conflicting-command",
            "action": "inspect",
            "object_id": "shop-counter",
        })
        request = Request(
            self.base + "/api/command",
            data=json.dumps({
                "command_id": "conflicting-command",
                "action": "inspect",
                "object_id": "tavern-ledger",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)

    def test_browser_save_reload_and_restart_controls_use_canonical_world(self) -> None:
        saved = self._post({"command_id": "save-1", "action": "save"})
        self.assertEqual(saved["result"]["schema_version"], 2)
        moved = self._post({"command_id": "move-before-reload", "action": "move", "destination_id": "royal-exchange"})
        self.assertEqual(moved["state"]["player"]["traveling_to"], "wall-street")
        reloaded = self._post({"command_id": "reload-1", "action": "reload"})
        self.assertFalse(reloaded["state"]["player"]["traveling_to"])
        restarted = self._post({"command_id": "restart-1", "action": "restart"})
        self.assertEqual(restarted["state"]["player"]["location_id"], "shop")


if __name__ == "__main__":
    unittest.main()
