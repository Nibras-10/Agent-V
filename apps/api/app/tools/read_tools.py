from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.customer_repo import CustomerRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.transaction_repo import TransactionRepository
from app.repositories.ticket_repo import TicketRepository


class ReadTools:
    def __init__(self, db: AsyncSession, authenticated_customer_id: str):
        self.db = db
        self.customer_id = authenticated_customer_id
        self.customer_repo = CustomerRepository(db)
        self.sub_repo = SubscriptionRepository(db)
        self.txn_repo = TransactionRepository(db)
        self.ticket_repo = TicketRepository(db)

    async def get_customer_profile(self) -> Dict[str, Any]:
        """Retrieve authoritative customer profile. Scoped strictly to authenticated customer."""
        customer = await self.customer_repo.get_by_id(self.customer_id)
        if not customer:
            return {"error": "Customer profile not found"}
        return {
            "id": customer.id,
            "external_ref": customer.external_ref,
            "display_name": customer.display_name,
            "email": customer.email,
            "phone": customer.phone,
            "status": customer.status,
            "created_at": customer.created_at.isoformat(),
        }

    async def get_subscription(self) -> Dict[str, Any]:
        """Retrieve active subscription details for the customer."""
        sub = await self.sub_repo.get_active_by_customer(self.customer_id)
        if not sub:
            return {"subscription": None, "message": "No active subscription found"}
        return {
            "id": sub.id,
            "plan": sub.plan,
            "status": sub.status,
            "started_at": sub.started_at.isoformat(),
            "cancel_at": sub.cancel_at.isoformat() if sub.cancel_at else None,
            "version": sub.version,
        }

    async def list_recent_transactions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent transactions for customer with bounded size."""
        bounded_limit = min(max(1, limit), 10)
        txns = await self.txn_repo.list_recent(self.customer_id, limit=bounded_limit)
        return [
            {
                "id": t.id,
                "amount_minor": t.amount_minor,
                "currency": t.currency,
                "status": t.status,
                "occurred_at": t.occurred_at.isoformat(),
                "refundable_minor": t.refundable_minor,
                "version": t.version,
            }
            for t in txns
        ]

    async def get_ticket_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent support ticket summaries for customer."""
        bounded_limit = min(max(1, limit), 10)
        tickets = await self.ticket_repo.list_by_customer(self.customer_id, limit=bounded_limit)
        return [
            {
                "id": tk.id,
                "subject": tk.subject,
                "status": tk.status,
                "priority": tk.priority,
                "created_at": tk.created_at.isoformat(),
            }
            for tk in tickets
        ]
