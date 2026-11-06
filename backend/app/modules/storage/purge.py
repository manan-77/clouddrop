"""Permanent removal of data that is only waiting to be cleaned up.

Every function is bounded by `limit`, safe to run twice, and logs counts only.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, select
from sqlalchemy.orm import Session

from app.core.errors import ServiceUnavailableError
from app.modules.auth.models import RefreshToken
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion, Folder
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

# Expired tokens are kept a little longer so a late reuse of one is still recognised.
REFRESH_TOKEN_GRACE = timedelta(days=1)


@dataclass(frozen=True)
class PurgeResult:
    files: int = 0
    stale_uploads: int = 0
    folders: int = 0
    refresh_tokens: int = 0


def _purge_files(session: Session, storage: S3Storage, file_ids: list[uuid.UUID]) -> int:
    """Delete the objects first, then the rows; a storage failure keeps the rows for later."""
    removed = 0
    for file_id in file_ids:
        keys = list(
            session.scalars(select(FileVersion.s3_key).where(FileVersion.file_id == file_id))
        )
        try:
            for key in keys:
                storage.delete(key)  # deleting a missing object is not an error in S3
        except ServiceUnavailableError:
            session.rollback()
            logger.warning("Purge stopped: storage unavailable")
            break
        # Versions, jobs and chunks go with the file through ON DELETE CASCADE.
        session.execute(delete(File).where(File.id == file_id))
        session.commit()
        removed += 1
    return removed


def purge_expired(
    session: Session,
    storage: S3Storage,
    *,
    retention: timedelta,
    pending_upload_ttl: timedelta,
    limit: int,
    now: datetime | None = None,
) -> PurgeResult:
    now = now or datetime.now(UTC)

    def locked_ids(*conditions: object) -> list[uuid.UUID]:
        # SKIP LOCKED lets two overlapping runs take different rows instead of waiting.
        return list(
            session.scalars(
                select(File.id)
                .where(*conditions)  # type: ignore[arg-type]
                .order_by(File.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    deleted = locked_ids(File.deleted_at.is_not(None), File.deleted_at < now - retention)
    files = _purge_files(session, storage, deleted)
    stale = locked_ids(
        File.status == FileStatus.PENDING_UPLOAD.value,
        File.deleted_at.is_(None),
        File.created_at < now - pending_upload_ttl,
    )
    stale_uploads = _purge_files(session, storage, stale)

    # A folder can go once nothing refers to it; deeper trees clear over successive runs.
    child = Folder.__table__.alias("child")
    folder_ids = list(
        session.scalars(
            select(Folder.id)
            .where(
                Folder.deleted_at.is_not(None),
                Folder.deleted_at < now - retention,
                ~exists().where(File.folder_id == Folder.id),
                ~exists().where(child.c.parent_id == Folder.id),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    folders = 0
    if folder_ids:
        folders = cast(
            CursorResult[Any], session.execute(delete(Folder).where(Folder.id.in_(folder_ids)))
        ).rowcount
    token_ids = list(
        session.scalars(
            select(RefreshToken.id)
            .where(RefreshToken.expires_at < now - REFRESH_TOKEN_GRACE)
            .limit(limit)
        )
    )
    tokens = 0
    if token_ids:
        tokens = cast(
            CursorResult[Any],
            session.execute(delete(RefreshToken).where(RefreshToken.id.in_(token_ids))),
        ).rowcount
    session.commit()
    result = PurgeResult(files, stale_uploads, folders, tokens)
    if any((files, stale_uploads, folders, tokens)):
        logger.info(
            "Purged %d files, %d stale uploads, %d folders, %d refresh tokens",
            files,
            stale_uploads,
            folders,
            tokens,
        )
    return result
