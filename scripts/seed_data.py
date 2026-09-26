import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.core.database import async_session_factory, engine, Base
from app.models.entities import (
    User,
    Customer,
    Subscription,
    Transaction,
    SupportTicket,
    Conversation,
    Message,
)
from app.auth.security import hash_password


async def seed():
    print("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # Check if already seeded
        res = await session.execute(select(User).limit(1))
        if res.scalar_one_or_none():
            print("Database already contains data. Skipping seeding.")
            return

        print("Seeding initial mock customers...")
        alice_cust = Customer(
            id="cust_alice_001",
            external_ref="ext_alice_001",
            display_name="Alice Smith",
            email="alice@example.com",
            phone="+1-555-0100",
            status="active",
        )
        bob_cust = Customer(
            id="cust_bob_002",
            external_ref="ext_bob_002",
            display_name="Bob Jones",
            email="bob@example.com",
            phone="+1-555-0200",
            status="active",
        )
        session.add_all([alice_cust, bob_cust])
        await session.commit()

        print("Seeding users...")
        pwd_hash = hash_password("Password123!")

        users = [
            User(
                id="user_alice_001",
                email="alice@example.com",
                password_hash=pwd_hash,
                role="customer",
                customer_id=alice_cust.id,
            ),
            User(
                id="user_bob_002",
                email="bob@example.com",
                password_hash=pwd_hash,
                role="customer",
                customer_id=bob_cust.id,
            ),
            User(
                id="user_reviewer_001",
                email="reviewer@example.com",
                password_hash=pwd_hash,
                role="reviewer",
            ),
            User(
                id="user_agent_001",
                email="agent@example.com",
                password_hash=pwd_hash,
                role="support_agent",
            ),
            User(
                id="user_admin_001",
                email="admin@example.com",
                password_hash=pwd_hash,
                role="admin",
            ),
        ]
        session.add_all(users)

        print("Seeding subscriptions...")
        now = datetime.now(timezone.utc)
        sub_alice = Subscription(
            id="sub_alice_001",
            customer_id=alice_cust.id,
            plan="Pro Plan ($49/mo)",
            status="active",
            started_at=now - timedelta(days=60),
            version=1,
        )
        sub_bob = Subscription(
            id="sub_bob_002",
            customer_id=bob_cust.id,
            plan="Starter Plan ($19/mo)",
            status="active",
            started_at=now - timedelta(days=30),
            version=1,
        )
        session.add_all([sub_alice, sub_bob])

        print("Seeding transactions...")
        txns = [
            Transaction(
                id="txn_alice_001",
                customer_id=alice_cust.id,
                amount_minor=5000,  # $50.00
                currency="USD",
                status="settled",
                refundable_minor=5000,
                occurred_at=now - timedelta(days=5),
                version=1,
            ),
            Transaction(
                id="txn_alice_002",
                customer_id=alice_cust.id,
                amount_minor=12000,  # $120.00
                currency="USD",
                status="settled",
                refundable_minor=12000,
                occurred_at=now - timedelta(days=2),
                version=1,
            ),
            Transaction(
                id="txn_bob_001",
                customer_id=bob_cust.id,
                amount_minor=1900,  # $19.00
                currency="USD",
                status="settled",
                refundable_minor=1900,
                occurred_at=now - timedelta(days=1),
                version=1,
            ),
        ]
        session.add_all(txns)

        print("Seeding initial support ticket...")
        ticket = SupportTicket(
            id="ticket_alice_001",
            customer_id=alice_cust.id,
            subject="Billing question regarding recent invoice",
            priority="normal",
            status="open",
        )
        session.add(ticket)
        await session.commit()

        conv = Conversation(
            id="conv_alice_001",
            ticket_id=ticket.id,
            channel="web",
        )
        session.add(conv)
        await session.commit()

        msg = Message(
            conversation_id=conv.id,
            actor_type="customer",
            actor_id="user_alice_001",
            content="Hello, I noticed a charge on my account and would like some information about it.",
        )
        session.add(msg)
        await session.commit()

        print("Seeding completed successfully!")
        print("Demo credentials:")
        print("Customer: alice@example.com / Password123!")
        print("Reviewer: reviewer@example.com / Password123!")
        print("Admin:    admin@example.com / Password123!")


if __name__ == "__main__":
    asyncio.run(seed())
