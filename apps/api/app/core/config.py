from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./agent_v.db"
    CHECKPOINT_DATABASE_URL: str = ""
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT & Auth
    JWT_SIGNING_KEY: str = "dev-insecure-secret-key-change-in-production-must-be-32-bytes-minimum!"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "agent-v-auth"
    JWT_AUDIENCE: str = "agent-v-api"
    ACCESS_TOKEN_MINUTES: int = 30
    AUTH_TOKEN_TTL_MINUTES: int = 60
    PASSWORD_RESET_TTL_MINUTES: int = 30
    FRONTEND_URL: str = "http://localhost:3000"

    # SMTP (required in production for verification and recovery)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_STARTTLS: bool = True

    # Financial action provider contract. The provider must honor Idempotency-Key.
    ACTION_GATEWAY_URL: str = ""
    ACTION_GATEWAY_API_KEY: str = ""

    # LLM Settings
    LLM_PROVIDER: str = "fake"  # 'fake', 'openai', 'gemini', etc.
    LLM_MODEL: str = "gemini-3.8-flash"
    LLM_API_KEY: str = "mock-api-key"
    LLM_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/models"

    # Resource Budgets
    MAX_AGENT_ATTEMPTS: int = 3
    MAX_LLM_CALLS_PER_RUN: int = 8
    MAX_TOOL_CALLS_PER_RUN: int = 12
    MAX_TOTAL_TOKENS_PER_RUN: int = 10000

    # Policy / HITL
    APPROVAL_EXPIRY_MINUTES: int = 60
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    LANGFUSE_ENABLED: bool = False
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> List[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def checkpoint_database_url(self) -> str:
        value = self.CHECKPOINT_DATABASE_URL or self.DATABASE_URL
        return value.replace("postgresql+asyncpg://", "postgresql://", 1)

    def validate_production(self) -> None:
        if not self.DATABASE_URL.startswith("postgresql+asyncpg://"):
            raise RuntimeError("Production requires a postgresql+asyncpg DATABASE_URL")
        if not self.CHECKPOINT_DATABASE_URL.startswith("postgresql://"):
            raise RuntimeError("Production requires an explicit psycopg PostgreSQL checkpoint URL")
        if not self.JWT_SIGNING_KEY or len(self.JWT_SIGNING_KEY) < 32 or self.JWT_SIGNING_KEY.startswith("dev-"):
            raise RuntimeError("Production requires a unique JWT_SIGNING_KEY of at least 32 characters")
        if self.LLM_PROVIDER != "gemini" or not self.LLM_API_KEY or self.LLM_API_KEY.startswith(("your_", "mock-")):
            raise RuntimeError("Production requires a configured Gemini API key")
        if not all((self.SMTP_HOST, self.SMTP_USERNAME, self.SMTP_PASSWORD, self.SMTP_FROM_EMAIL)):
            raise RuntimeError("Production requires SMTP credentials for account verification and recovery")
        if not self.ACTION_GATEWAY_URL.startswith("https://") or not self.ACTION_GATEWAY_API_KEY:
            raise RuntimeError("Production requires an HTTPS action gateway and API key")
        if not self.CORS_ALLOWED_ORIGINS or "*" in self.CORS_ALLOWED_ORIGINS:
            raise RuntimeError("Production CORS origins must be explicit")
        if not self.ALLOWED_HOSTS or "*" in self.ALLOWED_HOSTS:
            raise RuntimeError("Production ALLOWED_HOSTS must be explicit")


settings = Settings()
