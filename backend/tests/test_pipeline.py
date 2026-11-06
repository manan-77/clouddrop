import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.errors import ServiceUnavailableError
from app.modules.processing import dispatcher as dispatcher_module
from app.modules.processing.constants import JobStage, JobStatus
from app.modules.processing.dispatcher import PROCESS_TASK, ProcessingDispatcher
from app.modules.processing.filetype import looks_like_text, matches_declared_type
from app.modules.processing.models import ProcessingJob
from app.modules.processing.pipeline import PIPELINE, run_pipeline
from app.modules.processing.stages import TransientStageError
from app.modules.processing.sweeper import sweep_stuck_files
from app.modules.storage.models import File
from app.modules.storage.s3 import S3Storage
from tests.conftest import BUCKET, FakeDispatcher

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]
PDF = b"%PDF-1.7\nrest of a document"
PDF_TYPE = "application/pdf"


def _upload(
    client: TestClient,
    headers: Headers,
    s3_client: "S3Client",
    body: bytes = PDF,
    content_type: str = PDF_TYPE,
    name: str = "a.pdf",
) -> tuple[uuid.UUID, str]:
    init = client.post(
        "/api/v1/files/uploads",
        json={"name": name, "content_type": content_type, "size_bytes": len(body)},
        headers=headers,
    ).json()
    s3_client.put_object(Bucket=BUCKET, Key=init["upload"]["fields"]["key"], Body=body)
    file_id = init["file"]["id"]
    done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
    assert done.status_code == 200, done.text
    return uuid.UUID(file_id), init["upload"]["fields"]["key"]


def _status(session: Session, file_id: uuid.UUID) -> str:
    session.expire_all()
    file = session.get(File, file_id)
    assert file is not None
    return file.status


def _jobs(session: Session) -> dict[str, ProcessingJob]:
    session.expire_all()
    return {job.stage: job for job in session.scalars(select(ProcessingJob))}


class TestEnqueue:
    def test_completeUpload_enqueuesTheVersionOnceAfterTheCommit(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
    ) -> None:
        headers = make_user()
        file_id, _ = _upload(client, headers, s3_client)
        assert len(dispatcher.calls) == 1
        client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert len(dispatcher.calls) == 1  # a repeated completion does not enqueue again

    def test_completeUpload_sizeMismatch_enqueuesNothing(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
    ) -> None:
        headers = make_user()
        init = client.post(
            "/api/v1/files/uploads",
            json={"name": "a.pdf", "content_type": PDF_TYPE, "size_bytes": 10},
            headers=headers,
        ).json()
        s3_client.put_object(Bucket=BUCKET, Key=init["upload"]["fields"]["key"], Body=PDF * 9)
        response = client.post(
            f"/api/v1/files/{init['file']['id']}/uploads/complete", headers=headers
        )
        assert response.status_code == 422
        assert dispatcher.calls == []

    def test_dispatcher_brokerDown_doesNotRaiseAndWarns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _down(*_: object, **__: object) -> None:
            raise OperationalError("broker down")

        monkeypatch.setattr(dispatcher_module.celery_app, "send_task", _down)
        with caplog.at_level(logging.WARNING):
            ProcessingDispatcher().enqueue(uuid.uuid4())
        assert "Could not enqueue" in caplog.text

    def test_dispatcher_sendsTheTaskNameWithAnIdOnly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[tuple[str, list[str]]] = []
        monkeypatch.setattr(
            dispatcher_module.celery_app,
            "send_task",
            lambda name, args=None, **_: sent.append((name, args or [])),
        )
        version_id = uuid.uuid4()
        ProcessingDispatcher().enqueue(version_id)
        assert sent == [(PROCESS_TASK, [str(version_id)])]


