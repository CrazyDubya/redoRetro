"""The Insurance Game underwriting and claims kernel."""

from __future__ import annotations

from datetime import timedelta
import math

from .model import Business, CausalEvent, InsuranceClaim, InsurancePolicy, World, require_finite


def record_loss(
    world: World,
    subject_id: str,
    *,
    loss_kind: str,
    covered_risk: str,
    location_id: str,
    verified_loss_amount: float,
    description: str | None = None,
    causes: tuple[str, ...] = (),
) -> CausalEvent:
    """Register an authoritative, typed loss for later claims assessment.

    Insurance claims may only reference losses created through this gateway.
    A normal causal event is evidence about the world, but is not by itself an
    assessed monetary loss.  Keeping that distinction prevents policy, chat,
    payment, and movement events from being turned into arbitrary payouts.
    """
    _money_holder(world, subject_id)
    if location_id not in world.places:
        raise KeyError(location_id)
    if not isinstance(loss_kind, str) or not loss_kind.strip():
        raise ValueError("loss kind must be non-empty")
    if not isinstance(covered_risk, str) or not covered_risk.strip():
        raise ValueError("covered risk must be non-empty")
    require_finite(verified_loss_amount, "verified loss amount")
    if verified_loss_amount <= 0:
        raise ValueError("verified loss amount must be positive")
    event = world.record(
        "loss_verified",
        description or f"{subject_id} suffered a verified {loss_kind} loss",
        actors=[subject_id],
        entities=[subject_id, location_id],
        causes=causes,
        data={
            "loss_kind": loss_kind,
            "covered_risk": covered_risk,
            "loss_location_id": location_id,
            "verified_loss_amount": verified_loss_amount,
            "authority": "canonical-loss-registry",
        },
    )
    world.runtime.setdefault("verified_loss_event_ids", set()).add(event.id)
    return event


def _money_holder(world: World, holder_id: str):
    holder = world.actors.get(holder_id) or world.businesses.get(holder_id) or world.households.get(holder_id)
    if holder is None:
        raise KeyError(f"unknown money holder {holder_id!r}")
    return holder


def _insurer(world: World, insurer_id: str) -> Business:
    insurer = world.businesses.get(insurer_id)
    if insurer is None or insurer.kind != "insurer":
        raise ValueError(f"{insurer_id} is not an insurer business")
    return insurer


def issue_policy(
    world: World,
    insurer_id: str,
    policyholder_id: str,
    *,
    line: str,
    region_id: str,
    premium: float,
    coverage_limit: float,
    deductible: float = 0.0,
    term_days: int = 30,
    policy_id: str | None = None,
) -> InsurancePolicy:
    _insurer(world, insurer_id)
    _money_holder(world, policyholder_id)
    if region_id not in world.places:
        raise KeyError(region_id)
    require_finite(term_days, "insurance term days")
    if (
        not line
        or not all(math.isfinite(value) for value in (premium, coverage_limit, deductible))
        or premium <= 0
        or coverage_limit <= 0
        or deductible < 0
        or deductible >= coverage_limit
        or term_days <= 0
    ):
        raise ValueError("invalid insurance terms")
    policy_id = policy_id or f"policy-{len(world.insurance_policies) + 1}"
    if policy_id in world.insurance_policies:
        raise ValueError(f"insurance policy {policy_id} already exists")
    payment = world.pay(policyholder_id, insurer_id, premium, reason=f"premium for {policy_id}")
    policy = InsurancePolicy(
        id=policy_id,
        insurer_id=insurer_id,
        policyholder_id=policyholder_id,
        line=line,
        region_id=region_id,
        premium=premium,
        coverage_limit=coverage_limit,
        deductible=deductible,
        issued_at=world.now,
        expires_at=world.now + timedelta(days=term_days),
    )
    world.add(policy)
    world.record(
        "policy_issued",
        f"{insurer_id} insured {policyholder_id} for {line}",
        actors=[insurer_id, policyholder_id],
        entities=[policy.id, region_id],
        causes=[payment.id],
        data={"line": line, "premium": premium, "coverage_limit": coverage_limit, "deductible": deductible},
    )
    return policy


