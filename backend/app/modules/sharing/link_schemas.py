import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ShareLinkCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=365)


class ShareLinkRead(BaseModel):
    id: uuid.UUID
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class ShareLinkCreated(ShareLinkRead):
    # Shown once, here only. Only a hash is stored, so it cannot be shown again.
    token: str


class LinkTokenBody(BaseModel):
    # In the body, not the URL, so the secret never lands in an access log.
    token: str = Field(min_length=20, max_length=200)


class PublicLinkRead(BaseModel):
    file_name: str
    size_bytes: int
    content_type: str
    expires_at: datetime


class PublicDownload(BaseModel):
    url: str
    expires_in: int
