import unittest

from redos.harbor import build_harbor_world
from redos.model import Actor
from redos.runtime import run
from redos.simulation import tick
from redos.streets import RATZER_LOC_URL, RATZER_NYPL_URL, build_street_world, street_path
from redos.transport import board_passenger
from redos.vertical import default_dock_incident


class StreetSliceTests(unittest.TestCase):
    def test_bounded_historical_graph_is_canonical_and_traversable(self) -> None:
        world = build_street_world(seed=7).world
        district = world.runtime["street_district"]

        self.assertEqual(len(district["visitable_sites"]), 8)
        self.assertEqual(len(district["interior_sites"]), 4)
        self.assertTrue(set(district["interior_sites"]).issubset(district["visitable_sites"]))
        self.assertEqual(district["source"]["library_of_congress"], RATZER_LOC_URL)
        self.assertEqual(district["source"]["new_york_public_library"], RATZER_NYPL_URL)
        self.assertTrue(all(world.places[place_id].is_interior for place_id in district["interior_sites"]))

        path = street_path(world, "shop", "royal-exchange")
        self.assertTrue(path)
        self.assertTrue(set(route.id for route in path).issubset(district["street_route_ids"]))
        for route_id in district["street_route_ids"]:
            route = world.routes[route_id]
            reverse = next(
                (
                    candidate
                    for candidate in world.routes.values()
                    if candidate.origin_id == route.destination_id and candidate.destination_id == route.origin_id
                    and candidate.id in district["street_route_ids"]
                ),
                None,
            )
            self.assertIsNotNone(reverse, route_id)

    def test_ferry_can_carry_passengers_in_both_directions(self) -> None:
        world = build_harbor_world(seed=8).world
        services = set(world.runtime["passenger_services"])
        self.assertIn(("brooklyn-ferry", "brooklyn-landing", "dock"), services)
        self.assertIn(("brooklyn-ferry", "dock", "brooklyn-landing"), services)

        # Use a neutral rider so the harbor fixture's commuter schedule cannot
        # immediately book the return service during the same elapsed tick.
        outbound = Actor("outbound-passenger", "Outbound Passenger", "brooklyn-landing")
        world.add(outbound)
        outbound_movement = board_passenger(world, outbound.id, "brooklyn-ferry", "dock")
        tick(world, outbound_movement.duration_hours)
        self.assertEqual(outbound.location_id, "dock")
        self.assertEqual(world.transport_assets["brooklyn-ferry"].location_id, "dock")

        returner = Actor("return-passenger", "Return Passenger", "dock")
        world.add(returner)
        return_movement = board_passenger(world, returner.id, "brooklyn-ferry", "brooklyn-landing")
        tick(world, return_movement.duration_hours)
        self.assertEqual(returner.location_id, "brooklyn-landing")
        self.assertEqual(world.transport_assets["brooklyn-ferry"].location_id, "brooklyn-landing")

    def test_street_fixture_remains_livable_without_player_commands(self) -> None:
        state = build_street_world(seed=43)
        world = run(state.world, 30, external_events=(default_dock_incident(state),))

        self.assertTrue(any(event.kind == "incident" for event in world.events))
        self.assertGreater(sum(event.kind == "movement" for event in world.events), 20)
        self.assertGreater(sum(event.kind == "work" for event in world.events), 100)
        self.assertGreater(sum(event.kind == "meeting" for event in world.events), 20)
        beliefs = [
            actor.beliefs["dock-incident"]
            for actor in world.actors.values()
            if "dock-incident" in actor.beliefs
        ]
        self.assertGreaterEqual(len(beliefs), 2)
        self.assertGreaterEqual(len(set(beliefs)), 2)
        self.assertTrue(any(actor.location_id == "tavern" for actor in world.actors.values()))
        self.assertEqual(world.runtime["street_district"]["source"]["historical_scope"], "names and broad landmark relationships")


if __name__ == "__main__":
    unittest.main()
