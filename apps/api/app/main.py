import asyncio
import sys
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sentry_sdk
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.config import settings
from app.core.database import engine, Base
from app.core.redis import redis_client
from app.observability.logging import setup_logging, logger
from app.api.v1.auth_router import router as auth_router
from app.api.v1.conversation_router import router as conv_router
from app.api.v1.ticket_router import router as ticket_router
from app.api.v1.approval_router import router as approval_router
from app.api.v1.handoff_router import router as handoff_router
from app.api.v1.audit_router import router as audit_router
from app.api.v1.health_router import router as health_router
from app.agents.checkpointer import set_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup structured logging
    setup_logging()
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,
        )
    logger.info("Starting Autonomous Support Agent API...")

    if settings.is_production:
        if settings.DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("SQLite is not supported in production")
        if settings.JWT_SIGNING_KEY.startswith("dev-"):
            raise RuntimeError("A production JWT signing key is required")
        if settings.LLM_PROVIDER == "fake":
            raise RuntimeError("The fake LLM provider is not supported in production")

    if not settings.is_production:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    await redis_client.init()

    if settings.is_production:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as checkpointer:
            await checkpointer.setup()
            set_checkpointer(checkpointer)
            try:
                yield
            finally:
                set_checkpointer(None)
    else:
        yield

    await redis_client.close()
    await engine.dispose()
    logger.info("API shutdown complete.")


app = FastAPI(
    title="Autonomous Customer Support & Action Agent API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_and_tracing_middleware(request: Request, call_next):
    # Attach correlation request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start_time = time.time()

    # Pass request ID in state
    request.state.request_id = request_id

    try:
        response: Response = await call_next(request)
    except Exception as exc:
        duration = round((time.time() - start_time) * 1000, 2)
        logger.error(
            f"Unhandled exception processing request: {exc}",
            extra={"request_id": request_id, "duration": duration, "error_code": "INTERNAL_SERVER_ERROR"},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred.", "request_id": request_id},
        )

    duration = round((time.time() - start_time) * 1000, 2)

    # Security headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    logger.info(
        f"{request.method} {request.url.path} returned {response.status_code} ({duration}ms)",
        extra={"request_id": request_id, "status": response.status_code, "duration": duration},
    )

    return response


# Include Routers
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(conv_router, prefix="/api/v1")
app.include_router(ticket_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")
app.include_router(handoff_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
