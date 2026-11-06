"""Permanent removal of data that is only waiting to be cleaned up.

Every function is bounded by `limit`, safe to run twice, and logs counts only.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ServiceUnavailableError
from app.modules.auth.models import RefreshToken
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion, Folder
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

# Expired tokens are kept a little longer so a late reuse of one is still recognised.
REFRESH_TOKEN_GRACE = timedelta(days=1)
MAX_TOKEN_BATCHES = 50


@dataclass(frozen=True)
class PurgeResult:
    files: int = 0
    stale_uploads: int = 0
    folders: int = 0
    refresh_tokens: int = 0


def _purge_files(
    session: Session,
    storage: S3Storage,
    file_ids: list[uuid.UUID],
    conditions: list[ColumnElement[bool]],
) -> int:
    """Per file: lock it, re-check it is still purgeable, delete objects, then the row.

    The lock is held across the storage calls on purpose: it blocks a concurrent
    `complete_upload` (which locks the same row), so a file that just became live is never lost.
    A storage failure keeps the row for the next run.
    """
    removed = 0
    for file_id in file_ids:
        locked = session.scalar(
            select(File.id).where(File.id == file_id, *conditions).with_for_update(skip_locked=True)
        )
        if locked is None:
            session.rollback()  # changed since it was selected, or another run has it
            continue
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


def _purge_tokens(session: Session, now: datetime, batch: int) -> int:
    """Rotation creates a token per refresh, so loop in batches (bounded) to keep up."""
    total = 0
    for _ in range(MAX_TOKEN_BATCHES):
        ids = list(
            session.scalars(
                select(RefreshToken.id)
                .where(RefreshToken.expires_at < now - REFRESH_TOKEN_GRACE)
                .limit(batch)
            )
        )
        if not ids:
            break
        total += cast(
            CursorResult[Any], session.execute(delete(RefreshToken).where(RefreshToken.id.in_(ids)))
        ).rowcount
        session.commit()
        if len(ids) < batch:
            break
    return total


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

    def ids(conditions: list[ColumnElement[bool]]) -> list[uuid.UUID]:
        rows = session.scalars(
            select(File.id).where(*conditions).order_by(File.created_at).limit(limit)
        )
        return list(rows)

    deleted_conditions = [File.deleted_at.is_not(None), File.deleted_at < now - retention]
    files = _purge_files(session, storage, ids(deleted_conditions), deleted_conditions)
    stale_conditions = [
        File.status == FileStatus.PENDING_UPLOAD.value,
        File.deleted_at.is_(None),
        File.created_at < now - pending_upload_ttl,
    ]
    stale_uploads = _purge_files(session, storage, ids(stale_conditions), stale_conditions)

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
        try:
            folders = cast(
                CursorResult[Any], session.execute(delete(Folder).where(Folder.id.in_(folder_ids)))
            ).rowcount
            session.commit()
        except IntegrityError:  # something started using the folder meanwhile; try next run
            session.rollback()
            logger.warning("Folder purge skipped: a folder is in use again")
    tokens = _purge_tokens(session, now, limit)
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
