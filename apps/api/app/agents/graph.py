from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import SupportState
from app.agents.nodes.nodes import SupportWorkflowNodes
from app.agents.checkpointer import get_checkpointer


_memory_checkpointer = MemorySaver()


def route_after_triage(state: SupportState) -> Literal["retrieve_context", "handoff", "finalize"]:
    status = state.get("status")
    if status == "HANDED_OFF":
        return "handoff"
    intent = state.get("intent")
    if intent == "injection_attempt":
        return "finalize"
    return "retrieve_context"


def route_after_resolution(state: SupportState) -> Literal["policy_check", "handoff", "finalize"]:
    status = state.get("status")
    if status == "HANDED_OFF":
        return "handoff"
    if status == "WAITING_FOR_USER":
        return "finalize"

    proposed = state.get("proposed_action")
    if proposed and proposed.get("action_type") in ["refund", "cancellation", "contact_update"]:
        return "policy_check"

    return "finalize"


def route_after_policy(state: SupportState) -> Literal["approval_interrupt", "draft_response", "handoff", "finalize"]:
    status = state.get("status")
    if status == "HANDED_OFF":
        return "handoff"
    if status == "WAITING_FOR_APPROVAL":
        return "approval_interrupt"
    if state.get("action_result"):
        return "draft_response"
    return "finalize"


def route_after_approval(state: SupportState) -> Literal["execute_action", "finalize"]:
    if state.get("approval_decision") == "APPROVE":
        return "execute_action"
    return "finalize"


def build_support_graph(db: AsyncSession, checkpointer: BaseCheckpointSaver | None = None):
    workflow_nodes = SupportWorkflowNodes(db)
    builder = StateGraph(SupportState)

    # 1. Add all nodes
    builder.add_node("ingest_request", workflow_nodes.ingest_request)
    builder.add_node("triage", workflow_nodes.triage)
    builder.add_node("retrieve_context", workflow_nodes.retrieve_context)
    builder.add_node("compose_resolution", workflow_nodes.compose_resolution)
    builder.add_node("policy_check", workflow_nodes.policy_check)
    builder.add_node("approval_interrupt", workflow_nodes.approval_interrupt)
    builder.add_node("execute_action", workflow_nodes.execute_action)
    builder.add_node("draft_response", workflow_nodes.draft_response)
    builder.add_node("handoff", workflow_nodes.handoff)
    builder.add_node("finalize", workflow_nodes.finalize)

    # 2. Add edges
    builder.add_edge(START, "ingest_request")
    builder.add_edge("ingest_request", "triage")

    # Conditional after triage
    builder.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "retrieve_context": "retrieve_context",
            "handoff": "handoff",
            "finalize": "finalize",
        },
    )

    # Context retrieval always proceeds to resolution composition
    builder.add_edge("retrieve_context", "compose_resolution")

    # Conditional after resolution composition
    builder.add_conditional_edges(
        "compose_resolution",
        route_after_resolution,
        {
            "policy_check": "policy_check",
            "handoff": "handoff",
            "finalize": "finalize",
        },
    )

    # Conditional after policy check
    builder.add_conditional_edges(
        "policy_check",
        route_after_policy,
        {
            "approval_interrupt": "approval_interrupt",
            "draft_response": "draft_response",
            "handoff": "handoff",
            "finalize": "finalize",
        },
    )

    builder.add_conditional_edges(
        "approval_interrupt",
        route_after_approval,
        {
            "execute_action": "execute_action",
            "finalize": "finalize",
        },
    )

    # Execution flow (when resumed after approval)
    builder.add_edge("execute_action", "draft_response")
    builder.add_edge("draft_response", "finalize")
    builder.add_edge("handoff", "finalize")
    builder.add_edge("finalize", END)

    if checkpointer is None:
        checkpointer = get_checkpointer() or _memory_checkpointer

    return builder.compile(checkpointer=checkpointer)
