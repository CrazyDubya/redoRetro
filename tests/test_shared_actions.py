import unittest

from redos.actions import converse, deliver, inspect, move, purchase
from redos.model import Actor
from redos.simulation import tick
from redos.streets import build_street_world


class SharedActionTests(unittest.TestCase):
    def test_move_uses_the_same_embodied_route_for_a_caller(self) -> None:
        world = build_street_world(seed=21).world
        actor = Actor("walker", "Walker", "shop", money=500.0)
        world.add(actor)

        movement = move(world, actor.id, "royal-exchange")
        self.assertEqual(actor.location_id, "shop")
        self.assertIsNotNone(actor.traveling_to)
        tick(world, movement.duration_hours)
        tick(world, 2)
        self.assertEqual(actor.location_id, "royal-exchange")
        self.assertIsNone(actor.traveling_to)

    def test_inspection_requires_physical_presence(self) -> None:
        world = build_street_world(seed=22).world
        actor = Actor("visitor", "Visitor", "water-street")
        world.add(actor)

        with self.assertRaises(ValueError):
            inspect(world, actor.id, "shop-counter")
        actor.location_id = "shop"
        result = inspect(world, actor.id, "shop-counter")
        self.assertEqual(result["action"], "inspect")

    def test_conversation_requires_co_presence_but_preserves_information_kernel(self) -> None:
        world = build_street_world(seed=23).world
        speaker = Actor("speaker", "Speaker", "tavern")
        listener = Actor("listener", "Listener", "shop")
        world.add(speaker)
        world.add(listener)

        with self.assertRaises(ValueError):
            converse(world, speaker.id, listener.id, "seal", "the seal broke", truthful=False)
        listener.location_id = "tavern"
        statement = converse(world, speaker.id, listener.id, "seal", "the seal broke", truthful=False)
        self.assertFalse(statement.truthful)
        self.assertEqual(world.actors[listener.id].beliefs["seal"], "the seal broke")

    def test_purchase_uses_real_market_stock_and_delivery_uses_owned_lots(self) -> None:
        world = build_street_world(seed=24).world
        buyer = Actor("buyer", "Buyer", "shop", money=100_000.0)
        seller = Actor("seller", "Seller", "shop", money=100.0)
        world.add(buyer)
        world.add(seller)

        quote = purchase(world, buyer.id, "shop-market", "metals", 1.0)
        self.assertEqual(quote.side, "buy")
        self.assertAlmostEqual(world.quantity_held(buyer.id, "metals"), 1.0)

        before_events = len(world.events)
        world.create_lot("metals", 2.0, holder_id=seller.id, owner_id=seller.id, provenance=("seller-stock",))
        result = deliver(world, seller.id, "shop-market-cashier", "metals", 1.0)
        self.assertEqual(world.quantity_held("shop-market-cashier", "metals"), 1.0)
        self.assertEqual(world.quantity_held(seller.id, "metals"), 1.0)
        self.assertGreater(len(world.events), before_events)
        self.assertEqual(world.events[-1].kind, "delivery")
        self.assertTrue(result)

    def test_purchase_is_rejected_while_buyer_is_physically_traveling(self) -> None:
        world = build_street_world(seed=25).world
        actor = world.actors["merchant"]
        before_money = actor.money
        before_goods = world.quantity_held(actor.id, "metals")
        before_events = len(world.events)
        move(world, actor.id, "royal-exchange")

        with self.assertRaises(ValueError):
            purchase(world, actor.id, "shop-market", "metals", 1.0)

        self.assertEqual(actor.money, before_money)
        self.assertEqual(world.quantity_held(actor.id, "metals"), before_goods)
        self.assertEqual(len(world.events), before_events + 1)

    def test_rejected_second_move_preserves_original_destination_and_movement(self) -> None:
        world = build_street_world(seed=26).world
        actor = world.actors["merchant"]
        first = move(world, actor.id, "royal-exchange")
        before_event_number = world._event_number

        with self.assertRaises(ValueError):
            move(world, actor.id, "fly-market")

        self.assertEqual(actor.journey_destination_id, "royal-exchange")
        self.assertEqual(actor.traveling_to, first.destination_id)
        self.assertEqual(world._event_number, before_event_number)
        self.assertEqual(tuple(world.movements), (first.id,))


if __name__ == "__main__":
    unittest.main()
