# Production Deployment

## Required services

- Next.js frontend behind Caddy (automatic HTTPS/TLS).
- FastAPI API container (`docker/Dockerfile.api`), run as non-root.
- Supabase PostgreSQL for application records and LangGraph checkpoints.
- Redis 7 with authentication; production fails closed if Redis is unavailable.
- SMTP for email verification and password recovery.
- A live HTTPS action gateway that honors `Idempotency-Key` and supports the routes in `app/integrations/action_gateway.py`.

## Secrets and configuration

Copy `.env.example` to a private deployment secret store. Never commit `.env` or put production secrets in source control. Compose requires `DOMAIN`, both database URLs, Redis password, unique JWT key (32+ random characters), Gemini key, SMTP credentials, and action gateway URL/key. Use Supabase's transaction pooler for `DATABASE_URL` (asyncpg URL) and a direct/session PostgreSQL endpoint for `CHECKPOINT_DATABASE_URL` (`postgresql://`, psycopg). Require TLS for both remote database connections and Redis (`rediss://` when managed Redis is used).

Set `CORS_ALLOWED_ORIGINS` and `ALLOWED_HOSTS` to exact domains. Caddy terminates TLS and sends traffic to private API/web services; only ports 80/443 are published. Keep provider/API keys in the platform's secret manager, rotate them, and restrict access to deployment operators.

## Database migrations

Run migrations once from a trusted deployment job before rolling out the API. Do not run `Base.metadata.create_all` in production. Compose runs one `migrate` service to completion before starting the API; for other platforms, run `alembic upgrade head` once from the release pipeline before shifting traffic.

The migration chain contains the full initial application schema plus auth/token and provider-reference changes. Check migration status before releasing and rehearse upgrades/restores against a staging Supabase project.

## Compose deployment

1. Point the DNS `DOMAIN` at the host and allow inbound 80/443.
2. Configure every required variable in a protected `.env` (or inject via a secrets manager).
3. Build and start `docker-compose.yml`; its one-shot migration service completes before the API starts.
4. Confirm `/health/ready` is healthy and Caddy has issued a certificate.
5. Create the first staff user from an operator shell with `PYTHONPATH=apps/api python scripts/provision_staff.py EMAIL reviewer` (or the intended least-privilege role). Password is entered interactively and hashed; no public staff registration exists.
6. Verify auth email delivery, recovery, rate limiting, action-provider idempotency, database backup restore, and alerting in staging before launch.

## Provider contract and action recovery

The action gateway accepts `POST /refunds` with `transaction_ref`, `amount_minor`, and `currency`, and `POST /subscriptions/{ref}/cancel` with `cancel_at_period_end`. It receives `Authorization: Bearer …` and a stable `Idempotency-Key`; a refund response must include `status: succeeded` or `refunded`, and a cancellation response must include `canceled`, `cancelled`, or `scheduled` as applicable. Configure provider-side key retention longer than the maximum approval/reconciliation period. Import authoritative processor references into `transactions.provider_ref` and `subscriptions.provider_ref`; missing refs block live actions. The API persists a PENDING execution before calling the provider and commits the local action, result, and audit event together. If the outcome is uncertain, the same reviewer can safely retry against the same key.

## Backups and monitoring

Enable Supabase backups/PITR and test restoring to a separate staging project. Configure Sentry DSNs and alert on readiness failures, authentication abuse, repeated provider uncertainty, and failed migrations. Redis is rate-limit/cache state and is not the system of record.
