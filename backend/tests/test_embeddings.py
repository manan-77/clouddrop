import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, LocalEmbedder
from app.core.config import get_settings
from app.modules.processing.constants import JobStage, JobStatus
from app.modules.processing.models import ChunkEmbedding, DocumentChunk
from app.modules.processing.pipeline import run_pipeline
from app.modules.processing.repository import PipelineRepository
from app.modules.processing.stages import EmbedStage, TransientStageError
from app.modules.storage.s3 import S3Storage
from tests.conftest import FakeEmbedder
from tests.documents import make_pdf
from tests.test_pipeline import PDF_TYPE, _jobs, _status, _upload


def _count(session: Session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(ChunkEmbedding)) or 0


def _processed(client, make_user, s3_client, dispatcher, session, storage, pages=("a", "b", "c")):
    file_id, _ = _upload(client, make_user(), s3_client, make_pdf(list(pages)), PDF_TYPE, "a.pdf")
    version_id = dispatcher.calls[-1]
    run_pipeline(session, storage, version_id)
    return file_id, version_id


class TestEmbedStage:
    def test_everyChunkGetsOneVectorWithItsModelAndSize_andTheFileIsReady(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id, _ = _processed(client, make_user, s3_client, dispatcher, session, storage)
        assert _status(session, file_id) == "ready"
        rows = list(session.scalars(select(ChunkEmbedding)))
        assert len(rows) == 3
        assert {row.model for row in rows} == {EMBEDDING_MODEL}
        assert {row.dim for row in rows} == {EMBEDDING_DIM}
        assert all(len(row.embedding) == EMBEDDING_DIM for row in rows)
        assert {row.chunk_id for row in rows} == set(session.scalars(select(DocumentChunk.id)))

    def test_chunksAreEmbeddedInBatchesOfTheConfiguredSize(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_embedder: FakeEmbedder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
        _processed(client, make_user, s3_client, dispatcher, session, storage, pages=list("abcde"))
        assert [len(batch) for batch in fake_embedder.document_batches] == [2, 2, 1]
        assert _count(session) == 5

    def test_rerun_rewritesTheVectorsInsteadOfDuplicatingThem(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _, version_id = _processed(client, make_user, s3_client, dispatcher, session, storage)
        repo = PipelineRepository(session)
        version = repo.get_version(version_id)
        assert version is not None
        file = repo.get_active_file(version.file_id)
        assert file is not None
        EmbedStage().run(file, version, storage, session)
        EmbedStage().run(file, version, storage, session)
        assert _count(session) == 3

    def test_vectorOfTheWrongSize_failsTheFileAndWritesNothing(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_embedder: FakeEmbedder,
    ) -> None:
        fake_embedder.vector_size = 10
        file_id, _ = _processed(client, make_user, s3_client, dispatcher, session, storage)
        assert _status(session, file_id) == "failed"
        job = _jobs(session)[JobStage.EMBED]
        assert job.status == JobStatus.FAILED
        assert job.error_code == "embedding_dimension_mismatch"
        assert _count(session) == 0

    def test_embedderThatDeclaresAnotherSize_isRefusedBeforeAnyWork(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_embedder: FakeEmbedder,
    ) -> None:
        fake_embedder.dim = 768
        file_id, _ = _processed(client, make_user, s3_client, dispatcher, session, storage)
        assert _status(session, file_id) == "failed"
        assert fake_embedder.document_batches == []

    def test_embedderDown_isRetriedAndTheFileStaysProcessing(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_embedder: FakeEmbedder,
    ) -> None:
        fake_embedder.error = RuntimeError("model could not load")
        file_id, _ = _upload(client, make_user(), s3_client, make_pdf(["a"]), PDF_TYPE, "a.pdf")
        version_id = dispatcher.calls[-1]
        with pytest.raises(TransientStageError):
            run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "processing"
        assert _jobs(session)[JobStage.EMBED].status == JobStatus.PENDING
        fake_embedder.error = None
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "ready"
        assert _jobs(session)[JobStage.EMBED].attempts == 2
        assert _jobs(session)[JobStage.EXTRACT].attempts == 1


class TestStorage:
    def test_replacingChunks_removesTheirVectors(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _, version_id = _processed(client, make_user, s3_client, dispatcher, session, storage)
        assert _count(session) == 3
        PipelineRepository(session).replace_chunks(version_id, [])
        assert _count(session) == 0

    def test_aChunkHasAtMostOneVector(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _processed(client, make_user, s3_client, dispatcher, session, storage)
        existing = session.scalars(select(ChunkEmbedding)).first()
        assert existing is not None
        session.add(
            ChunkEmbedding(
                chunk_id=existing.chunk_id,
                model="x",
                dim=EMBEDDING_DIM,
                embedding=[0.0] * EMBEDDING_DIM,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_aVectorOfAnotherSize_isRejectedByTheDatabase(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _processed(client, make_user, s3_client, dispatcher, session, storage)
        chunk_id = session.scalars(select(DocumentChunk.id)).first()
        session.rollback()
        session.add(
            ChunkEmbedding(chunk_id=chunk_id or uuid.uuid4(), model="x", dim=3, embedding=[1, 2, 3])
        )
        with pytest.raises(Exception, match="dimension"):
            session.flush()


@pytest.mark.skipif(
    not os.environ.get("RUN_LOCAL_MODEL_TESTS"),
    reason="downloads the real model (~70 MB); set RUN_LOCAL_MODEL_TESTS=1 to run",
)
class TestRealLocalModel:
    def test_vectorsHaveTheDeclaredSize_andTheRelevantPassageRanksFirst(self) -> None:
        embedder = LocalEmbedder(get_settings().embedding_cache_dir or None)
        passages = ["The invoice is due on 5 March.", "Support is open 9 to 5."]
        vectors = embedder.embed_documents(passages)
        query = embedder.embed_query("when must the bill be paid")
        assert len(query) == EMBEDDING_DIM and all(len(v) == EMBEDDING_DIM for v in vectors)
        scores = [sum(a * b for a, b in zip(query, vector, strict=True)) for vector in vectors]
        assert scores[0] > scores[1]
