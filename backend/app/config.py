"""
app/config.py
Application configuration for Code Explorer.

Uses Pydantic Settings (v2) to load all values from environment variables
or a .env file.  Secrets are never hard-coded here.

Usage::

    from app.config import get_settings
    settings = get_settings()
    print(settings.app_name)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Sub-settings groups
# Each group maps to a logical service.  They are composed into Settings below.


class AppSettings(BaseSettings):
    """Core application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default="Code Explorer", alias="APP_NAME")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_secret_key: str = Field(
        default="change-me-in-production", alias="APP_SECRET_KEY"
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def log_level(self) -> str:
        return "DEBUG" if self.app_debug else "INFO"

    @property
    def json_logs(self) -> bool:
        """Use JSON logs in production / staging; pretty logs in development."""
        return self.app_env != "development"


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/code_explorer",
        alias="DATABASE_URL",
        description="Async PostgreSQL DSN (postgresql+asyncpg://...)",
    )
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    database_echo_sql: bool = Field(default=False, alias="DATABASE_ECHO_SQL")

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v


class QdrantSettings(BaseSettings):
    """Qdrant vector database settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
    )
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_timeout: float = Field(default=30.0, alias="QDRANT_TIMEOUT")


class RedisSettings(BaseSettings):
    """Redis connection settings (used for Celery broker, cache, rate limiting)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
    )
    redis_cache_ttl_seconds: int = Field(
        default=3600, alias="REDIS_CACHE_TTL_SECONDS"
    )


class CelerySettings(BaseSettings):
    """Celery task queue settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        alias="CELERY_RESULT_BACKEND",
    )
    # Set True to run tasks synchronously in tests (no broker needed)
    celery_task_always_eager: bool = Field(
        default=False, alias="CELERY_TASK_ALWAYS_EAGER"
    )


class GitHubSettings(BaseSettings):
    """GitHub API and webhook settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_webhook_secret: str | None = Field(
        default=None, alias="GITHUB_WEBHOOK_SECRET"
    )
    github_api_base_url: str = Field(
        default="https://api.github.com", alias="GITHUB_API_BASE_URL"
    )
    github_max_file_size_mb: int = Field(
        default=10, alias="GITHUB_MAX_FILE_SIZE_MB"
    )

    @property
    def github_max_file_size_bytes(self) -> int:
        return self.github_max_file_size_mb * 1024 * 1024


class EmbeddingSettings(BaseSettings):
    """Jina AI embedding settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    jina_api_key: str | None = Field(default=None, alias="JINA_API_KEY")
    jina_api_url: str = Field(
        default="https://api.jina.ai/v1/embeddings", alias="JINA_API_URL"
    )
    jina_embedding_model: str = Field(
        default="jina-embeddings-v3", alias="JINA_EMBEDDING_MODEL"
    )
    jina_embedding_batch_size: int = Field(
        default=32, alias="JINA_EMBEDDING_BATCH_SIZE"
    )
    jina_max_retries: int = Field(default=6, alias="JINA_MAX_RETRIES")
    jina_inter_batch_delay: float = Field(
        default=2.0, alias="JINA_INTER_BATCH_DELAY"
    )
    embedding_dimension: int = Field(
        default=1024, alias="EMBEDDING_DIMENSION"
    )


class LLMSettings(BaseSettings):
    """Qwen LLM settings (OpenAI-compatible DashScope endpoint)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    qwen_api_key: str | None = Field(default=None, alias="QWEN_API_KEY")
    qwen_model: str = Field(default="qwen-plus", alias="QWEN_MODEL")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_max_tokens: int = Field(default=4096, alias="QWEN_MAX_TOKENS")
    qwen_temperature: float = Field(default=0.1, alias="QWEN_TEMPERATURE")
    qwen_max_retries: int = Field(default=3, alias="QWEN_MAX_RETRIES")
    qwen_timeout_seconds: int = Field(default=60, alias="QWEN_TIMEOUT_SECONDS")


class IngestionSettings(BaseSettings):
    """Ingestion pipeline tuning settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ingestion_max_zip_size_mb: int = Field(
        default=500, alias="INGESTION_MAX_ZIP_SIZE_MB"
    )
    ingestion_max_zip_files: int = Field(
        default=10_000, alias="INGESTION_MAX_ZIP_FILES"
    )
    ingestion_chunk_max_tokens: int = Field(
        default=512, alias="INGESTION_CHUNK_MAX_TOKENS"
    )
    ingestion_chunk_overlap_tokens: int = Field(
        default=64, alias="INGESTION_CHUNK_OVERLAP_TOKENS"
    )


class SearchSettings(BaseSettings):
    """Search pipeline tuning settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    search_top_k: int = Field(default=20, alias="SEARCH_TOP_K")
    search_min_evidence_score: float = Field(
        default=0.5, alias="SEARCH_MIN_EVIDENCE_SCORE"
    )
    search_max_context_tokens: int = Field(
        default=8192, alias="SEARCH_MAX_CONTEXT_TOKENS"
    )


# Composite Settings

class Settings(
    AppSettings,
    DatabaseSettings,
    QdrantSettings,
    RedisSettings,
    CelerySettings,
    GitHubSettings,
    EmbeddingSettings,
    LLMSettings,
    IngestionSettings,
    SearchSettings,
):
    """
    Single composite settings object loaded once at startup.

    All values come from environment variables or the .env file.
    No secrets are hard-coded here.

    Usage::

        from app.config import get_settings
        s = get_settings()
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def warn_missing_optional_secrets(self) -> "Settings":
        """
        Emit warnings for optional secrets that are missing in production.
        Does NOT raise — allows the app to start without credentials during
        local development and testing.
        """
        import warnings  # noqa: PLC0415

        if self.is_production:
            if not self.github_token:
                warnings.warn(
                    "GITHUB_TOKEN is not set in production", stacklevel=2
                )
            if not self.jina_api_key:
                warnings.warn(
                    "JINA_API_KEY is not set in production", stacklevel=2
                )
            if not self.qwen_api_key:
                warnings.warn(
                    "QWEN_API_KEY is not set in production", stacklevel=2
                )
            if not self.github_webhook_secret:
                warnings.warn(
                    "GITHUB_WEBHOOK_SECRET is not set in production", stacklevel=2
                )
        return self


# Singleton accessor

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached application settings instance.

    The first call reads from environment / .env file.
    Subsequent calls return the same cached object.

    In tests, call ``get_settings.cache_clear()`` to reset.
    """
    return Settings()
