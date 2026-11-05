import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.pagination import Page, PageParamsDep
from app.modules.auth.deps import CurrentUser
from app.modules.storage.constants import FileStatus
from app.modules.storage.deps import FileServiceDep
from app.modules.storage.schemas import (
    DownloadResponse,
    FileRead,
    FileUpdate,
    FileUploadRequest,
    UploadInitResponse,
    UploadInstructions,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])


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
        items=[FileRead.model_validate(file) for file in files],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("/uploads", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
def init_upload(
    body: FileUploadRequest, response: Response, user: CurrentUser, service: FileServiceDep
) -> UploadInitResponse:
    file, upload = service.init_upload(
        user.id, body.name, body.content_type, body.size_bytes, body.folder_id
    )
    response.headers["Location"] = f"/api/v1/files/{file.id}"
    return UploadInitResponse(
        file=FileRead.model_validate(file),
        upload=UploadInstructions(
            url=upload.url, fields=upload.fields, expires_in=upload.expires_in
        ),
    )


@router.post("/{file_id}/uploads/complete", response_model=FileRead, status_code=status.HTTP_200_OK)
def complete_upload(file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep) -> FileRead:
    return FileRead.model_validate(service.complete_upload(user.id, file_id))


@router.get("/{file_id}", response_model=FileRead, status_code=status.HTTP_200_OK)
def get_file(file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep) -> FileRead:
    return FileRead.model_validate(service.get_file(user.id, file_id))


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
    return FileRead.model_validate(file)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep) -> None:
    service.delete_file(user.id, file_id)


@router.get("/{file_id}/download", response_model=DownloadResponse, status_code=status.HTTP_200_OK)
def download_file(
    file_id: uuid.UUID, user: CurrentUser, service: FileServiceDep
) -> DownloadResponse:
    url, expires_in = service.create_download_url(user.id, file_id)
    return DownloadResponse(url=url, expires_in=expires_in)
