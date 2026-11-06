import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.errors import ServiceUnavailableError
from app.modules.auth.models import RefreshToken, User
from app.modules.processing.models import DocumentChunk
from app.modules.processing.pipeline import run_pipeline
from app.modules.storage.models import File, FileVersion, Folder
from app.modules.storage.purge import purge_expired
from app.modules.storage.repository import FileRepository
from app.modules.storage.s3 import S3Storage
from tests.conftest import BUCKET
from tests.test_pipeline import _upload

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

RETENTION = timedelta(days=30)
PENDING_TTL = timedelta(minutes=30)


def _purge(session: Session, storage: S3Storage, limit: int = 100):  # type: ignore[no-untyped-def]
    return purge_expired(
        session, storage, retention=RETENTION, pending_upload_ttl=PENDING_TTL, limit=limit
    )


def _exists(s3_client: "S3Client", key: str) -> bool:
    try:
        s3_client.head_object(Bucket=BUCKET, Key=key)
    except ClientError:
        return False
    return True


def _count(session: Session, model: type) -> int:
    session.expire_all()
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _soft_delete(session: Session, file_id: uuid.UUID, days: float) -> None:
    session.execute(
        update(File)
        .where(File.id == file_id)
        .values(deleted_at=datetime.now(UTC) - timedelta(days=days))
    )
    session.commit()


