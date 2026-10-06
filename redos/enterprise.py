"""Market, Cartels & Cutthroats, INTOPIA, and M.U.L.E. kernels."""

from __future__ import annotations

from .model import Business, Contract, World


def business_quote(world: World, business_id: str, market_id: str, good_type_id: str) -> float:
    business = world.businesses[business_id]
    market = world.markets[market_id]
    reference = market.fixed_prices[good_type_id]
    markup = business.price_markup.get(good_type_id, 0.0)
    advertising_effect = min(0.15, max(0.0, business.advertising) * 0.01)
    return round(reference * (1.0 + markup - advertising_effect), 2)


def compete(world: World, market_id: str, good_type_id: str) -> dict[str, float]:
    """Compute observable market share from actual offers and inventory."""
    market = world.markets[market_id]
    businesses = [business for business in world.businesses.values() if business.location_id == market.place_id and world.quantity_held(business.id, good_type_id) > 0]
    if not businesses:
        return {}
    weights = {}
    for business in businesses:
        price = business_quote(world, business.id, market_id, good_type_id)
        weights[business.id] = world.quantity_held(business.id, good_type_id) / max(price, 0.01)
    total = sum(weights.values())
    shares = {business_id: weight / total for business_id, weight in weights.items()}
    for business_id, share in shares.items():
        world.businesses[business_id].market_share[good_type_id] = share
    world.record("competition", f"firms competed for {good_type_id}", entities=[market_id, good_type_id], data={"shares": shares})
    return shares


def create_contract(
    world: World,
    seller_id: str,
    buyer_id: str,
    good_type_id: str,
    quantity: float,
    unit_price: float,
    *,
    origin_id: str,
    destination_id: str,
    due_days: int,
) -> Contract:
    if quantity <= 0 or unit_price <= 0 or due_days < 0:
        raise ValueError("invalid contract terms")
    world._event_number += 1
    contract = Contract(
        id=f"contract-{world._event_number}",
        seller_id=seller_id,
        buyer_id=buyer_id,
        good_type_id=good_type_id,
        quantity=quantity,
        unit_price=unit_price,
        origin_id=origin_id,
        destination_id=destination_id,
        due_day=(world.now - world.now.replace(hour=0, minute=0, second=0, microsecond=0)).days + due_days,
    )
    world.add(contract)
    world.record("contract_signed", f"{seller_id} contracted to supply {buyer_id}", actors=[seller_id, buyer_id], entities=[contract.id, good_type_id])
    return contract


def settle_contract(world: World, contract_id: str) -> None:
    contract = world.contracts[contract_id]
    if contract.status != "open":
        raise ValueError("contract is not open")
    seller = world.businesses[contract.seller_id]
    buyer = world.businesses[contract.buyer_id]
    if seller.location_id != contract.origin_id or buyer.location_id != contract.destination_id:
        raise ValueError("contract endpoints are not at their agreed locations")
    if world.quantity_held(seller.id, contract.good_type_id) < contract.quantity:
        raise ValueError("seller cannot fulfill contract")
    payment = world.pay(buyer.id, seller.id, contract.quantity * contract.unit_price, reason="business contract settlement")
    world.transfer_goods(contract.good_type_id, contract.quantity, from_holder=seller.id, to_holder=buyer.id, to_owner=buyer.id, causes=[payment.id, contract.id], reason="business contract delivery")
    contract.status = "settled"
    world.record("contract_settled", f"{contract.id} settled", actors=[seller.id, buyer.id], entities=[contract.id], causes=[payment.id])


def borrow(world: World, borrower_id: str, lender_id: str, amount: float) -> None:
    if amount <= 0:
        raise ValueError("loan must be positive")
    world.pay(lender_id, borrower_id, amount, reason="business loan")
    world.businesses[borrower_id].debt += amount
    world.record("loan", f"{borrower_id} borrowed from {lender_id}", actors=[borrower_id, lender_id], data={"amount": amount})


def repay(world: World, borrower_id: str, lender_id: str, amount: float) -> None:
    borrower = world.businesses[borrower_id]
    amount = min(amount, borrower.debt)
    if amount <= 0:
        return
    world.pay(borrower_id, lender_id, amount, reason="business loan repayment")
    borrower.debt -= amount
    world.record("loan_repayment", f"{borrower_id} repaid {lender_id}", actors=[borrower_id, lender_id], data={"amount": amount})


def invest_in_research(world: World, business_id: str, amount: float) -> None:
    if amount <= 0:
        raise ValueError("research investment must be positive")
    business = world.businesses[business_id]
    if business.cash < amount:
        raise ValueError("business cannot fund research")
    business.cash -= amount
    business.research += amount
    world.record("research", f"{business_id} invested in research", actors=[business_id], data={"amount": amount})


def mule_bid(world: World, buyer_id: str, seller_id: str, good_type_id: str, quantity: float, amount: float) -> None:
    """A scarcity bid: a buyer pays a seller for an actual lot."""
    if amount <= 0:
        raise ValueError("bid must be positive")
    world.pay(buyer_id, seller_id, amount, reason="scarcity auction bid")
    world.transfer_goods(good_type_id, quantity, from_holder=seller_id, to_holder=buyer_id, to_owner=buyer_id, reason="scarcity auction delivery")
    world.record("scarcity_auction", f"{buyer_id} acquired scarce {good_type_id}", actors=[buyer_id, seller_id], entities=[good_type_id], data={"quantity": quantity, "amount": amount})
