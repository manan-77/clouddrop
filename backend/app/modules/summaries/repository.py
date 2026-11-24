import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.db.soft_delete import only_active
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion
from app.modules.summaries.constants import SummaryStatus
from app.modules.summaries.draft import SummaryDraft
from app.modules.summaries.models import FileSummary


class SummaryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_version_id(self, file_id: uuid.UUID) -> uuid.UUID | None:
        return self.session.scalar(
            select(FileVersion.id)
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version.desc())
            .limit(1)
        )

    def get(self, version_id: uuid.UUID) -> FileSummary | None:
        return self.session.scalar(
            select(FileSummary).where(FileSummary.file_version_id == version_id)
        )

    def ensure(self, version_id: uuid.UUID, now: datetime) -> bool:
        """Asks for a summary if none was asked for. True when this call created the request."""
        created = self.session.execute(
            insert(FileSummary)
            .values(
                file_version_id=version_id, status=SummaryStatus.PENDING.value, requested_at=now
            )
            .on_conflict_do_nothing(index_elements=[FileSummary.file_version_id])
            .returning(FileSummary.id)
        ).first()
        return created is not None

    def request_again(self, version_id: uuid.UUID, now: datetime) -> bool:
        """Someone asked for a new summary. True when it is newly pending (so it must be queued);
        False when one is already waiting, so asking twice does not run it twice."""
        values = {
            "status": SummaryStatus.PENDING.value,
            "attempts": 0,
            "error_code": None,
            "requested_at": now,
        }
        changed = self.session.execute(
            insert(FileSummary)
            .values(file_version_id=version_id, **values)
            .on_conflict_do_update(
                index_elements=[FileSummary.file_version_id],
                set_=values,
                where=FileSummary.status != SummaryStatus.PENDING.value,
            )
            .returning(FileSummary.id)
        ).first()
        return changed is not None

    def claim(self, version_id: uuid.UUID) -> FileSummary | None:
        """Counts this attempt on a waiting request; None if there is nothing waiting."""
        return self.session.scalar(
            update(FileSummary)
            .where(
                FileSummary.file_version_id == version_id,
                FileSummary.status == SummaryStatus.PENDING.value,
            )
            .values(attempts=FileSummary.attempts + 1)
            .returning(FileSummary)
        )

    def finish(
        self,
        version_id: uuid.UUID,
        draft: SummaryDraft,
        *,
        partial: bool,
        model: str,
        prompt_version: str,
        now: datetime,
    ) -> None:
        self.session.execute(
            update(FileSummary)
            .where(FileSummary.file_version_id == version_id)
            .values(
                status=SummaryStatus.READY.value,
                summary=draft.summary,
                category=draft.category,
                tags=draft.tags,
                partial=partial,
                model=model,
                prompt_version=prompt_version,
                error_code=None,
                generated_at=now,
            )
        )

    def fail(self, version_id: uuid.UUID, code: str) -> None:
        self.session.execute(
            update(FileSummary)
            .where(FileSummary.file_version_id == version_id)
            .values(status=SummaryStatus.FAILED.value, error_code=code)
        )

    def ready_versions_without_request(self, limit: int) -> list[uuid.UUID]:
        """Newest versions of ready, undeleted files that nobody ever asked a summary for."""
        newer = aliased(FileVersion)  # an alias, or the subquery correlates away its own table
        newest = select(func.max(newer.version)).where(newer.file_id == File.id).scalar_subquery()
        asked = select(FileSummary.id).where(FileSummary.file_version_id == FileVersion.id)
        return list(
            self.session.scalars(
                select(FileVersion.id)
                .join(File, File.id == FileVersion.file_id)
                .where(only_active(File), File.status == FileStatus.READY.value)
                .where(FileVersion.version == newest, ~asked.exists())
                .order_by(FileVersion.created_at)
                .limit(limit)
            )
        )

    def stale_requests(self, before: datetime, limit: int) -> list[uuid.UUID]:
        """Waiting requests nobody has picked up since `before` (a lost message or a crash)."""
        return list(
            self.session.scalars(
                select(FileSummary.file_version_id)
                .where(
                    FileSummary.status == SummaryStatus.PENDING.value,
                    FileSummary.requested_at < before,
                )
                .order_by(FileSummary.requested_at)
                .limit(limit)
            )
        )

    def touch(self, version_ids: list[uuid.UUID], now: datetime) -> None:
        if version_ids:
            self.session.execute(
                update(FileSummary)
                .where(FileSummary.file_version_id.in_(version_ids))
                .values(requested_at=now)
            )
