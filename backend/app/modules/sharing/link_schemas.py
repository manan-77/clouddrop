import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShareLinkCreate(BaseModel):
    # The upper bound is a setting, checked in one place by the service (`link_too_long`).
    expires_in_days: int = Field(default=7, ge=1)


class ShareLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class ShareLinkCreated(ShareLinkRead):
    # Shown once, here only. Only a hash is stored, so it cannot be shown again.
    token: str


class LinkTokenBody(BaseModel):
    # In the body, not the URL, so the secret never lands in an access log. No minimum length:
    # a short token must get the same 404 as any other unusable one, after the rate limit.
    token: str = Field(max_length=200)


class PublicLinkRead(BaseModel):
    file_name: str
    size_bytes: int
    content_type: str
    expires_at: datetime


class PublicDownload(BaseModel):
    url: str
    expires_in: int
