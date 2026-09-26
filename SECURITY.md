# Security Policy

## Core Principles & Guarantees

1. **Deterministic Control Plane vs Probabilistic Reasoning Plane**
   - Language models propose classifications and actions; deterministic code enforces policies, authorization, and execution.
   - The LLM can never authorize refunds, cancellations, profile alterations, or any side effects.

2. **Least Privilege & Scoped Capabilities**
   - Every tool has narrow, strongly-typed Pydantic schemas.
   - Raw SQL, shell execution, filesystem access, eval, and generic HTTP endpoints are strictly prohibited.
   - Separate read and write tools; write actions enforce server-generated idempotency keys and transactional boundaries.

3. **Untrusted Data Boundary**
   - Customer messages, support ticket histories, CRM notes, and tool outputs are strictly treated as untrusted data.
   - System prompts instruct agents to never treat customer-supplied or external data as instructions.

4. **Human-In-The-Loop (HITL) by Default**
   - High-risk actions (Refunds, Subscription Cancellations, Account Deletion) require authenticated human reviewer approval.
   - Approvals are cryptographically bound to the canonical SHA-256 hash of the action proposal.
   - On resume, the system verifies the proposal hash, checks non-expiry, and revalidates customer ownership, transaction status, and version before execution.

5. **Secrets & PII Protection**
   - LLM prompts, logs, and client responses never contain signing secrets, database credentials, reviewer tokens, or unredacted payment details.
   - All logging uses structured JSON with automatic redaction of sensitive headers and fields.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately to security@example.com instead of opening a public issue.
