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

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT & Auth
    JWT_SIGNING_KEY: str = "dev-insecure-secret-key-change-in-production-must-be-32-bytes-minimum!"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "agent-v-auth"
    JWT_AUDIENCE: str = "agent-v-api"
    ACCESS_TOKEN_MINUTES: int = 60

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
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def checkpoint_database_url(self) -> str:
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


settings = Settings()
