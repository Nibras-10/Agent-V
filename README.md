# Agent V

Agent V is a customer-support platform with an AI-assisted support workflow and separate customer and staff workspaces. Customers can ask about their accounts and request help. Support staff can manage conversations and handoffs, while authorized reviewers control sensitive account actions.

The application combines a Next.js web interface, a FastAPI service, a LangGraph workflow, PostgreSQL, and Redis. Policy checks and authorization remain in the application; the language model proposes responses and actions but does not grant permissions or approve sensitive actions.

## Capabilities

- Customer registration, sign-in, email verification, and password recovery
- Authenticated, customer-scoped account and conversation views
- Request triage and account-context lookup
- Policy-checked refund and subscription-cancellation proposals
- Human approval, persisted workflow state, and action audit records
- Staff ticket inbox, replies, assignments, and human handoff
- Contact-detail updates subject to authorization and policy
- Request budgets, rate limiting, secure password hashing, and structured application logs

## Architecture

```text
Next.js web app
      │
      ▼
FastAPI API ── JWT authentication and role/object authorization
      │
      ├── LangGraph support workflow ── policy and approval steps
      ├── PostgreSQL ── accounts, tickets, actions, audit, workflow checkpoints
      ├── Redis ── rate limits and ephemeral coordination
      ├── SMTP ── account verification and password recovery
      └── HTTPS action gateway ── approved refunds and cancellations
```

Live financial operations require an action gateway that implements the contract in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The application sends approved actions to that gateway with an idempotency key; connect it to a payment or subscription provider only after implementing and validating the provider-side contract.

## Technology

- **Web:** Next.js 14, React 18, TypeScript
- **API:** Python 3.12+, FastAPI, Pydantic
- **Agent workflow:** LangGraph
- **Database:** PostgreSQL with SQLAlchemy and Alembic; SQLite is supported for local development
- **Cache and rate limits:** Redis 7+
- **Deployment:** Docker Compose, Caddy, and a container registry or hosting platform

## Requirements

For local development:

- Python 3.12 or newer
- Node.js 20 or newer and npm
- Git

For the included production Compose deployment:

- A Linux host with Docker Engine and the Docker Compose plugin
- A DNS name pointed at that host, with inbound ports 80 and 443 available
- PostgreSQL (the documented deployment uses Supabase)
- An authenticated Redis service
- SMTP credentials
- A Gemini API key
- An HTTPS action gateway implementing the project contract

## Run locally

### API

Clone the repository and create the Python environment from the repository root:

```shell
git clone <repository-url>
cd <repository-directory>
python -m venv .venv
```

Activate the environment and install dependencies:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```shell
# macOS / Linux
source .venv/bin/activate
```

```shell
pip install -r requirements.txt
```

Create local configuration from the example file:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
$env:PYTHONPATH = "apps/api"
```

```shell
# macOS / Linux
cp .env.example .env
export PYTHONPATH=apps/api
```

The example configuration uses a local SQLite database and development settings. For local use, the API can fall back to a deterministic model adapter when no valid model API key is configured; Redis can also be omitted in development.

Start the API from the repository root:

```shell
uvicorn app.main:app --reload --port 8000
```

In development, the API creates its SQLite tables at startup. Its interactive API reference is at [http://localhost:8000/docs](http://localhost:8000/docs).

### Web app

Open a second terminal from the repository root:

```powershell
# Windows PowerShell
Copy-Item apps/web/.env.example apps/web/.env.local
```

```shell
# macOS / Linux
cp apps/web/.env.example apps/web/.env.local
```

Then start the web app:

```shell
cd apps/web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The web app reads `NEXT_PUBLIC_API_URL` from `apps/web/.env.local`; the example points to the local API. Create a customer account from the sign-up page. Staff accounts must be provisioned by an operator.

## Production deployment with Docker Compose

The included [`docker-compose.yml`](docker-compose.yml) runs the API, web app, Redis, migration job, and Caddy reverse proxy. PostgreSQL, SMTP, the language model, and the action gateway are configured as external services.

