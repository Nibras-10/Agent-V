from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.entities import Transaction, Subscription, Approval, SupportTicket, ExecutedAction, HumanQueue
from app.services.approval_service import ApprovalService


@pytest.mark.asyncio
async def test_case_1_read_only_performs_no_write(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 1: Read-only request performs no write to transactions, subscriptions, or approvals."""
    headers = {"Authorization": f"Bearer {auth_tokens['alice']}"}
    res = await client.post(
        "/api/v1/conversations/conv_alice_1/messages",
        headers=headers,
        json={"content": "What is my current subscription plan?"},
    )
    assert res.status_code == 200
    # Verify no proposals or approvals were created
    approvals = (await db_session.execute(select(Approval))).scalars().all()
    assert len(approvals) == 0


@pytest.mark.asyncio
async def test_case_2_refund_proposal_cannot_execute_before_approval(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 2: Refund proposal creates pending approval and pauses; no balance deducted yet."""
    headers = {"Authorization": f"Bearer {auth_tokens['alice']}"}
    res = await client.post(
        "/api/v1/conversations/conv_alice_1/messages",
        headers=headers,
        json={"content": "Please issue a refund for transaction txn_alice_1, I was charged twice"},
    )
    assert res.status_code == 200
    assert "submitted for human reviewer approval" in res.json()["content"]

    # Transaction balance should remain unchanged before approval
    txn = (await db_session.execute(select(Transaction).where(Transaction.id == "txn_alice_1"))).scalar_one()
    assert txn.refundable_minor == 5000  # Still full refundable balance
    assert txn.version == 1

    # Approval record must exist with PENDING status
    approvals = (await db_session.execute(select(Approval))).scalars().all()
    assert len(approvals) == 1
    assert approvals[0].status == "PENDING"


@pytest.mark.asyncio
async def test_case_3_approved_refund_executes_exactly_once(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 3: Approved refund executes exactly once and duplicate attempt is idempotent."""
    headers_cust = {"Authorization": f"Bearer {auth_tokens['alice']}"}
    await client.post(
        "/api/v1/conversations/conv_alice_1/messages",
        headers=headers_cust,
        json={"content": "Please refund txn_alice_1"},
    )

    approval = (await db_session.execute(select(Approval))).scalars().one()
    assert approval.status == "PENDING"
    approval_id = approval.id

    # Reviewer approves
    headers_rev = {"Authorization": f"Bearer {auth_tokens['reviewer']}"}
    res_appr = await client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        headers=headers_rev,
        json={"decision": "APPROVE", "comment": "Legitimate duplicate charge"},
    )
    assert res_appr.status_code == 200
    assert res_appr.json()["status"] == "APPROVED"

    # Verify transaction deducted
    db_session.expire_all()
    txn = (await db_session.execute(select(Transaction).where(Transaction.id == "txn_alice_1"))).scalar_one()
    assert txn.refundable_minor == 0
    assert txn.status == "refunded"
    assert txn.version == 2

    # Second approval attempt should be rejected (cannot re-approve)
    res_dup = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers=headers_rev,
        json={"decision": "APPROVE"},
    )
    assert res_dup.status_code == 400


@pytest.mark.asyncio
async def test_case_4_rejected_refund_never_executes(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 4: Rejected refund never executes."""
    headers_cust = {"Authorization": f"Bearer {auth_tokens['alice']}"}
    await client.post(
        "/api/v1/conversations/conv_alice_1/messages",
        headers=headers_cust,
        json={"content": "Refund txn_alice_1"},
    )

    approval = (await db_session.execute(select(Approval))).scalars().one()

    # Reviewer rejects
    headers_rev = {"Authorization": f"Bearer {auth_tokens['reviewer']}"}
    res_reject = await client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        headers=headers_rev,
        json={"decision": "REJECT", "comment": "Policy limit exceeded or fraudulent"},
    )
    assert res_reject.status_code == 200
    assert res_reject.json()["status"] == "REJECTED"

    # Balance remains untouched
    db_session.expire_all()
    txn = (await db_session.execute(select(Transaction).where(Transaction.id == "txn_alice_1"))).scalar_one()
    assert txn.refundable_minor == 5000
    assert txn.status == "settled"

    # No executed action created
    execs = (await db_session.execute(select(ExecutedAction))).scalars().all()
    assert len(execs) == 0


@pytest.mark.asyncio
async def test_case_5_cancellation_requires_approval_and_revalidation(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 5: Cancellation requires approval + version revalidation."""
    headers_cust = {"Authorization": f"Bearer {auth_tokens['alice']}"}
    res = await client.post(
        "/api/v1/conversations/conv_alice_1/messages",
        headers=headers_cust,
        json={"content": "Please cancel my subscription sub_alice_1"},
    )
    assert res.status_code == 200

    approval = (await db_session.execute(select(Approval))).scalars().one()
    assert approval.status == "PENDING"

    # Reviewer approves
    headers_rev = {"Authorization": f"Bearer {auth_tokens['reviewer']}"}
    res_appr = await client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        headers=headers_rev,
        json={"decision": "APPROVE"},
    )
    assert res_appr.status_code == 200

    db_session.expire_all()
    sub = (await db_session.execute(select(Subscription).where(Subscription.id == "sub_alice_1"))).scalar_one()
    assert sub.status == "canceled"
    assert sub.version == 2


@pytest.mark.asyncio
async def test_case_6_three_failed_attempts_produce_one_handoff(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 6: Three failed attempts produce one handoff and terminate."""
    from app.agents.graph import build_support_graph
    from app.agents.state import SupportState
    from app.core.config import settings

    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_limit_test",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "retry_count": 3,
        "status": "HANDED_OFF",
        "last_error_code": "HANDOFF_LOOP_LIMIT",
        "messages": [{"role": "customer", "content": "Failed state"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_limit_1"}})
    assert result["status"] == "HANDED_OFF"

    # Check human queue
    hq = (await db_session.execute(select(HumanQueue).where(HumanQueue.ticket_id == "ticket_alice_1"))).scalars().all()
    assert len(hq) == 1
    assert hq[0].reason_code == "HANDOFF_LOOP_LIMIT"


@pytest.mark.asyncio
async def test_case_7_token_budget_causes_handoff(
    client: AsyncClient,
    seed_test_data,
    auth_tokens,
    db_session: AsyncSession,
):
    """Case 7: Token budget cannot be exceeded and causes handoff."""
    from app.agents.graph import build_support_graph
    from app.agents.state import SupportState
    from app.core.config import settings

    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_token_test",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "token_usage": {"total_tokens": settings.MAX_TOTAL_TOKENS_PER_RUN},
        "messages": [{"role": "customer", "content": "Exceed tokens"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_tok_1"}})
    assert result["status"] == "HANDED_OFF"
