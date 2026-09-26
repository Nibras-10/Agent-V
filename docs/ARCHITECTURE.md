# Architecture & Security Specification

## 1. Overview & Core Philosophy

This system implements a stateful, auditable, enterprise-grade Autonomous Customer Support & Action Agent using **LangGraph** with a **deterministic control plane** and a **probabilistic reasoning plane**.

```text
Customer Web UI (Next.js)
      ↓
FastAPI Gateway → Auth (JWT / Scopes) → Object-Level Authorization (BOLA) → Rate Limiting
      ↓
LangGraph Support Workflow
  ├─ Ingest Request (State init & budgets)
  ├─ Triage Agent (Intent & urgency classification; zero side-effects)
  ├─ Context/DB Agent (Strictly scoped read tools; authenticated customer only)
  ├─ Resolution/Action Agent (Grounded reasoning; generates typed proposals)
  ├─ Deterministic Policy/Risk Engine (Refund, Cancellation, Contact rules)
  ├─ Human-In-The-Loop Approval Interrupt (State persisted; reviewer portal gated)
  ├─ Action Executor (Idempotent execution with canonical SHA-256 hash checks)
  ├─ Draft Response (Authoritative grounded messages)
  ├─ Human Handoff (Enqueued on 3 failures or budget limits)
  └─ Finalize (Status persistence & audit event logging)
```

## 2. Inviolable Security Guarantees

1. **Deterministic Authorization**:
   - The LLM classifies intent and drafts proposals, but **never authorizes, approves, or executes financial transactions or cancellations**.
2. **Cryptographic Proposal Binding**:
   - Every high-risk proposal produces a canonical SHA-256 hash `SHA-256(canonical JSON)`.
   - On reviewer approval and resume, the system recomputes and verifies the hash against the authoritative database state to detect any proposal tampering.
3. **Idempotent Execution**:
   - Every state mutation uses a server-generated idempotency key (`idempotency_key UNIQUE`).
   - Duplicate calls return the recorded result without performing a second write.
4. **Untrusted Data Boundary**:
   - Customer messages, support histories, CRM records, and tool outputs are treated strictly as untrusted data strings, preventing prompt injection and privilege escalation.
5. **No Blind Retries**:
   - Hard budgets: max 3 recovery attempts, max 8 LLM calls, max 12 tool calls, max 10,000 tokens per run. If exceeded, bounded failure triggers a single human handoff.
