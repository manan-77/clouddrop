import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

GrantRole = Literal["viewer", "editor"]


class GrantCreate(BaseModel):
    email: EmailStr = Field(max_length=320)
    role: GrantRole


class GrantUpdate(BaseModel):
    role: GrantRole


class GrantRead(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: GrantRole
    created_at: datetime


class SharedItem(BaseModel):
    resource_type: Literal["file", "folder"]
    id: uuid.UUID
    name: str
    role: GrantRole
    owner_name: str
    updated_at: datetime
    size_bytes: int | None
    content_type: str | None
    status: str | None
