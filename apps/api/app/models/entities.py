import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # customer, support_agent, reviewer, auditor, admin
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="users")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    external_ref: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    users: Mapped[List["User"]] = relationship("User", back_populates="customer")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="customer")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="customer")
    tickets: Mapped[List["SupportTicket"]] = relationship("SupportTicket", back_populates="customer")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)  # active, canceled, paused
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    cancel_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    customer: Mapped["Customer"] = relationship("Customer", back_populates="subscriptions")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)  # minor currency units, e.g. 5000 = $50.00
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="settled", nullable=False)  # settled, refunded, pending
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    refundable_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    customer: Mapped["Customer"] = relationship("Customer", back_populates="transactions")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)  # open, pending_approval, resolved, handed_off
    priority: Mapped[str] = mapped_column(String(50), default="normal", nullable=False)  # low, normal, high, urgent
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    customer: Mapped["Customer"] = relationship("Customer", back_populates="tickets")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="ticket")
    runs: Mapped[List["AgentRun"]] = relationship("AgentRun", back_populates="ticket")
    human_queue_items: Mapped[List["HumanQueue"]] = relationship("HumanQueue", back_populates="ticket")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("support_tickets.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="web", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), index=True, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)  # customer, agent, reviewer, system
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("support_tickets.id"), index=True, nullable=False)
    graph_status: Mapped[str] = mapped_column(String(50), default="RUNNING", nullable=False)  # RUNNING, COMPLETED, WAITING_FOR_APPROVAL, HANDED_OFF, FAILED
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_counts: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_alias: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="runs")
    proposals: Mapped[List["ActionProposal"]] = relationship("ActionProposal", back_populates="run")


class ActionProposal(Base):
    __tablename__ = "action_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # refund, cancellation, contact_update
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="HIGH", nullable=False)  # LOW, HIGH
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 of canonical proposal
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED, EXPIRED, EXECUTED

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="proposals")
    approval: Mapped[Optional["Approval"]] = relationship("Approval", back_populates="proposal", uselist=False)
    executed_action: Mapped[Optional["ExecutedAction"]] = relationship("ExecutedAction", back_populates="proposal", uselist=False)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("action_proposals.id"), unique=True, index=True, nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("support_tickets.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED, EXPIRED
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    proposal: Mapped["ActionProposal"] = relationship("ActionProposal", back_populates="approval")
    reviewer: Mapped[Optional["User"]] = relationship("User")


class ExecutedAction(Base):
    __tablename__ = "executed_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("action_proposals.id"), unique=True, index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="SUCCESS", nullable=False)  # SUCCESS, FAILED, UNKNOWN
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    proposal: Mapped["ActionProposal"] = relationship("ActionProposal", back_populates="executed_action")


class HumanQueue(Base):
    __tablename__ = "human_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("support_tickets.id"), index=True, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)  # LOOP_LIMIT, TOKEN_BUDGET, AMBIGUOUS, POLICY_DENIAL, SYSTEM_ERROR
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, ASSIGNED, RESOLVED
    assigned_to: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="human_queue_items")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    request_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)  # customer, reviewer, agent, system
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    metadata_redacted: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# Indexing
Index("ix_audit_ticket_created", AuditEvent.ticket_id, AuditEvent.created_at)
Index("ix_proposal_status_risk", ActionProposal.status, ActionProposal.risk_level)
