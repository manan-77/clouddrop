from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

import boto3
from botocore.config import Config
from fastapi import Depends

from app.core.deps import SessionDep, SettingsDep
from app.core.errors import ServiceUnavailableError
from app.modules.storage.file_service import FileService
from app.modules.storage.folder_service import FolderService
from app.modules.storage.s3 import S3Storage

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@lru_cache
def _s3_client(
    region: str,
    endpoint_url: str | None,
    access_key: str | None,
    secret_key: str | None,
    connect_timeout: int,
    read_timeout: int,
    max_attempts: int,
) -> S3Client:
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


def get_storage(settings: SettingsDep) -> S3Storage:
    if not settings.s3_bucket:
        raise ServiceUnavailableError(
            "File storage is not configured", code="storage_not_configured"
        )
    client = _s3_client(
        settings.aws_region,
        settings.s3_endpoint_url,
        settings.aws_access_key_id.get_secret_value() if settings.aws_access_key_id else None,
        settings.aws_secret_access_key.get_secret_value()
        if settings.aws_secret_access_key
        else None,
        settings.s3_connect_timeout_seconds,
        settings.s3_read_timeout_seconds,
        settings.s3_max_attempts,
    )
    return S3Storage(
        client,
        settings.s3_bucket,
        settings.presigned_upload_ttl_seconds,
        settings.presigned_download_ttl_seconds,
    )


def get_folder_service(session: SessionDep) -> FolderService:
    return FolderService(session)


def get_file_service(
    session: SessionDep,
    settings: SettingsDep,
    storage: Annotated[S3Storage, Depends(get_storage)],
) -> FileService:
    return FileService(session, settings, storage)


FolderServiceDep = Annotated[FolderService, Depends(get_folder_service)]
FileServiceDep = Annotated[FileService, Depends(get_file_service)]
