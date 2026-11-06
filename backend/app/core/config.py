"Application settings: the only place environment variables are read."

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str
    jwt_secret: SecretStr
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 7
    cors_origins: list[str] = ["http://localhost:4200"]
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 10

    aws_region: str = "ap-south-1"
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    max_upload_bytes: int = 100 * 1024 * 1024
    presigned_upload_ttl_seconds: int = 900
    presigned_download_ttl_seconds: int = 300
    user_quota_bytes: int = 5 * 1024 * 1024 * 1024

    redis_url: str = "redis://localhost:6379/0"
    celery_task_soft_time_limit_seconds: int = 300
    celery_task_time_limit_seconds: int = 330
    # Must exceed the longest task including retry back-off, or Redis redelivers a running task.
    celery_visibility_timeout_seconds: int = 1800
    processing_max_retries: int = 5
    processing_job_stale_seconds: int = 900
    sweeper_interval_seconds: int = 300
    sweeper_stuck_after_seconds: int = 600
    sweeper_batch_size: int = 100
    s3_connect_timeout_seconds: int = 5
    s3_read_timeout_seconds: int = 30
    s3_max_attempts: int = 3
    allowed_content_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
    ]

    @field_validator(
        "aws_access_key_id", "aws_secret_access_key", "s3_bucket", "s3_endpoint_url", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # An empty `KEY=` line in .env means "not configured", not an empty credential.
        return None if value == "" else value

    @field_validator("jwt_secret")
    @classmethod
    def _require_strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value

    @property
    def is_local(self) -> bool:
        return self.environment in ("development", "test")

    @property
    def cookie_secure(self) -> bool:
        # Fail closed: anything that is not explicitly local gets Secure cookies.
        return not self.is_local

    @property
    def docs_enabled(self) -> bool:
        return self.is_local


@lru_cache
def get_settings() -> Settings:
    return Settings()
