import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.graph import build_support_graph
from app.agents.state import SupportState
from app.core.config import settings


@pytest.mark.asyncio
async def test_graph_read_only_flow(db_session: AsyncSession, seed_test_data):
    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_test_1",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "messages": [{"role": "customer", "content": "What is my subscription status?"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_test_1"}})
    assert result["status"] == "COMPLETED"
    assert result["intent"] == "account_question"
    assert "retrieved_context" in result
    assert "subscription" in result["retrieved_context"]
    assert result.get("proposed_action") is None


@pytest.mark.asyncio
async def test_graph_refund_requires_approval(db_session: AsyncSession, seed_test_data):
    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_test_2",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "messages": [{"role": "customer", "content": "I was charged twice for transaction txn_alice_1, please refund me"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_test_2"}})
    assert result["status"] == "WAITING_FOR_APPROVAL"
    assert result["risk_level"] == "HIGH"
    assert result.get("approval_id") is not None
    assert result["proposed_action"]["action_type"] == "refund"


@pytest.mark.asyncio
async def test_graph_loop_limit_handoff(db_session: AsyncSession, seed_test_data, monkeypatch):
    # Simulate a node error exceeding retry attempts
    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_test_3",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "retry_count": settings.MAX_AGENT_ATTEMPTS,  # Already at max attempts
        "status": "HANDED_OFF",
        "last_error_code": "HANDOFF_LOOP_LIMIT",
        "messages": [{"role": "customer", "content": "Trigger failure"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_test_3"}})
    assert result["status"] == "HANDED_OFF"
    assert "human support team" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_graph_token_budget_exceeded(db_session: AsyncSession, seed_test_data):
    graph = build_support_graph(db_session)
    state: SupportState = {
        "run_id": "run_test_4",
        "ticket_id": "ticket_alice_1",
        "authenticated_actor_id": "user_alice",
        "customer_id": "cust_alice",
        "token_usage": {"total_tokens": settings.MAX_TOTAL_TOKENS_PER_RUN + 100},
        "messages": [{"role": "customer", "content": "Hello"}],
    }
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "thread_test_4"}})
    assert result["status"] == "HANDED_OFF"
