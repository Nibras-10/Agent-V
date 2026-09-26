from datetime import datetime, timezone
import pytest
from app.models.entities import Transaction, Subscription, Customer
from app.policies.refund_policy import RefundPolicy
from app.policies.cancellation_policy import CancellationPolicy
from app.policies.contact_policy import ContactPolicy
from app.schemas.actions import (
    RefundProposalPayload,
    CancellationProposalPayload,
    ContactUpdatePayload,
)


def test_refund_policy_valid():
    txn = Transaction(
        id="txn_1",
        customer_id="cust_1",
        amount_minor=5000,
        currency="USD",
        status="settled",
        refundable_minor=5000,
        version=1,
        occurred_at=datetime.now(timezone.utc),
    )
    proposal = RefundProposalPayload(
        transaction_id="txn_1",
        customer_id="cust_1",
        amount_minor=5000,
        currency="USD",
        reason="Duplicate charge",
    )
    decision = RefundPolicy.evaluate("cust_1", txn, proposal)
    assert decision.allowed is True
    assert decision.approval_required is True
    assert decision.risk == "HIGH"
    assert "ELIGIBLE_FOR_REVIEW" in decision.reason_codes


def test_refund_policy_customer_mismatch():
    txn = Transaction(
        id="txn_1",
        customer_id="cust_other",
        amount_minor=5000,
        currency="USD",
        status="settled",
        refundable_minor=5000,
        version=1,
        occurred_at=datetime.now(timezone.utc),
    )
    proposal = RefundProposalPayload(
        transaction_id="txn_1",
        customer_id="cust_1",
        amount_minor=5000,
        currency="USD",
        reason="Attempting to refund someone else's txn",
    )
    decision = RefundPolicy.evaluate("cust_1", txn, proposal)
    assert decision.allowed is False
    assert "CUSTOMER_MISMATCH" in decision.reason_codes


def test_refund_policy_exceeds_refundable():
    txn = Transaction(
        id="txn_1",
        customer_id="cust_1",
        amount_minor=5000,
        currency="USD",
        status="settled",
        refundable_minor=2000,  # Only 2000 refundable
        version=1,
        occurred_at=datetime.now(timezone.utc),
    )
    proposal = RefundProposalPayload(
        transaction_id="txn_1",
        customer_id="cust_1",
        amount_minor=5000,
        currency="USD",
        reason="Excess refund",
    )
    decision = RefundPolicy.evaluate("cust_1", txn, proposal)
    assert decision.allowed is False
    assert "AMOUNT_EXCEEDS_REFUNDABLE_BALANCE" in decision.reason_codes


def test_cancellation_policy_active():
    sub = Subscription(
        id="sub_1",
        customer_id="cust_1",
        plan="Pro",
        status="active",
        version=1,
        started_at=datetime.now(timezone.utc),
    )
    proposal = CancellationProposalPayload(
        subscription_id="sub_1",
        customer_id="cust_1",
        reason="No longer needed",
    )
    decision = CancellationPolicy.evaluate("cust_1", sub, proposal)
    assert decision.allowed is True
    assert decision.approval_required is True
    assert decision.risk == "HIGH"


def test_cancellation_policy_already_canceled():
    sub = Subscription(
        id="sub_1",
        customer_id="cust_1",
        plan="Pro",
        status="canceled",
        version=2,
        started_at=datetime.now(timezone.utc),
    )
    proposal = CancellationProposalPayload(
        subscription_id="sub_1",
        customer_id="cust_1",
        reason="Cancel again",
    )
    decision = CancellationPolicy.evaluate("cust_1", sub, proposal)
    assert decision.allowed is False
    assert "SUBSCRIPTION_NOT_ACTIVE" in decision.reason_codes


def test_contact_policy_allowlisted():
    cust = Customer(
        id="cust_1",
        external_ref="ext_1",
        display_name="Old Name",
        email="cust@test.com",
        phone="+1-555-0000",
        status="active",
    )
    payload = ContactUpdatePayload(customer_id="cust_1", display_name="New Name", phone="+1-555-1111")
    decision = ContactPolicy.evaluate("cust_1", cust, payload)
    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.risk == "LOW"
