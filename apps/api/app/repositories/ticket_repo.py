from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.entities import SupportTicket, Conversation, Message


class TicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_ticket(self, customer_id: str, subject: str, priority: str = "normal") -> SupportTicket:
        ticket = SupportTicket(
            customer_id=customer_id,
            subject=subject,
            priority=priority,
            status="open",
        )
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: str, load_conversations: bool = True) -> Optional[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
        if load_conversations:
            stmt = stmt.options(
                selectinload(SupportTicket.conversations).selectinload(Conversation.messages)
            )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_customer(self, customer_id: str, limit: int = 20) -> List[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.customer_id == customer_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def update_status(self, ticket_id: str, status: str) -> Optional[SupportTicket]:
        ticket = await self.get_by_id(ticket_id, load_conversations=False)
        if not ticket:
            return None
        ticket.status = status
        ticket.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(self, ticket_id: str, channel: str = "web") -> Conversation:
        conv = Conversation(ticket_id=ticket_id, channel=channel)
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def add_message(
        self,
        conversation_id: str,
        actor_type: str,
        content: str,
        actor_id: Optional[str] = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            content=content,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg
