"Application settings: the only place environment variables are read."

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Longest wait between task retries; part of the visibility-timeout rule enforced below.
CELERY_RETRY_BACKOFF_MAX_SECONDS = 600


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

    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_task_soft_time_limit_seconds: int = 300
    celery_task_time_limit_seconds: int = 330
    # Must exceed the longest task including retry back-off, or Redis redelivers a running task.
    celery_visibility_timeout_seconds: int = 1800
    processing_max_retries: int = 5
    # A stage that has been claimed this many times is failed instead of retried forever.
    processing_max_attempts: int = 8
    processing_job_stale_seconds: int = 600
    sweeper_interval_seconds: int = 300
    # "off" skips malware scanning and is only accepted in local environments.
    scanner_mode: Literal["clamav", "off"] = "clamav"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    scanner_timeout_seconds: int = 30
    # Raise clamd's StreamMaxLength to at least this too; a larger file fails instead of skipping.
    scanner_max_stream_bytes: int = 100 * 1024 * 1024
    scanner_chunk_bytes: int = 64 * 1024
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

    @model_validator(mode="after")
    def _scanning_stays_on_outside_local(self) -> Self:
        if self.scanner_mode == "off" and not self.is_local:
            raise ValueError("SCANNER_MODE=off is only allowed in development and test")
        return self

    @model_validator(mode="after")
    def _worker_limits_are_consistent(self) -> Self:
        if self.celery_task_soft_time_limit_seconds >= self.celery_task_time_limit_seconds:
            raise ValueError("The soft time limit must be below the hard time limit")
        # If the broker's visibility timeout is shorter than a running task plus its retry delay,
        # Redis hands the same task to a second worker while the first is still running.
        longest = self.celery_task_time_limit_seconds + CELERY_RETRY_BACKOFF_MAX_SECONDS
        if self.celery_visibility_timeout_seconds <= longest:
            raise ValueError(f"CELERY_VISIBILITY_TIMEOUT_SECONDS must exceed {longest}")
        return self

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