class TestPurgeFiles:
    def test_retentionBoundary_removesOnlyFilesDeletedLongEnoughAgo(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        headers = make_user()
        old, old_key = _upload(client, headers, s3_client)
        run_pipeline(session, storage, dispatcher.calls[-1])  # also creates chunks
        recent, recent_key = _upload(client, headers, s3_client, name="b.pdf")
        _soft_delete(session, old, 31)
        _soft_delete(session, recent, 29)
        result = _purge(session, storage)
        assert result.files == 1
        assert not _exists(s3_client, old_key) and _exists(s3_client, recent_key)
        assert session.get(File, old) is None and session.get(File, recent) is not None
        assert _count(session, DocumentChunk) == 0  # removed with the version
        assert _count(session, FileVersion) == 1

    def test_runningTwice_isANoOpTheSecondTime(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, _ = _upload(client, make_user(), s3_client)
        _soft_delete(session, file_id, 40)
        assert _purge(session, storage).files == 1
        assert _purge(session, storage).files == 0

    def test_storageDown_keepsTheRowsAndTheNextRunFinishesTheJob(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        file_id, key = _upload(client, make_user(), s3_client)
        _soft_delete(session, file_id, 40)
        real = storage.delete

        def down(_: str) -> None:
            raise ServiceUnavailableError("down", code="storage_unavailable")

        monkeypatch.setattr(storage, "delete", down)
        assert _purge(session, storage).files == 0
        assert session.get(File, file_id) is not None and _exists(s3_client, key)
        monkeypatch.setattr(storage, "delete", real)
        assert _purge(session, storage).files == 1
        assert not _exists(s3_client, key)

    def test_batchLimit_capsTheWorkPerRun(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        headers = make_user()
        for index in range(3):
            file_id, _ = _upload(client, headers, s3_client, name=f"{index}.pdf")
            _soft_delete(session, file_id, 40)
        assert _purge(session, storage, limit=2).files == 2
        assert _purge(session, storage, limit=2).files == 1


class TestRaceAndScope:
    def test_fileCompletedWhilePurgeIsRunning_isNotDeleted(
        self,
        client,
        make_user,
        s3_client,
        session: Session,
        storage: S3Storage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        headers = make_user()
        ids = []
        for name in ("a.pdf", "b.pdf"):
            init = client.post(
                "/api/v1/files/uploads",
                json={"name": name, "content_type": "application/pdf", "size_bytes": 10},
                headers=headers,
            ).json()
            ids.append(uuid.UUID(init["file"]["id"]))
        session.execute(update(File).values(created_at=text("now() - interval '2 hours'")))
        session.commit()
        real, calls = storage.delete, []

        def delete_then_complete_other(key: str) -> None:
            real(key)
            if not calls:  # while the first file is being purged, the other one is completed
                other = max(
                    ids,
                    key=lambda i: (
                        i
                        != session.scalar(
                            select(FileVersion.file_id).where(FileVersion.s3_key == key)
                        )
                    ),
                )
                session.execute(update(File).where(File.id == other).values(status="uploaded"))
                session.commit()
            calls.append(key)

        monkeypatch.setattr(storage, "delete", delete_then_complete_other)
        assert _purge(session, storage).stale_uploads == 1
        assert _count(session, File) == 1
        survivor = session.scalar(select(File))
        assert survivor is not None and survivor.status == "uploaded"

    def test_nonPendingOldFiles_areNotTreatedAsStale(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, key = _upload(client, make_user(), s3_client)
        session.execute(update(File).values(created_at=text("now() - interval '2 hours'")))
        session.commit()
        assert _purge(session, storage).stale_uploads == 0
        assert session.get(File, file_id) is not None and _exists(s3_client, key)

    def test_storageDown_onTheStalePath_keepsTheRow(
        self,
        client,
        make_user,
        s3_client,
        session: Session,
        storage: S3Storage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        init = client.post(
            "/api/v1/files/uploads",
            json={"name": "a.pdf", "content_type": "application/pdf", "size_bytes": 10},
            headers=make_user(),
        ).json()
        session.execute(update(File).values(created_at=text("now() - interval '2 hours'")))
        session.commit()

        def down(_: str) -> None:
            raise ServiceUnavailableError("down", code="storage_unavailable")

        monkeypatch.setattr(storage, "delete", down)
        assert _purge(session, storage).stale_uploads == 0
        assert session.get(File, uuid.UUID(init["file"]["id"])) is not None


class TestStaleUploads:
    def _age(self, session: Session, file_id: uuid.UUID, minutes: int) -> None:
        session.execute(
            update(File)
            .where(File.id == file_id)
            .values(created_at=text(f"now() - interval '{minutes} minutes'"))
        )
        session.commit()

    def _pending(self, client, headers, s3_client, name: str) -> tuple[uuid.UUID, str]:  # type: ignore[no-untyped-def]
        init = client.post(
            "/api/v1/files/uploads",
            json={"name": name, "content_type": "application/pdf", "size_bytes": 10},
            headers=headers,
        ).json()
        return uuid.UUID(init["file"]["id"]), init["upload"]["fields"]["key"]

    def test_abandonedPendingUploads_areRemovedWithTheirObjectAndFreshOnesAreNot(
        self, client, make_user, s3_client, session: Session, storage: S3Storage
    ) -> None:
        headers = make_user()
        stale, stale_key = self._pending(client, headers, s3_client, "stale.pdf")
        fresh, _ = self._pending(client, headers, s3_client, "fresh.pdf")
        s3_client.put_object(Bucket=BUCKET, Key=stale_key, Body=b"x" * 10)
        self._age(session, stale, 120)
        assert _purge(session, storage).stale_uploads == 1
        assert session.get(File, stale) is None and session.get(File, fresh) is not None
        assert not _exists(s3_client, stale_key)

    def test_abandonedPendingUploads_stopCountingTowardTheQuota(
        self, client, make_user, s3_client, session: Session
    ) -> None:
        headers = make_user()
        stale, _ = self._pending(client, headers, s3_client, "stale.pdf")
        self._pending(client, headers, s3_client, "fresh.pdf")
        self._age(session, stale, 120)
        workspace_id = session.scalar(select(File.workspace_id))
        assert workspace_id is not None
        repo = FileRepository(session)
        assert repo.sum_size(workspace_id) == 20
        assert repo.sum_size(workspace_id, datetime.now(UTC) - PENDING_TTL) == 10


class TestOtherData:
    def test_expiredRefreshTokens_areRemovedAfterTheGracePeriod(
        self, client, make_user, session: Session, storage: S3Storage
    ) -> None:
        make_user()
        user_id = session.scalar(select(User.id))
        assert user_id is not None
        now = datetime.now(UTC)
        for index, delta in enumerate([timedelta(days=-2), timedelta(hours=-1), timedelta(days=1)]):
            session.add(
                RefreshToken(
                    user_id=user_id,
                    family_id=uuid.uuid4(),
                    token_hash=f"{index:064d}",
                    expires_at=now + delta,
                )
            )
        session.commit()
        before = _count(session, RefreshToken)
        assert _purge(session, storage).refresh_tokens == 1
        assert _count(session, RefreshToken) == before - 1

    def test_moreExpiredTokensThanTheBatch_areAllRemoved(
        self, client, make_user, session: Session, storage: S3Storage
    ) -> None:
        make_user()
        user_id = session.scalar(select(User.id))
        assert user_id is not None
        old = datetime.now(UTC) - timedelta(days=5)
        session.add_all(
            RefreshToken(
                user_id=user_id, family_id=uuid.uuid4(), token_hash=f"{i:064d}", expires_at=old
            )
            for i in range(25)
        )
        session.commit()
        live = _count(session, RefreshToken) - 25
        assert _purge(session, storage, limit=10).refresh_tokens == 25
        assert _count(session, RefreshToken) == live

    def test_beatSchedule_includesThePurgeTask(self) -> None:
        from app.worker.celery_app import celery_app

        tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
        assert "storage.purge_expired" in tasks

    def test_deletedFolders_goOnceEmptyAndLeavesGoFirst(
        self, client, make_user, session: Session, storage: S3Storage
    ) -> None:
        headers = make_user()
        parent = client.post("/api/v1/folders", json={"name": "p"}, headers=headers).json()["id"]
        child = client.post(
            "/api/v1/folders", json={"name": "c", "parent_id": parent}, headers=headers
        ).json()["id"]
        old = datetime.now(UTC) - timedelta(days=40)
        session.execute(update(Folder).values(deleted_at=old))
        session.commit()
        assert _purge(session, storage).folders == 1  # the leaf
        assert session.get(Folder, uuid.UUID(child)) is None
        assert _purge(session, storage).folders == 1  # then its parent
        assert _count(session, Folder) == 0
