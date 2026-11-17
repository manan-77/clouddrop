import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.pagination import Page, PageParamsDep
from app.modules.auth.deps import CurrentUser
from app.modules.auth.models import User
from app.modules.storage.deps import FolderServiceDep
from app.modules.storage.folder_service import FolderService
from app.modules.storage.models import Folder
from app.modules.storage.schemas import FolderCreate, FolderRead, FolderUpdate

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


def _read(
    service: FolderService, user: User, folder: Folder, *, parent_known: bool = False
) -> FolderRead:
    """The top of a shared tree does not reveal the id of a parent the caller cannot see."""
    read = FolderRead.model_validate(folder)
    if not parent_known and not service.parent_visible(user.id, folder):
        read = read.model_copy(update={"parent_id": None})
    return read


@router.get("", response_model=Page[FolderRead], status_code=status.HTTP_200_OK)
def list_folders(
    user: CurrentUser,
    service: FolderServiceDep,
    params: PageParamsDep,
    parent_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[FolderRead]:
    folders, total = service.list_folders(user.id, parent_id, params)
    return Page[FolderRead](
        items=[_read(service, user, folder, parent_known=True) for folder in folders],
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
    return _read(service, user, folder, parent_known=True)


@router.get("/{folder_id}", response_model=FolderRead, status_code=status.HTTP_200_OK)
def get_folder(folder_id: uuid.UUID, user: CurrentUser, service: FolderServiceDep) -> FolderRead:
    return _read(service, user, service.get_folder(user.id, folder_id))


@router.get("/{folder_id}/path", response_model=list[FolderRead], status_code=status.HTTP_200_OK)
def get_folder_path(
    folder_id: uuid.UUID, user: CurrentUser, service: FolderServiceDep
) -> list[FolderRead]:
    # Not paginated on purpose: the chain is bounded by MAX_FOLDER_DEPTH, root first.
    path = service.get_folder_path(user.id, folder_id)
    # Only the first element can have a hidden parent; every later one is inside the chain.
    return [_read(service, user, f, parent_known=i > 0) for i, f in enumerate(path)]


@router.patch("/{folder_id}", response_model=FolderRead, status_code=status.HTTP_200_OK)
def rename_folder(
    folder_id: uuid.UUID, body: FolderUpdate, user: CurrentUser, service: FolderServiceDep
) -> FolderRead:
    return _read(service, user, service.rename_folder(user.id, folder_id, body.name))


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: uuid.UUID, user: CurrentUser, service: FolderServiceDep) -> None:
    service.delete_folder(user.id, folder_id)