1. Configure DNS for your deployment domain and allow inbound TCP ports 80 and 443.
2. Copy `.env.example` to `.env` on the deployment host. Keep this file out of source control.
3. Set the production values described below. Use a PostgreSQL transaction-pool URL for `DATABASE_URL`, and a direct/session PostgreSQL URL for `CHECKPOINT_DATABASE_URL`.
4. Set `DOMAIN`, `REDIS_PASSWORD`, a unique `JWT_SIGNING_KEY` of at least 32 characters, Gemini credentials, SMTP credentials, and the action-gateway URL and API key.
5. Set `CORS_ALLOWED_ORIGINS` and `ALLOWED_HOSTS` to the exact public web and API hosts. The included Caddy configuration serves the web app and forwards `/api/*` and `/health/*` to the API.
6. Build and start the services:

   ```shell
   docker compose up --build -d
   ```

7. Confirm `https://<your-domain>/health/ready` reports ready and that Caddy has obtained a TLS certificate.
8. Provision the first staff account from a trusted operator environment connected to the configured database:

   ```shell
   PYTHONPATH=apps/api python scripts/provision_staff.py reviewer@example.com reviewer
   ```

   The script prompts for a password without putting it in shell history. Supported staff roles are `support_agent`, `reviewer`, `auditor`, and `admin`.

The Compose deployment runs the Alembic migration job before starting the API. For other hosting platforms, run `alembic upgrade head` once as a release step before shifting traffic. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for database, action-gateway, backup, and operational details.

### Production configuration

| Variable | Purpose |
|---|---|
| `APP_ENV` | Set to `production` to enable production checks and security behavior |
| `DOMAIN` | Public hostname used by Caddy and the web build |
| `DATABASE_URL` | PostgreSQL application database URL using `postgresql+asyncpg://` |
| `CHECKPOINT_DATABASE_URL` | Direct/session PostgreSQL URL for LangGraph checkpoints using `postgresql://` |
| `REDIS_PASSWORD` / `REDIS_URL` | Authenticated Redis connection |
| `JWT_SIGNING_KEY` | Unique secret of at least 32 characters; never use the development example |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | Language model provider, model, and credential |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | Verification and account-recovery email delivery |
| `ACTION_GATEWAY_URL`, `ACTION_GATEWAY_API_KEY` | HTTPS action gateway for approved financial actions |
| `CORS_ALLOWED_ORIGINS`, `ALLOWED_HOSTS` | Explicit allowed browser origins and hostnames |
| `FRONTEND_URL` | Public frontend URL used in account emails |

See [`.env.example`](.env.example) for the full configuration list. Store production secrets in your host's secret manager where possible. Do not commit `.env` or real credentials.

## Staff account provisioning

There is no public staff registration. An operator creates staff accounts with `scripts/provision_staff.py`; the password is entered interactively and stored as a password hash. Grant each person the least-privileged role they need. Customer accounts are created through the customer sign-up flow.

## Security and operations

- Customer routes derive identity from the authenticated user and enforce customer-level access checks.
- Sensitive actions require authorization and reviewer approval; provider calls use idempotency keys.
- Customer messages and retrieved records are untrusted input to the agent workflow.
- Production requires PostgreSQL, Redis, explicit CORS and host allow-lists, and a strong JWT key.
- Configure SMTP, TLS, backups, Sentry or equivalent monitoring, and test database restore and action recovery procedures before launch.
- Review [`SECURITY.md`](SECURITY.md) before reporting a vulnerability.

## Repository layout

```text
apps/api/       FastAPI routes, authentication, agent workflow, policy, and persistence
apps/web/       Next.js customer and staff application
docker/         Container and reverse-proxy configuration
migrations/     Alembic schema migrations
scripts/        Staff provisioning and operational scripts
docs/           Architecture and deployment documentation
tests/          Automated tests
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Production deployment](docs/DEPLOYMENT.md)
- [Security policy](SECURITY.md)
- [License](LICENSE)
