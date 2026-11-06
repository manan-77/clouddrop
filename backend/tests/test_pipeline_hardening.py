import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.processing.constants import JobStage, JobStatus
from app.modules.processing.dispatcher import ProcessingDispatcher
from app.modules.processing.pipeline import run_pipeline
from app.modules.processing.repository import PipelineRepository
from app.modules.processing.stages import DetectTypeStage, PermanentStageError, TransientStageError
from app.modules.processing.sweeper import sweep_stuck_files
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion
from app.modules.storage.s3 import S3Storage
from app.worker.celery_app import create_celery_app
from tests.conftest import BUCKET, FakeDispatcher
from tests.test_pipeline import _jobs, _status, _upload

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]


class Boom:
    "A stage that raises whatever it is given, to exercise the unexpected-error paths."

    name = JobStage.VERIFY_OBJECT
    file_status = FileStatus.SCANNING

    def __init__(self, error: Exception) -> None:
        self.error = error

    def run(self, file: object, version: object, storage: object) -> None:
        raise self.error


def test_completeUpload_enqueuesOnlyAfterTheFileRowIsCommitted(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    dispatcher: FakeDispatcher,
    session: Session,
) -> None:
    seen: list[str] = []

    def observe(version_id: uuid.UUID) -> None:
        session.expire_all()  # drops anything not yet written, so only committed state is visible
        status = session.scalar(
            select(File.status)
            .join(FileVersion, FileVersion.file_id == File.id)
            .where(FileVersion.id == version_id)
        )
        assert status is not None
        seen.append(status)

    dispatcher.on_enqueue = observe
    _upload(client, make_user(), s3_client)
    assert seen == ["uploaded"]


def test_enqueue_brokerUnreachable_returnsQuicklyAndWarns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unreachable = get_settings().model_copy(
        update={"redis_url": SecretStr("redis://127.0.0.1:1/0")}
    )
    dispatcher = ProcessingDispatcher(create_celery_app(unreachable))
    started = time.monotonic()
    dispatcher.enqueue(uuid.uuid4())
    assert time.monotonic() - started < 10
    assert "Could not enqueue" in caplog.text


@pytest.mark.parametrize("error", [RuntimeError("boom"), SoftTimeLimitExceeded()])
def test_unexpectedError_putsTheJobBackToPendingAndAsksForARetry(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    dispatcher: FakeDispatcher,
    session: Session,
    storage: S3Storage,
    error: Exception,
) -> None:
    file_id, _ = _upload(client, make_user(), s3_client)
    with pytest.raises(TransientStageError):
        run_pipeline(session, storage, dispatcher.calls[-1], stages=(Boom(error),))
    job = _jobs(session)[JobStage.VERIFY_OBJECT]
    assert job.status == JobStatus.PENDING and job.attempts == 1
    assert _status(session, file_id) == "scanning"


def test_poisonFile_isFailedAfterTheAttemptCapInsteadOfRetriedForever(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    dispatcher: FakeDispatcher,
    session: Session,
    storage: S3Storage,
) -> None:
    file_id, _ = _upload(client, make_user(), s3_client)
    version_id = dispatcher.calls[-1]
    for _ in range(2):
        with pytest.raises(TransientStageError):
            run_pipeline(
                session, storage, version_id, stages=(Boom(RuntimeError("x")),), max_attempts=2
            )
    run_pipeline(session, storage, version_id, stages=(Boom(RuntimeError("x")),), max_attempts=2)
    job = _jobs(session)[JobStage.VERIFY_OBJECT]
    assert job.status == JobStatus.FAILED and job.error_code == "too_many_attempts"
    assert job.attempts == 2
    assert _status(session, file_id) == "failed"


def test_claim_twiceOnTheSameJob_onlyTheFirstWins(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    dispatcher: FakeDispatcher,
    session: Session,
) -> None:
    _upload(client, make_user(), s3_client)
    repo = PipelineRepository(session)
    job = repo.ensure_job(dispatcher.calls[-1], JobStage.VERIFY_OBJECT.value)
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=15)
    assert repo.claim(job.id, now, stale) is True
    assert repo.claim(job.id, now, stale) is False


def test_objectSwappedBetweenVerifyAndRead_isRejectedByTheEtagCondition(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    dispatcher: FakeDispatcher,
    session: Session,
    storage: S3Storage,
) -> None:
    file_id, key = _upload(client, make_user(), s3_client)
    file = session.get(File, file_id)
    version = session.get(FileVersion, dispatcher.calls[-1])
    assert file is not None and version is not None
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"%PDF-9.9 swapped bytes of any size")
    with pytest.raises(PermanentStageError) as raised:
        DetectTypeStage().run(file, version, storage, session)
    assert raised.value.code == "object_changed"


class TestReadHead:
    def test_readHead_returnsOnlyTheRequestedLeadingBytes(
        self, s3_client: "S3Client", storage: S3Storage
    ) -> None:
        s3_client.put_object(Bucket=BUCKET, Key="k", Body=b"0123456789")
        assert storage.read_head("k", 4) == b"0123"

    def test_readHead_missingObject_returnsNone(self, storage: S3Storage) -> None:
        assert storage.read_head("nope", 4) is None

    def test_readHead_emptyObject_returnsEmptyBytes(
        self, s3_client: "S3Client", storage: S3Storage
    ) -> None:
        s3_client.put_object(Bucket=BUCKET, Key="empty", Body=b"")
        assert storage.read_head("empty", 4) == b""


class TestSweeperFairness:
    def _stuck_uploads(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
        session: Session,
    ) -> list[uuid.UUID]:
        headers = make_user()
        for index, minutes in enumerate((90, 60, 30)):
            file_id, _ = _upload(client, headers, s3_client, name=f"{index}.pdf")
            session.execute(
                update(File)
                .where(File.id == file_id)
                .values(updated_at=text(f"now() - interval '{minutes} minutes'"))
            )
            session.execute(
                update(FileVersion).where(FileVersion.file_id == file_id).values(enqueued_at=None)
            )
        return list(dispatcher.calls)

    def test_oldestFirst_andEachFileIsSentOncePerStuckPeriod(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
        session: Session,
    ) -> None:
        versions = self._stuck_uploads(client, make_user, s3_client, dispatcher, session)
        sent = FakeDispatcher()
        window = timedelta(minutes=10)
        assert sweep_stuck_files(session, sent, stuck_after=window, limit=2) == 2  # type: ignore[arg-type]
        assert sent.calls == versions[:2]
        # The first two were just handed to the worker, so the next sweep reaches the third.
        assert sweep_stuck_files(session, sent, stuck_after=window, limit=2) == 1  # type: ignore[arg-type]
        assert sent.calls[2:] == versions[2:]
        assert sweep_stuck_files(session, sent, stuck_after=window, limit=2) == 0  # type: ignore[arg-type]