def file_claim(world: World, policy_id: str, *, loss_event_id: str, loss_amount: float, claim_id: str | None = None) -> InsuranceClaim:
    policy = world.insurance_policies[policy_id]
    if policy.status != "active":
        raise ValueError("policy is not active")
    event = next((event for event in world.events if event.id == loss_event_id), None)
    if event is None:
        raise KeyError(loss_event_id)
    if loss_event_id not in world.runtime.get("verified_loss_event_ids", set()) or event.kind != "loss_verified":
        raise ValueError("claim must reference an authoritative verified loss")
    loss_kind = event.data.get("loss_kind")
    if not isinstance(loss_kind, str) or not loss_kind.strip():
        raise ValueError("loss event must declare an explicit loss kind")
    if event.data.get("covered_risk") != policy.line:
        raise ValueError("loss event is not for the insured risk")
    if event.at < policy.issued_at or event.at > policy.expires_at or event.at > world.now:
        raise ValueError("loss did not occur during the policy coverage period")
    if policy.policyholder_id not in event.actors and policy.policyholder_id not in event.entities:
        raise ValueError("loss event is not linked to the policyholder")
    location_id = event.data.get("loss_location_id", event.data.get("location_id"))
    if location_id is None:
        location_id = next((entity_id for entity_id in event.entities if entity_id in world.places), None)
    if location_id is None:
        raise ValueError("loss event has no authoritative location")
    if location_id != policy.region_id:
        raise ValueError("loss event occurred outside the insured region")
    verified_loss = event.data.get("verified_loss_amount")
    if verified_loss is None:
        raise ValueError("loss event has no verified loss amount")
    require_finite(verified_loss, "verified loss amount")
    if verified_loss <= 0 or loss_amount > verified_loss + 1e-9:
        raise ValueError("claim exceeds the verified loss")
    require_finite(loss_amount, "loss amount")
    if loss_amount <= 0:
        raise ValueError("loss must be positive")
    claim_id = claim_id or f"claim-{len(world.insurance_claims) + 1}"
    if claim_id in world.insurance_claims:
        raise ValueError(f"insurance claim {claim_id} already exists")
    if any(
        claim.policy_id == policy.id and claim.loss_event_id == loss_event_id
        for claim in world.insurance_claims.values()
    ):
        raise ValueError("a claim already exists for this loss under this policy")
    indemnity = min(max(0.0, loss_amount - policy.deductible), policy.coverage_limit)
    claim = InsuranceClaim(
        id=claim_id,
        policy_id=policy.id,
        loss_event_id=loss_event_id,
        loss_amount=loss_amount,
        indemnity=indemnity,
        filed_at=world.now,
    )
    world.add(claim)
    world.record(
        "claim_filed",
        f"{policy.policyholder_id} filed {claim.id} against {policy.id}",
        actors=[policy.policyholder_id, policy.insurer_id],
        entities=[claim.id, policy.id],
        causes=[loss_event_id],
        data={"loss_amount": loss_amount, "indemnity": indemnity},
    )
    return claim


def approve_claim(world: World, claim_id: str) -> float:
    claim = world.insurance_claims[claim_id]
    if claim.status != "filed":
        raise ValueError("claim is not awaiting assessment")
    claim.status = "approved" if claim.indemnity > 0 else "denied"
    policy = world.insurance_policies[claim.policy_id]
    world.record(
        "claim_assessed",
        f"{claim.id} was {claim.status}",
        actors=[policy.insurer_id, policy.policyholder_id],
        entities=[claim.id, policy.id],
        causes=[claim.loss_event_id],
        data={"indemnity": claim.indemnity},
    )
    return claim.indemnity


def settle_claim(world: World, claim_id: str) -> float:
    claim = world.insurance_claims[claim_id]
    if claim.status != "approved":
        raise ValueError("claim is not approved")
    policy = world.insurance_policies[claim.policy_id]
    if claim.indemnity <= 0:
        raise ValueError("approved claim has no indemnity")
    # Validate and move money before marking the claim paid. An insolvent
    # insurer leaves an auditable approved obligation rather than free money.
    payment = world.pay(policy.insurer_id, policy.policyholder_id, claim.indemnity, reason=f"settlement of {claim.id}")
    claim.status = "paid"
    claim.settled_at = world.now
    world.record(
        "claim_settled",
        f"{policy.insurer_id} paid {claim.id}",
        actors=[policy.insurer_id, policy.policyholder_id],
        entities=[claim.id, policy.id],
        causes=[payment.id, claim.loss_event_id],
        data={"amount": claim.indemnity},
    )
    return claim.indemnity


def insurer_exposure(world: World, insurer_id: str) -> dict[str, float]:
    _insurer(world, insurer_id)
    active = [policy for policy in world.insurance_policies.values() if policy.insurer_id == insurer_id and policy.status == "active" and world.now <= policy.expires_at]
    insured_policy_ids = {policy.id for policy in world.insurance_policies.values() if policy.insurer_id == insurer_id}
    open_claims = [
        claim
        for claim in world.insurance_claims.values()
        if claim.policy_id in insured_policy_ids and claim.status == "approved"
    ]
    return {
        "premium_income": sum(policy.premium for policy in active),
        "coverage_limit": sum(policy.coverage_limit for policy in active),
        "approved_claims": sum(claim.indemnity for claim in open_claims),
    }


def advance_claims(world: World) -> None:
    """Attempt payment of every approved claim during ordinary settlement."""
    for claim in world.insurance_claims.values():
        if claim.status != "approved":
            continue
        try:
            settle_claim(world, claim.id)
        except (KeyError, ValueError) as exc:
            world.record(
                "claim_payment_deferred",
                f"approved claim {claim.id} remains unpaid",
                entities=[claim.id, claim.policy_id],
                data={"amount": claim.indemnity, "reason": str(exc)},
            )