class TestPipeline:
    def _setup(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
        **kwargs: object,
    ) -> tuple[uuid.UUID, uuid.UUID, str]:
        file_id, key = _upload(client, make_user(), s3_client, **kwargs)  # type: ignore[arg-type]
        return file_id, dispatcher.calls[-1], key

    def test_validPdf_runsEveryStageAndRestsInProcessing(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "processing"
        jobs = _jobs(session)
        assert set(jobs) == {JobStage.VERIFY_OBJECT, JobStage.DETECT_TYPE}
        assert {job.status for job in jobs.values()} == {JobStatus.SUCCEEDED}
        assert all(job.attempts == 1 and job.error_code is None for job in jobs.values())

    def test_runTwice_isANoOpTheSecondTime(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)
        run_pipeline(session, storage, version_id)
        run_pipeline(session, storage, version_id)
        jobs = _jobs(session)
        assert len(jobs) == len(PIPELINE)
        assert all(job.attempts == 1 for job in jobs.values())
        assert _status(session, file_id) == "processing"

    def test_objectOverwrittenAfterCompletion_failsWithObjectChanged(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, key = self._setup(client, make_user, s3_client, dispatcher)
        s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"%PDF-9.9\nDIFFERENT BYTES!!")
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "failed"
        job = _jobs(session)[JobStage.VERIFY_OBJECT]
        assert job.status == JobStatus.FAILED and job.error_code in {
            "object_changed",
            "object_size_changed",
        }
        assert JobStage.DETECT_TYPE not in _jobs(session)

    def test_sameSizeDifferentContent_isCaughtByTheEtag(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, key = self._setup(client, make_user, s3_client, dispatcher)
        s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"%PDF-1.7\nREST OF A DOCUMENT")
        assert len(b"%PDF-1.7\nREST OF A DOCUMENT") == len(PDF)
        run_pipeline(session, storage, version_id)
        assert _jobs(session)[JobStage.VERIFY_OBJECT].error_code == "object_changed"
        assert _status(session, file_id) == "failed"

    def test_objectDeleted_failsWithObjectMissing(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, key = self._setup(client, make_user, s3_client, dispatcher)
        s3_client.delete_object(Bucket=BUCKET, Key=key)
        run_pipeline(session, storage, version_id)
        assert _jobs(session)[JobStage.VERIFY_OBJECT].error_code == "object_missing"
        assert _status(session, file_id) == "failed"

    @pytest.mark.parametrize(
        ("body", "content_type", "ok"),
        [
            (b"just some plain text\n", "text/plain", True),
            (b"a,b\n1,2\n", "text/csv", True),
            (b"text with a NUL \x00 byte", "text/plain", False),
            (b"\xff\xfe\xfa binary", "text/plain", False),
            (b"\x89PNG\r\n\x1a\nrest", "image/png", True),
            (b"%PDF-1.7 pretending", "image/png", False),
            (b"MZ\x90\x00 an executable", PDF_TYPE, False),
        ],
    )
    def test_typeDetection_acceptsMatchingContentAndRejectsTheRest(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        body: bytes,
        content_type: str,
        ok: bool,
    ) -> None:
        file_id, version_id, _ = self._setup(
            client, make_user, s3_client, dispatcher, body=body, content_type=content_type
        )
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == ("processing" if ok else "failed")
        if not ok:
            assert _jobs(session)[JobStage.DETECT_TYPE].error_code == "type_mismatch"

    def test_storageUnavailable_isTransientAndResumesLater(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)

        class Down:
            def head(self, key: str) -> None:
                raise ServiceUnavailableError("down", code="storage_unavailable")

        with pytest.raises(TransientStageError):
            run_pipeline(session, Down(), version_id)  # type: ignore[arg-type]
        assert _jobs(session)[JobStage.VERIFY_OBJECT].status == JobStatus.PENDING
        assert _status(session, file_id) == "scanning"
        run_pipeline(session, storage, version_id)  # storage is back: the same job resumes
        assert _status(session, file_id) == "processing"
        assert _jobs(session)[JobStage.VERIFY_OBJECT].attempts == 2

    def test_alreadyFailedOrDeletedOrUnknown_areSkipped(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)
        session.execute(update(File).where(File.id == file_id).values(status="failed"))
        run_pipeline(session, storage, version_id)
        assert _jobs(session) == {}
        session.execute(
            update(File)
            .where(File.id == file_id)
            .values(status="uploaded", deleted_at=text("now()"))
        )
        run_pipeline(session, storage, version_id)
        assert _jobs(session) == {}
        run_pipeline(session, storage, uuid.uuid4())

    def test_abandonedRunningJob_isReclaimedAfterTheStalePeriod(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)
        run_pipeline(session, storage, version_id, stages=PIPELINE[:1])
        session.execute(
            update(ProcessingJob).values(
                status="running", started_at=text("now() - interval '1 hour'")
            )
        )
        run_pipeline(session, storage, version_id, stale_after=timedelta(minutes=15))
        assert _jobs(session)[JobStage.VERIFY_OBJECT].status == JobStatus.SUCCEEDED
        assert _status(session, file_id) == "processing"

    def test_freshRunningJob_isLeftToItsOwnWorker(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, version_id, _ = self._setup(client, make_user, s3_client, dispatcher)
        run_pipeline(session, storage, version_id, stages=PIPELINE[:1])
        session.execute(update(ProcessingJob).values(status="running", started_at=text("now()")))
        run_pipeline(session, storage, version_id, stale_after=timedelta(minutes=15))
        assert _jobs(session)[JobStage.VERIFY_OBJECT].status == JobStatus.RUNNING
        assert JobStage.DETECT_TYPE not in _jobs(session)


class TestSweeper:
    def _age(self, session: Session, file_id: uuid.UUID, minutes: int) -> None:
        session.execute(
            update(File)
            .where(File.id == file_id)
            .values(updated_at=text(f"now() - interval '{minutes} minutes'"))
        )

    def test_stuckFiles_areReEnqueuedAndFreshOnesAreNot(
        self, client, make_user, s3_client, dispatcher, session: Session
    ) -> None:
        headers = make_user()
        stuck, _ = _upload(client, headers, s3_client)
        fresh, _ = _upload(client, headers, s3_client, name="b.pdf")
        self._age(session, stuck, 60)
        sweeper = FakeDispatcher()
        count = sweep_stuck_files(session, sweeper, stuck_after=timedelta(minutes=10), limit=100)  # type: ignore[arg-type]
        assert count == 1 and len(sweeper.calls) == 1
        assert fresh != stuck

    def test_failedDeletedAndFullyProcessedFiles_areIgnored(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        headers = make_user()
        failed, _ = _upload(client, headers, s3_client, name="f.pdf")
        deleted, _ = _upload(client, headers, s3_client, name="d.pdf")
        done, _ = _upload(client, headers, s3_client, name="ok.pdf")
        for file_id in (failed, deleted, done):
            self._age(session, file_id, 60)
        session.execute(update(File).where(File.id == failed).values(status="failed"))
        session.execute(update(File).where(File.id == deleted).values(deleted_at=text("now()")))
        run_pipeline(session, storage, dispatcher.calls[2])  # `done` finishes every stage
        self._age(session, done, 60)
        sweeper = FakeDispatcher()
        count = sweep_stuck_files(session, sweeper, stuck_after=timedelta(minutes=10), limit=100)  # type: ignore[arg-type]
        assert count == 0

    def test_batchLimit_capsTheWorkPerRun(
        self, client, make_user, s3_client, dispatcher, session: Session
    ) -> None:
        headers = make_user()
        for index in range(3):
            file_id, _ = _upload(client, headers, s3_client, name=f"{index}.pdf")
            self._age(session, file_id, 60)
        sweeper = FakeDispatcher()
        count = sweep_stuck_files(session, sweeper, stuck_after=timedelta(minutes=10), limit=2)  # type: ignore[arg-type]
        assert count == 2


class TestFileType:
    @pytest.mark.parametrize("head", [b"", b"\x00", b"caf\xc3\xa9 ok", "日本語".encode()[:-1]])
    def test_looksLikeText_acceptsEmptyUtf8AndATruncatedLastCharacter(self, head: bytes) -> None:
        assert looks_like_text(head) is (b"\x00" not in head)

    def test_matchesDeclaredType_unknownTypeIsNotAccepted(self) -> None:
        assert matches_declared_type(b"anything", "application/x-unknown") is False
