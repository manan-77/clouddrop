import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.pagination import Page, PageParamsDep
from app.modules.auth.deps import CurrentUser
from app.modules.storage.deps import FolderServiceDep
from app.modules.storage.schemas import FolderCreate, FolderRead, FolderUpdate

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


@router.get("", response_model=Page[FolderRead], status_code=status.HTTP_200_OK)
def list_folders(
    user: CurrentUser,
    service: FolderServiceDep,
    params: PageParamsDep,
    parent_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[FolderRead]:
    folders, total = service.list_folders(user.id, parent_id, params)
    return Page[FolderRead](
        items=[FolderRead.model_validate(folder) for folder in folders],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=FolderRead, status_code=status.HTTP_201_CREATED)
def create_folder(
    body: FolderCreate, response: Response, user: CurrentUser, service: FolderServiceDep
) -> FolderRead:
    folder = service.create_folder(user.id, body.name, body.parent_id)
    response.headers["Location"] = f"/api/v1/folders/{folder.id}"
    return FolderRead.model_validate(folder)


@router.get("/{folder_id}", response_model=FolderRead, status_code=status.HTTP_200_OK)
def get_folder(folder_id: uuid.UUID, user: CurrentUser, service: FolderServiceDep) -> FolderRead:
    return FolderRead.model_validate(service.get_folder(user.id, folder_id))


@router.patch("/{folder_id}", response_model=FolderRead, status_code=status.HTTP_200_OK)
def rename_folder(
    folder_id: uuid.UUID, body: FolderUpdate, user: CurrentUser, service: FolderServiceDep
) -> FolderRead:
    return FolderRead.model_validate(service.rename_folder(user.id, folder_id, body.name))


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: uuid.UUID, user: CurrentUser, service: FolderServiceDep) -> None:
    service.delete_folder(user.id, folder_id)
