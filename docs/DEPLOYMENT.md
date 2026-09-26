# Production Deployment

## Architecture

- Next.js frontend: Vercel
- FastAPI backend: Azure App Service using `docker/Dockerfile.api`
- PostgreSQL: Supabase
- Redis: managed Redis using a TLS `rediss://` URL
- Monitoring: separate Sentry projects for API and web

## Required Secrets

Set these in Azure App Service Configuration. Do not commit them or place them in GitHub workflow files.

```text
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=rediss://...
JWT_SIGNING_KEY=<random production secret>
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
LLM_API_KEY=<Gemini key>
CORS_ALLOWED_ORIGINS=https://your-frontend-domain
SENTRY_DSN=<backend Sentry DSN>
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.05
```

Set these in Vercel Project Settings -> Environment Variables:

```text
NEXT_PUBLIC_API_URL=https://your-api-domain
NEXT_PUBLIC_SENTRY_DSN=<frontend Sentry DSN>
NEXT_PUBLIC_SENTRY_ENVIRONMENT=production
```

## Database Migration

Run migrations from a trusted deployment job or locally with production environment variables loaded:

```powershell
$env:PYTHONPATH="apps/api"
python -m alembic upgrade head
```

The API does not create production tables at startup. Migrations must complete before the new API version receives traffic.

## Azure App Service

1. Create an App Service using the Linux container option.
2. Push the API image to a private Azure Container Registry.
3. Configure the App Service to use that image and listen on port `8000`.
4. Add the environment variables above in Configuration -> Application settings.
5. Set Health check path to `/health/ready`.
6. Add a custom domain such as `api.example.com`; Azure provisions HTTPS after DNS validation.
7. Restrict inbound access to HTTPS and keep database/Redis credentials out of source control.

## Vercel

1. Import the repository and set the project root to `apps/web`.
2. Set `NEXT_PUBLIC_API_URL` to the Azure HTTPS URL.
3. Add the frontend Sentry DSN and production environment.
4. Deploy and add the frontend custom domain.
5. Update Azure `CORS_ALLOWED_ORIGINS` to the exact Vercel/custom domain.

## Sentry

Create separate Sentry projects for `agent-v-api` and `agent-v-web`. Add the DSNs as environment variables. Add `SENTRY_AUTH_TOKEN` only to Vercel if source-map uploads are desired; never expose it as a `NEXT_PUBLIC_*` variable.

Configure alerts for unhandled exceptions, Gemini failures, database errors, Redis errors, and failed approval executions.

## Staging Acceptance Checks

Before public traffic, verify:

- `/health/live` returns 200.
- `/health/ready` reports database and Redis ready.
- Customer login succeeds.
- Read-only subscription request returns grounded data.
- Refund request creates a pending approval and does not execute.
- Reviewer approval executes exactly once.
- Rejection does not execute an action.
- Cross-customer access returns 403.
- Prompt-injection input does not reveal secrets or bypass approval.
- Sentry receives a controlled staging exception.

## Backups

Enable Supabase daily backups and point-in-time recovery according to the selected plan. Test restoring a backup into a separate staging project before launch. Ensure Redis is treated as recoverable cache state, not the system of record.
