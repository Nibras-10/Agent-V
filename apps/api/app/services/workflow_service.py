import uuid
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.entities import User, Conversation, SupportTicket, Message
from app.repositories.ticket_repo import TicketRepository, ConversationRepository
from app.repositories.run_repo import AgentRunRepository
from app.repositories.audit_repo import AuditRepository
from app.agents.graph import build_support_graph
from app.agents.state import SupportState
from app.observability.logging import logger


class WorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ticket_repo = TicketRepository(db)
        self.conv_repo = ConversationRepository(db)
        self.run_repo = AgentRunRepository(db)
        self.audit_repo = AuditRepository(db)

    async def handle_customer_message(
        self,
        conversation_id: str,
        content: str,
        user: User,
    ) -> Dict[str, Any]:
        conv = await self.conv_repo.get_by_id(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")

        ticket = await self.ticket_repo.get_by_id(conv.ticket_id, load_conversations=False)
        if not ticket:
            raise ValueError(f"Associated ticket {conv.ticket_id} not found")

        if user.role != "customer" or not user.customer_id or user.customer_id != ticket.customer_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authenticated customer does not own this ticket")

        # 1. Record customer message
        customer_msg = await self.conv_repo.add_message(
            conversation_id=conversation_id,
            actor_type="customer",
            content=content,
            actor_id=user.id,
        )

        # 2. Initialize Agent Run record
        agent_run = await self.run_repo.create_run(ticket_id=ticket.id)

        # 3. Build state for LangGraph
        initial_state: SupportState = {
            "run_id": agent_run.id,
            "conversation_id": conversation_id,
            "ticket_id": ticket.id,
            "authenticated_actor_id": user.id,
            "customer_id": user.customer_id,
            "messages": [
                {"role": m.actor_type, "content": m.content}
                for m in conv.messages
            ] + [{"role": "customer", "content": content}],
            "retry_count": 0,
            "tool_call_count": 0,
            "llm_call_count": 0,
            "token_usage": {"total_tokens": 0},
            "status": "RUNNING",
        }

        # 4. Compile and invoke graph
        graph = build_support_graph(self.db)
        final_state = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": f"thread_{agent_run.id}"}},
        )

        final_response_text = final_state.get(
            "final_response",
            "Thank you for contacting customer support. We are reviewing your inquiry.",
        )

        # 5. Persist agent reply message
        agent_msg = await self.conv_repo.add_message(
            conversation_id=conversation_id,
            actor_type="agent",
            content=final_response_text,
            actor_id=None,
        )

        # 6. Update agent run record
        final_status = final_state.get("status", "COMPLETED")
        await self.run_repo.update_run(
            run_id=agent_run.id,
            status=final_status,
            retry_count=final_state.get("retry_count", 0),
            token_counts=final_state.get("token_usage", {}),
        )

        if final_status == "WAITING_FOR_APPROVAL":
            await self.ticket_repo.update_status(ticket.id, "pending_approval")
        elif final_status == "HANDED_OFF":
            await self.ticket_repo.update_status(ticket.id, "handed_off")

        # 7. Audit log event
        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=user.id,
            actor_type="customer",
            event_type="MESSAGE_PROCESSED",
            resource_type="conversation",
            resource_id=conversation_id,
            ticket_id=ticket.id,
            metadata={"status": final_status, "intent": final_state.get("intent")},
        )

        return {
            "conversation_id": conversation_id,
            "ticket_id": ticket.id,
            "customer_message": customer_msg,
            "agent_message": agent_msg,
            "workflow_status": final_status,
            "intent": final_state.get("intent"),
            "approval_id": final_state.get("approval_id"),
        }
