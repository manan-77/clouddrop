from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.deps import SessionDep, SettingsDep
from app.modules.processing.dispatcher import ProcessingDispatcher, get_dispatcher
from app.modules.storage.factory import build_storage
from app.modules.storage.file_service import FileService
from app.modules.storage.folder_service import FolderService
from app.modules.storage.s3 import S3Storage


def get_storage(settings: SettingsDep) -> S3Storage:
    return build_storage(settings)


def get_folder_service(session: SessionDep) -> FolderService:
    return FolderService(session)


def get_file_service(
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: Annotated[ProcessingDispatcher, Depends(get_dispatcher)],
) -> FileService:
    return FileService(session, settings, dispatcher)


FolderServiceDep = Annotated[FolderService, Depends(get_folder_service)]
# Only the routes that really talk to S3 declare this, so listing, renaming and deleting work
# even while no bucket is configured.
StorageDep = Annotated[S3Storage, Depends(get_storage)]
FileServiceDep = Annotated[FileService, Depends(get_file_service)]
