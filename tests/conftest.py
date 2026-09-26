import asyncio
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base, get_db
from app.models.entities import (
    User,
    Customer,
    Subscription,
    Transaction,
    SupportTicket,
    Conversation,
    Message,
)
from app.auth.security import hash_password, create_access_token
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_async_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_async_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def seed_test_data(db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    pwd = hash_password("Password123!")

    # Customers
    cust1 = Customer(
        id="cust_alice",
        external_ref="ext_alice",
        display_name="Alice Smith",
        email="alice@test.com",
        phone="+1-555-0101",
        status="active",
    )
    cust2 = Customer(
        id="cust_bob",
        external_ref="ext_bob",
        display_name="Bob Jones",
        email="bob@test.com",
        phone="+1-555-0202",
        status="active",
    )
    db_session.add_all([cust1, cust2])
    await db_session.commit()

    # Users
    u_alice = User(
        id="user_alice",
        email="alice@test.com",
        password_hash=pwd,
        role="customer",
        customer_id=cust1.id,
    )
    u_bob = User(
        id="user_bob",
        email="bob@test.com",
        password_hash=pwd,
        role="customer",
        customer_id=cust2.id,
    )
    u_rev = User(
        id="user_reviewer",
        email="reviewer@test.com",
        password_hash=pwd,
        role="reviewer",
    )
    u_admin = User(
        id="user_admin",
        email="admin@test.com",
        password_hash=pwd,
        role="admin",
    )
    db_session.add_all([u_alice, u_bob, u_rev, u_admin])
    await db_session.commit()

    # Subscriptions
    sub_alice = Subscription(
        id="sub_alice_1",
        customer_id=cust1.id,
        plan="Pro Plan",
        status="active",
        started_at=now - timedelta(days=30),
        version=1,
    )
    sub_bob = Subscription(
        id="sub_bob_1",
        customer_id=cust2.id,
        plan="Basic Plan",
        status="active",
        started_at=now - timedelta(days=15),
        version=1,
    )
    db_session.add_all([sub_alice, sub_bob])

    # Transactions
    txn_alice = Transaction(
        id="txn_alice_1",
        customer_id=cust1.id,
        amount_minor=5000,
        currency="USD",
        status="settled",
        refundable_minor=5000,
        occurred_at=now - timedelta(days=2),
        version=1,
    )
    txn_bob = Transaction(
        id="txn_bob_1",
        customer_id=cust2.id,
        amount_minor=3000,
        currency="USD",
        status="settled",
        refundable_minor=3000,
        occurred_at=now - timedelta(days=1),
        version=1,
    )
    db_session.add_all([txn_alice, txn_bob])

    # Ticket
    ticket_alice = SupportTicket(
        id="ticket_alice_1",
        customer_id=cust1.id,
        subject="Sample question",
        status="open",
        priority="normal",
    )
    db_session.add(ticket_alice)
    await db_session.commit()

    conv_alice = Conversation(
        id="conv_alice_1",
        ticket_id=ticket_alice.id,
        channel="web",
    )
    db_session.add(conv_alice)
    await db_session.commit()

    return {
        "alice": u_alice,
        "bob": u_bob,
        "reviewer": u_rev,
        "admin": u_admin,
        "ticket_alice": ticket_alice,
        "conv_alice": conv_alice,
        "txn_alice": txn_alice,
        "sub_alice": sub_alice,
    }


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_tokens():
    return {
        "alice": create_access_token(user_id="user_alice", email="alice@test.com", role="customer", customer_id="cust_alice"),
        "bob": create_access_token(user_id="user_bob", email="bob@test.com", role="customer", customer_id="cust_bob"),
        "reviewer": create_access_token(user_id="user_reviewer", email="reviewer@test.com", role="reviewer"),
        "admin": create_access_token(user_id="user_admin", email="admin@test.com", role="admin"),
    }
