import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.processing.constants import JobStage, JobStatus
from app.modules.processing.models import ChunkEmbedding, DocumentChunk
from app.modules.processing.pipeline import run_pipeline
from app.modules.storage.models import File
from app.modules.storage.s3 import S3Storage
from app.worker.reprocess import reprocess_ready_files
from tests.conftest import FakeDispatcher
from tests.test_pipeline import _jobs, _status, _upload

TEXT = b"First sentence is here. Second sentence follows it. Third one ends the paragraph. " * 12


def _processed(client, make_user, s3_client, dispatcher, session, storage, name="a.txt"):
    file_id, _ = _upload(client, make_user(), s3_client, TEXT, "text/plain", name)
    run_pipeline(session, storage, dispatcher.calls[-1])
    return file_id, dispatcher.calls[-1]


def _chunks(session: Session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(DocumentChunk)) or 0


class TestReprocess:
    def test_aReadyFileIsChunkedAgainWithTheCurrentSettings_andIsReadyAgain(
        self,
        client,
        make_user,
        s3_client,
        dispatcher: FakeDispatcher,
        session: Session,
        storage: S3Storage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        file_id, version_id = _processed(client, make_user, s3_client, dispatcher, session, storage)
        before = _chunks(session)
        monkeypatch.setattr(get_settings(), "chunk_size_chars", 150)
        monkeypatch.setattr(get_settings(), "chunk_overlap_chars", 30)
        dispatcher.calls.clear()
        assert reprocess_ready_files(session, dispatcher) == 1
        assert dispatcher.calls == [version_id]
        assert _status(session, file_id) == "processing"
        jobs = _jobs(session)
        assert JobStage.EXTRACT not in jobs and JobStage.EMBED not in jobs
        assert {
            jobs[s].status for s in (JobStage.VERIFY_OBJECT, JobStage.SCAN, JobStage.DETECT_TYPE)
        } == {JobStatus.SUCCEEDED}
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "ready"
        assert _chunks(session) > before  # smaller chunks now
        embeddings = session.scalar(select(func.count()).select_from(ChunkEmbedding)) or 0
        assert embeddings == _chunks(session)

    def test_filesThatAreNotReadyOrAreDeletedAreLeftAlone(
        self,
        client,
        make_user,
        s3_client,
        dispatcher: FakeDispatcher,
        session: Session,
        storage: S3Storage,
    ) -> None:
        user = make_user()
        ids = []
        for name in ("ready.txt", "failed.txt", "deleted.txt"):
            file_id, _ = _upload(client, user, s3_client, TEXT, "text/plain", name)
            run_pipeline(session, storage, dispatcher.calls[-1])
            ids.append(file_id)
        session.execute(update(File).where(File.id == ids[1]).values(status="failed"))
        session.execute(update(File).where(File.id == ids[2]).values(deleted_at=func.now()))
        session.commit()
        dispatcher.calls.clear()
        assert reprocess_ready_files(session, dispatcher) == 1
        assert _status(session, ids[0]) == "processing"
        assert _status(session, ids[1]) == "failed"

    def test_manyFilesAreQueuedOnceEach_acrossBatches(
        self,
        client,
        make_user,
        s3_client,
        dispatcher: FakeDispatcher,
        session: Session,
        storage: S3Storage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = make_user()
        versions = set()
        for index in range(5):
            _upload(client, user, s3_client, TEXT, "text/plain", f"f{index}.txt")
            versions.add(dispatcher.calls[-1])
            run_pipeline(session, storage, dispatcher.calls[-1])
        monkeypatch.setattr("app.worker.reprocess.BATCH_SIZE", 2)
        dispatcher.calls.clear()
        assert reprocess_ready_files(session, dispatcher) == 5
        assert sorted(dispatcher.calls) == sorted(versions) and len(dispatcher.calls) == 5

    def test_nothingToDo_queuesNothing(self, session: Session, dispatcher: FakeDispatcher) -> None:
        assert reprocess_ready_files(session, dispatcher) == 0
        assert dispatcher.calls == []

    def test_aFileAlreadyBeingProcessedIsNotQueuedASecondTime(
        self,
        client,
        make_user,
        s3_client,
        dispatcher: FakeDispatcher,
        session: Session,
        storage: S3Storage,
    ) -> None:
        _processed(client, make_user, s3_client, dispatcher, session, storage)
        dispatcher.calls.clear()
        assert reprocess_ready_files(session, dispatcher) == 1
        assert reprocess_ready_files(session, dispatcher) == 0  # now `processing`, not `ready`
