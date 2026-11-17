import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.config import Settings
from app.core.deps import SettingsDep
from app.core.pagination import Page, PageParamsDep
from app.core.ratelimit import RateLimiter, RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.auth.models import User
from app.modules.storage.constants import FileStatus
from app.modules.storage.deps import FileServiceDep, StorageDep
from app.modules.storage.file_service import FileService
from app.modules.storage.models import File
from app.modules.storage.schemas import (
    DownloadResponse,
    FileRead,
    FileUpdate,
    FileUploadRequest,
    MultipartInitResponse,
    MultipartInstructions,
    PartUrl,
    PartUrlsRequest,
    PartUrlsResponse,
    UploadInitResponse,
    UploadInstructions,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])


def _read(service: FileService, user: User, file: File, *, folder_known: bool = False) -> FileRead:
    """A file-only grantee is not told which folder holds the file."""
    read = FileRead.model_validate(file)
    if not folder_known and not service.folder_visible(user.id, file):
        read = read.model_copy(update={"folder_id": None})
    return read


def _limit_init(
    user: User,
    folder_id: uuid.UUID | None,
    service: FileService,
    limiter: RateLimiter,
    settings: Settings,
) -> None:
    # An editor's pending upload reserves the owner's quota, so those are rate limited per user.
    # An owner filling their own space is not limited.
    if not service.uploads_into_shared_folder(user.id, folder_id):
        return
    enforce(
        limiter,
        "upload-init:user",
        str(user.id),
        settings.rate_limit_upload_init_per_user,
        settings.rate_limit_upload_init_window_seconds,
    )


@router.get("", response_model=Page[FileRead], status_code=status.HTTP_200_OK)
def list_files(
    user: CurrentUser,
    service: FileServiceDep,
    params: PageParamsDep,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[FileStatus | None, Query(alias="status")] = None,
) -> Page[FileRead]:
    files, total = service.list_files(user.id, folder_id, status_filter, params)
    return Page[FileRead](
        items=[_read(service, user, file, folder_known=True) for file in files],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/uploads", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
def init_upload(
    body: FileUploadRequest,
    response: Response,
    user: CurrentUser,
    service: FileServiceDep,
    storage: StorageDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> UploadInitResponse:
    _limit_init(user, body.folder_id, service, limiter, settings)
    file, upload = service.init_upload(
        user.id, body.name, body.content_type, body.size_bytes, body.folder_id, storage
    )
    response.headers["Location"] = f"/api/v1/files/{file.id}"
    return UploadInitResponse(
        file=_read(service, user, file, folder_known=True),
        upload=UploadInstructions(
            url=upload.url, fields=upload.fields, expires_in=upload.expires_in
        ),
    )


@router.post(
    "/uploads/multipart", response_model=MultipartInitResponse, status_code=status.HTTP_201_CREATED
)
def init_multipart_upload(
    body: FileUploadRequest,
    response: Response,
    user: CurrentUser,
    service: FileServiceDep,
    storage: StorageDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> MultipartInitResponse:
    _limit_init(user, body.folder_id, service, limiter, settings)
    file, part_size, part_count = service.init_multipart_upload(
        user.id, body.name, body.content_type, body.size_bytes, body.folder_id, storage
    )
    response.headers["Location"] = f"/api/v1/files/{file.id}"
    return MultipartInitResponse(
        file=_read(service, user, file, folder_known=True),
        multipart=MultipartInstructions(
            part_size_bytes=part_size,
            part_count=part_count,
            expires_in=settings.presigned_upload_ttl_seconds,
        ),
    )


@router.post(
    "/{file_id}/uploads/parts", response_model=PartUrlsResponse, status_code=status.HTTP_200_OK
)
def create_part_urls(
    file_id: uuid.UUID,
    body: PartUrlsRequest,
    user: CurrentUser,
    service: FileServiceDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> PartUrlsResponse:
    urls = service.create_part_urls(user.id, file_id, body.part_numbers, storage)
    return PartUrlsResponse(
        parts=[PartUrl(part_number=n, url=u) for n, u in urls],
        expires_in=settings.presigned_upload_ttl_seconds,
    )


@router.delete("/{file_id}/uploads", status_code=status.HTTP_204_NO_CONTENT)
def abort_upload(
    file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep, storage: StorageDep
) -> None:
    service.abort_upload(user.id, file_id, storage)


@router.post("/{file_id}/uploads/complete", response_model=FileRead, status_code=status.HTTP_200_OK)
def complete_upload(
    file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep, storage: StorageDep
) -> FileRead:
    return _read(service, user, service.complete_upload(user.id, file_id, storage))


@router.get("/{file_id}", response_model=FileRead, status_code=status.HTTP_200_OK)
def get_file(file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep) -> FileRead:
    return _read(service, user, service.get_file(user.id, file_id))


@router.patch("/{file_id}", response_model=FileRead, status_code=status.HTTP_200_OK)
def update_file(
    file_id: uuid.UUID, body: FileUpdate, user: CurrentUser, service: FileServiceDep
) -> FileRead:
    file = service.update_file(
        user.id,
        file_id,
        name=body.name,
        folder_id=body.folder_id,
        move="folder_id" in body.model_fields_set,
    )
    return _read(service, user, file)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep) -> None:
    service.delete_file(user.id, file_id)


@router.get("/{file_id}/download", response_model=DownloadResponse, status_code=status.HTTP_200_OK)
def download_file(
    file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep, storage: StorageDep
) -> DownloadResponse:
    url, expires_in = service.create_download_url(user.id, file_id, storage)
    return DownloadResponse(url=url, expires_in=expires_in)
