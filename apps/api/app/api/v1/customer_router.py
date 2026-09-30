from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.entities import Customer, Subscription, Transaction, User

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("/me/overview")
async def get_customer_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "customer" or not current_user.customer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer account required")

    customer = await db.get(Customer, current_user.customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer profile not found")

    subscriptions = await db.scalars(
        select(Subscription)
        .where(Subscription.customer_id == customer.id)
        .order_by(Subscription.started_at.desc())
    )
    transactions = await db.scalars(
        select(Transaction)
        .where(Transaction.customer_id == customer.id)
        .order_by(Transaction.occurred_at.desc())
        .limit(8)
    )
    return {
        "customer": {"id": customer.id, "display_name": customer.display_name, "email": customer.email, "phone": customer.phone},
        "subscriptions": [
            {"id": sub.id, "plan": sub.plan, "status": sub.status, "started_at": sub.started_at, "cancel_at": sub.cancel_at}
            for sub in subscriptions
        ],
        "transactions": [
            {"id": txn.id, "amount_minor": txn.amount_minor, "currency": txn.currency, "status": txn.status,
             "refundable_minor": txn.refundable_minor, "occurred_at": txn.occurred_at}
            for txn in transactions
        ],
    }
