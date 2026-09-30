"""Add repeatable synthetic customer fixtures to the explicitly enabled demo deployment."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text

from app.auth.security import hash_password
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.models.entities import (
    Conversation,
    Customer,
    HumanQueue,
    Message,
    Subscription,
    SupportTicket,
    Transaction,
    User,
)


async def seed_demo_data() -> None:
    if os.getenv("SEED_DEMO_DATA", "").strip().lower() != "true":
        raise SystemExit("Set SEED_DEMO_DATA=true to enable production demo fixtures.")
    if not settings.is_production:
        raise SystemExit("Demo fixtures are restricted to APP_ENV=production.")
    if not settings.DATABASE_URL.startswith("postgresql+asyncpg://"):
        raise SystemExit("Demo fixtures require the configured production PostgreSQL database.")

    password = os.getenv("DEMO_CUSTOMER_PASSWORD", "")
    if len(password) < 16:
        raise SystemExit("Set DEMO_CUSTOMER_PASSWORD to a demo-only password of at least 16 characters.")

    now = datetime.now(timezone.utc)
    customers = [
        Customer(
            id="demo_customer_alice_001", external_ref="DEMO-ACCT-ALICE-001",
            display_name="Demo Customer Alice", email="demo.alice@example.com",
            phone="+1-202-555-0101", status="active", created_at=now - timedelta(days=90),
        ),
        Customer(
            id="demo_customer_jordan_002", external_ref="DEMO-ACCT-JORDAN-002",
            display_name="Demo Customer Jordan", email="demo.jordan@example.com",
            phone="+1-202-555-0102", status="active", created_at=now - timedelta(days=45),
        ),
    ]
    users = [
        User(
            id="demo_user_alice_001", email="demo.alice@example.com", password_hash=hash_password(password),
            role="customer", customer_id=customers[0].id, is_active=True, is_verified=True,
            token_version=0, created_at=now - timedelta(days=90),
        ),
        User(
            id="demo_user_jordan_002", email="demo.jordan@example.com", password_hash=hash_password(password),
            role="customer", customer_id=customers[1].id, is_active=True, is_verified=True,
            token_version=0, created_at=now - timedelta(days=45),
        ),
    ]
    tickets = [
        SupportTicket(
            id="demo_ticket_billing_001", customer_id=customers[0].id,
            subject="Question about a recent demo charge", priority="normal", status="open",
            created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2),
        ),
        SupportTicket(
            id="demo_ticket_handoff_002", customer_id=customers[0].id,
            subject="Demo request to speak with support", priority="normal", status="handed_off",
            created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1),
        ),
        SupportTicket(
            id="demo_ticket_subscription_003", customer_id=customers[1].id,
            subject="Help with a paused demo subscription", priority="normal", status="open",
            created_at=now - timedelta(days=1), updated_at=now - timedelta(days=1),
        ),
    ]
    conversations = [
        Conversation(id="demo_conversation_billing_001", ticket_id=tickets[0].id, channel="web", created_at=now - timedelta(hours=2)),
        Conversation(id="demo_conversation_handoff_002", ticket_id=tickets[1].id, channel="web", created_at=now - timedelta(hours=1)),
        Conversation(id="demo_conversation_subscription_003", ticket_id=tickets[2].id, channel="web", created_at=now - timedelta(days=1)),
    ]
    messages = [
        Message(id="demo_message_billing_customer_001", conversation_id=conversations[0].id,
                actor_type="customer", actor_id=users[0].id,
                content="I have a question about the $49.00 charge on my demo account.", created_at=now - timedelta(hours=2)),
        Message(id="demo_message_billing_agent_002", conversation_id=conversations[0].id,
                actor_type="agent", actor_id=None,
                content="I can help review that demo charge. Would you like me to check its status and date?", created_at=now - timedelta(hours=2) + timedelta(minutes=1)),
        Message(id="demo_message_handoff_customer_003", conversation_id=conversations[1].id,
                actor_type="customer", actor_id=users[0].id,
                content="Please connect me with a person about my demo account.", created_at=now - timedelta(hours=1)),
        Message(id="demo_message_subscription_customer_004", conversation_id=conversations[2].id,
                actor_type="customer", actor_id=users[1].id,
                content="Can you explain why my demo subscription is paused?", created_at=now - timedelta(days=1)),
    ]
    subscriptions = [
        Subscription(id="demo_subscription_alice_001", customer_id=customers[0].id,
                     plan="Demo Pro ($49/month)", status="active", started_at=now - timedelta(days=60), version=1),
        Subscription(id="demo_subscription_jordan_002", customer_id=customers[1].id,
                     plan="Demo Starter ($19/month)", status="paused", started_at=now - timedelta(days=30), version=1),
    ]
    transactions = [
        Transaction(id="demo_transaction_alice_001", customer_id=customers[0].id,
                    amount_minor=4900, currency="USD", status="settled", refundable_minor=4900,
                    occurred_at=now - timedelta(days=3), version=1),
        Transaction(id="demo_transaction_alice_002", customer_id=customers[0].id,
                    amount_minor=1200, currency="USD", status="settled", refundable_minor=0,
                    occurred_at=now - timedelta(days=10), version=1),
        Transaction(id="demo_transaction_jordan_001", customer_id=customers[1].id,
                    amount_minor=1900, currency="USD", status="pending", refundable_minor=0,
                    occurred_at=now - timedelta(days=1), version=1),
    ]
    queue_item = HumanQueue(
        id="demo_handoff_001", ticket_id=tickets[1].id, reason_code="CUSTOMER_REQUEST",
        summary="Synthetic demo request for a human support agent.", status="PENDING",
        created_at=now - timedelta(hours=1),
    )

    async with async_session_factory() as session:
        async with session.begin():
            # Serialize startup runs so simultaneous instances cannot insert duplicate fixtures.
            await session.execute(text("SELECT pg_advisory_xact_lock(724190260930)"))

            for customer in customers:
                existing = await session.get(Customer, customer.id)
                if existing is None:
                    conflict = await session.scalar(select(Customer.id).where(or_(
                        Customer.email == customer.email, Customer.external_ref == customer.external_ref,
                    )))
                    if conflict:
                        raise RuntimeError(f"Demo fixture identity conflicts with existing customer {conflict}; no records were changed.")
                    session.add(customer)

            for user in users:
                existing = await session.get(User, user.id)
                if existing is None:
                    conflict = await session.scalar(select(User.id).where(User.email == user.email))
                    if conflict:
                        raise RuntimeError(f"Demo fixture email conflicts with existing user {conflict}; no records were changed.")
                    session.add(user)

            for record in [*subscriptions, *transactions, *tickets, *conversations, *messages, queue_item]:
                if await session.get(type(record), record.id) is None:
                    session.add(record)

    await engine.dispose()
    print("Synthetic production demo data is ready.")
    print("Customer accounts: demo.alice@example.com and demo.jordan@example.com")
    print("Both use the password configured in DEMO_CUSTOMER_PASSWORD.")
    print("No staff accounts or executable approval proposals were created.")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
