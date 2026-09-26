from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import SupportState
from app.agents.model_adapter import (
    get_llm_adapter,
    TriageOutput,
    ResolutionOutput,
)
from app.agents.prompts.system_prompt import (
    SYSTEM_SECURITY_POLICY,
    TRIAGE_PROMPT,
    RESOLUTION_PROMPT,
)
from app.tools.read_tools import ReadTools
from app.tools.action_tools import ActionTools
from app.policies.refund_policy import RefundPolicy
from app.policies.cancellation_policy import CancellationPolicy
from app.policies.contact_policy import ContactPolicy
from app.schemas.actions import RefundProposalPayload, CancellationProposalPayload, ContactUpdatePayload
from app.core.config import settings
from app.observability.logging import logger


class SupportWorkflowNodes:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_adapter()

    async def ingest_request(self, state: SupportState) -> Dict[str, Any]:
        """Initialize run state, track budgets and timestamps."""
        return {
            "retry_count": state.get("retry_count", 0),
            "tool_call_count": state.get("tool_call_count", 0),
            "llm_call_count": state.get("llm_call_count", 0),
            "token_usage": state.get("token_usage", {"total_tokens": 0}),
            "status": state.get("status", "RUNNING"),
            "created_at": state.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def triage(self, state: SupportState) -> Dict[str, Any]:
        """Triage agent: classify intent/urgency/capability. Never writes or authorizes."""
        if state.get("status") == "HANDED_OFF":
            return {"status": "HANDED_OFF"}

        # Check budget limits
        if state.get("llm_call_count", 0) >= settings.MAX_LLM_CALLS_PER_RUN:
            return {"status": "HANDED_OFF", "last_error_code": "HANDOFF_LLM_BUDGET"}
        if state.get("token_usage", {}).get("total_tokens", 0) >= settings.MAX_TOTAL_TOKENS_PER_RUN:
            return {"status": "HANDED_OFF", "last_error_code": "TOKEN_BUDGET_EXCEEDED"}

        messages = state.get("messages", [])
        last_message = messages[-1]["content"] if messages else ""

        try:
            triage_res, tokens = await self.llm.generate_structured(
                system_prompt=f"{SYSTEM_SECURITY_POLICY}\n\n{TRIAGE_PROMPT}",
                user_prompt=f"Customer Inquiry: {last_message}",
                output_schema=TriageOutput,
            )
            total_tokens = state.get("token_usage", {}).get("total_tokens", 0) + tokens
            updates = {
                "intent": triage_res.intent,
                "confidence": triage_res.confidence,
                "llm_call_count": state.get("llm_call_count", 0) + 1,
                "token_usage": {"total_tokens": total_tokens},
                "status": "RUNNING",
            }
            if triage_res.intent == "injection_attempt":
                updates["final_response"] = (
                    "I cannot execute instructions that alter security boundaries or reveal internal systems."
                )
            return updates
        except Exception as e:
            logger.error(f"Triage error: {e}")
            retry_count = state.get("retry_count", 0) + 1
            if retry_count >= settings.MAX_AGENT_ATTEMPTS:
                return {
                    "status": "HANDED_OFF",
                    "retry_count": retry_count,
                    "last_error_code": "HANDOFF_LOOP_LIMIT",
                }
            return {
                "retry_count": retry_count,
                "last_error_code": "TRIAGE_FAILED",
            }

    async def retrieve_context(self, state: SupportState) -> Dict[str, Any]:
        """DB/Context agent: call constrained read tools for authenticated customer."""
        customer_id = state.get("customer_id", "")
        read_tools = ReadTools(self.db, customer_id)
        tool_calls = state.get("tool_call_count", 0)

        if tool_calls >= settings.MAX_TOOL_CALLS_PER_RUN:
            return {"status": "HANDED_OFF", "last_error_code": "TOOL_BUDGET_EXCEEDED"}

        intent = state.get("intent", "")
        retrieved: Dict[str, Any] = {}

        # Profile is always retrieved
        profile = await read_tools.get_customer_profile()
        retrieved["customer_profile"] = profile
        tool_calls += 1

        if intent in ["refund_request", "duplicate_incorrect_charge"]:
            txns = await read_tools.list_recent_transactions(limit=5)
            retrieved["recent_transactions"] = txns
            tool_calls += 1
        elif intent in ["cancel_subscription", "account_question"]:
            sub = await read_tools.get_subscription()
            retrieved["subscription"] = sub
            tool_calls += 1

        return {
            "retrieved_context": retrieved,
            "tool_call_count": tool_calls,
        }

    async def compose_resolution(self, state: SupportState) -> Dict[str, Any]:
        """Resolution agent: produce grounded response or typed action proposal."""
        if state.get("llm_call_count", 0) >= settings.MAX_LLM_CALLS_PER_RUN:
            return {"status": "HANDED_OFF", "last_error_code": "HANDOFF_LLM_BUDGET"}

        intent = state.get("intent", "")
        retrieved_context = state.get("retrieved_context", {})
        messages = state.get("messages", [])
        last_message = messages[-1]["content"] if messages else ""

        user_prompt = (
            f"Intent: {intent}\n"
            f"Customer message: {last_message}\n"
            f"Authoritative Context: {retrieved_context}"
        )

        try:
            res_output, tokens = await self.llm.generate_structured(
                system_prompt=f"{SYSTEM_SECURITY_POLICY}\n\n{RESOLUTION_PROMPT}",
                user_prompt=user_prompt,
                output_schema=ResolutionOutput,
            )
            total_tokens = state.get("token_usage", {}).get("total_tokens", 0) + tokens
            updates: Dict[str, Any] = {
                "llm_call_count": state.get("llm_call_count", 0) + 1,
                "token_usage": {"total_tokens": total_tokens},
                "final_response": res_output.response_text,
            }

            if res_output.needs_clarification:
                updates["status"] = "WAITING_FOR_USER"
                updates["clarification_question"] = res_output.clarification_question
            elif res_output.proposed_action:
                updates["proposed_action"] = res_output.proposed_action.model_dump()
                updates["risk_level"] = res_output.proposed_action.risk

            return updates
        except Exception as e:
            logger.error(f"Resolution error: {e}")
            retry_count = state.get("retry_count", 0) + 1
            if retry_count >= settings.MAX_AGENT_ATTEMPTS:
                return {
                    "status": "HANDED_OFF",
                    "retry_count": retry_count,
                    "last_error_code": "HANDOFF_LOOP_LIMIT",
                }
            return {
                "retry_count": retry_count,
                "last_error_code": "RESOLUTION_FAILED",
            }

    async def policy_check(self, state: SupportState) -> Dict[str, Any]:
        """Deterministic policy & risk engine. Enforces business rules and creates proposals."""
        proposed = state.get("proposed_action")
        if not proposed:
            return {"status": "RUNNING"}

        action_type = proposed.get("action_type")
        customer_id = state.get("customer_id", "")
        actor_id = state.get("authenticated_actor_id", "")
        ticket_id = state.get("ticket_id", "")
        run_id = state.get("run_id", "")

        action_tools = ActionTools(self.db, actor_id, customer_id, ticket_id, run_id)

        if action_type == "refund":
            params = proposed.get("parameters", {})
            txn_id = params.get("transaction_id", "")
            amount_minor = params.get("amount_minor", 0)
            reason = proposed.get("reason", "Customer requested refund")
            currency = params.get("currency", "USD")

            # Check if this transaction exists in customer's recent transactions
            txns = state.get("retrieved_context", {}).get("recent_transactions", [])
            target_txn = next((t for t in txns if t["id"] == txn_id), None)
            if not target_txn and txns:
                # Use the most recent transaction for refund if LLM passed a generic id
                txn_id = txns[0]["id"]
                amount_minor = min(amount_minor or 5000, txns[0]["refundable_minor"])

            proposal_res = await action_tools.create_refund_proposal(
                transaction_id=txn_id,
                amount_minor=amount_minor,
                reason=reason,
                currency=currency,
            )

            if not proposal_res.get("success"):
                return {
                    "status": "HANDED_OFF",
                    "last_error_code": f"POLICY_DENIED_{proposal_res.get('reason_codes')}",
                    "final_response": "Your refund request could not be processed according to our policy and has been forwarded to human support.",
                }

            return {
                "approval_id": proposal_res["approval_id"],
                "risk_level": "HIGH",
                "status": "WAITING_FOR_APPROVAL",
                "final_response": "A refund proposal has been generated and submitted for human reviewer approval.",
            }

        elif action_type == "cancellation":
            params = proposed.get("parameters", {})
            sub_id = params.get("subscription_id", "")
            reason = proposed.get("reason", "Customer requested subscription cancellation")

            sub = state.get("retrieved_context", {}).get("subscription")
            if sub and sub.get("id"):
                sub_id = sub["id"]

            proposal_res = await action_tools.create_cancellation_proposal(
                subscription_id=sub_id,
                reason=reason,
                cancel_at_period_end=params.get("cancel_at_period_end", True),
            )

            if not proposal_res.get("success"):
                return {
                    "status": "HANDED_OFF",
                    "last_error_code": f"POLICY_DENIED_{proposal_res.get('reason_codes')}",
                    "final_response": "Your cancellation request could not be processed according to policy and has been forwarded to human support.",
                }

            return {
                "approval_id": proposal_res["approval_id"],
                "risk_level": "HIGH",
                "status": "WAITING_FOR_APPROVAL",
                "final_response": "A cancellation proposal has been generated and submitted for human reviewer approval.",
            }

        elif action_type == "contact_update":
            # Low risk: allowlisted fields directly executable
            params = proposed.get("parameters", {})
            exec_res = await action_tools.update_contact_details(
                display_name=params.get("display_name"),
                phone=params.get("phone"),
            )
            return {
                "action_result": exec_res.model_dump(),
                "risk_level": "LOW",
                "status": "RUNNING",
                "final_response": exec_res.message,
            }

        return {"status": "RUNNING"}

    async def approval_interrupt(self, state: SupportState) -> Dict[str, Any]:
        """Interrupt point for Human-In-The-Loop. Graph pauses here until reviewed."""
        # If approval_id is set and status is WAITING_FOR_APPROVAL, this node pauses execution
        return {
            "status": "WAITING_FOR_APPROVAL",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def execute_action(self, state: SupportState) -> Dict[str, Any]:
        """Execute only an authorized action after revalidation and version checks."""
        approval_id = state.get("approval_id")
        if not approval_id:
            return {"status": "FAILED", "last_error_code": "NO_APPROVAL_ID"}

        customer_id = state.get("customer_id", "")
        actor_id = state.get("authenticated_actor_id", "")
        ticket_id = state.get("ticket_id", "")
        run_id = state.get("run_id", "")

        action_tools = ActionTools(self.db, actor_id, customer_id, ticket_id, run_id)
        proposed = state.get("proposed_action", {})
        action_type = proposed.get("action_type")

        if action_type == "refund":
            result = await action_tools.execute_approved_refund(approval_id)
        elif action_type == "cancellation":
            result = await action_tools.execute_approved_cancellation(approval_id)
        else:
            return {"status": "FAILED", "last_error_code": "UNSUPPORTED_ACTION"}

        if not result.success:
            return {
                "status": "FAILED",
                "action_result": result.model_dump(),
                "last_error_code": "EXECUTION_FAILED",
                "final_response": f"Execution failed: {result.message}",
            }

        return {
            "status": "RUNNING",
            "action_result": result.model_dump(),
            "final_response": result.message,
        }

    async def draft_response(self, state: SupportState) -> Dict[str, Any]:
        """Finalize customer message grounded on executed action result or answer."""
        if state.get("action_result"):
            action_res = state["action_result"]
            if action_res.get("status") == "SUCCESS":
                return {
                    "final_response": f"Action completed successfully: {action_res.get('message')}",
                    "status": "COMPLETED",
                }
        return {"status": "COMPLETED"}

    async def handoff(self, state: SupportState) -> Dict[str, Any]:
        """Enqueue ticket for human support and terminate workflow."""
        customer_id = state.get("customer_id", "")
        actor_id = state.get("authenticated_actor_id", "")
        ticket_id = state.get("ticket_id", "")
        run_id = state.get("run_id", "")
        reason = state.get("last_error_code", "UNKNOWN_ERROR")

        action_tools = ActionTools(self.db, actor_id, customer_id, ticket_id, run_id)
        summary = f"Workflow handed off to human agent. Reason: {reason}. Status: {state.get('status')}"
        await action_tools.enqueue_human_handoff(reason_code=reason, summary=summary)

        return {
            "status": "HANDED_OFF",
            "final_response": "Your request has been routed to our human support team for manual assistance.",
        }

    async def finalize(self, state: SupportState) -> Dict[str, Any]:
        """Finalize state and record completion timestamp."""
        status = state.get("status", "COMPLETED")
        if status not in ["WAITING_FOR_APPROVAL", "WAITING_FOR_USER", "HANDED_OFF"]:
            status = "COMPLETED"
        return {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
