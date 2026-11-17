import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, Folder

# What the caller may do with this item; set per caller by the routers. The server still decides.
CallerRole = Literal["owner", "editor", "viewer"]


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class FolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    created_at: datetime
    updated_at: datetime
    role: CallerRole

    @classmethod
    def of(cls, folder: "Folder", role: CallerRole, *, parent_id: uuid.UUID | None) -> "FolderRead":
        # Explicit on purpose: a response cannot be built without saying what the caller may do.
        return cls(
            id=folder.id,
            parent_id=parent_id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            role=role,
        )


class FileUploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    folder_id: uuid.UUID | None = None


class FileUpdate(BaseModel):
    # An explicit `folder_id: null` moves the file to the root; omitting it leaves it alone.
    name: str | None = Field(default=None, min_length=1, max_length=255)
    folder_id: uuid.UUID | None = None


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    folder_id: uuid.UUID | None
    name: str
    content_type: str
    size_bytes: int
    status: FileStatus
    created_at: datetime
    updated_at: datetime
    role: CallerRole

    @classmethod
    def of(cls, file: "File", role: CallerRole, *, folder_id: uuid.UUID | None) -> "FileRead":
        return cls(
            id=file.id,
            folder_id=folder_id,
            name=file.name,
            content_type=file.content_type,
            size_bytes=file.size_bytes,
            status=FileStatus(file.status),
            created_at=file.created_at,
            updated_at=file.updated_at,
            role=role,
        )


class UploadInstructions(BaseModel):
    url: str
    fields: dict[str, str]
    expires_in: int


class UploadInitResponse(BaseModel):
    file: FileRead
    upload: UploadInstructions


class MultipartInstructions(BaseModel):
    part_size_bytes: int
    part_count: int
    expires_in: int


class MultipartInitResponse(BaseModel):
    file: FileRead
    multipart: MultipartInstructions


class PartUrlsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=100)


class PartUrl(BaseModel):
    part_number: int
    url: str


class PartUrlsResponse(BaseModel):
    parts: list[PartUrl]
    expires_in: int


class DownloadResponse(BaseModel):
    url: str
    expires_in: int
