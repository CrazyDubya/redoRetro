import json
from threading import Thread
import unittest
from urllib.request import Request, urlopen

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
        self.assertIn("Redos — The Living Streets", page)
        self.assertEqual(state["player"]["id"], "merchant")
        self.assertIn("shop", {place["id"] for place in state["places"]})

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


if __name__ == "__main__":
    unittest.main()
