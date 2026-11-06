import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.processing.constants import JobStage
from app.modules.processing.extraction.chunking import Section, chunk_sections, clean_text
from app.modules.processing.models import DocumentChunk
from app.modules.processing.pipeline import run_pipeline
from app.modules.storage.s3 import S3Storage
from tests.documents import make_docx, make_pdf, make_xlsx, make_zip_bomb
from tests.test_pipeline import PDF_TYPE, _jobs, _status, _upload

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _chunks(session: Session) -> list[DocumentChunk]:
    session.expire_all()
    return list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))


def _run(client, make_user, s3_client, dispatcher, session, storage, body, content_type, name):
    file_id, _ = _upload(client, make_user(), s3_client, body, content_type, name)
    run_pipeline(session, storage, dispatcher.calls[-1])
    return file_id


class TestExtraction:
    def test_pdf_storesChunksWithPageNumbers(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        body = make_pdf(["alpha page", "beta page"])
        file_id = _run(
            client, make_user, s3_client, dispatcher, session, storage, body, PDF_TYPE, "a.pdf"
        )
        assert _status(session, file_id) == "processing"
        assert [(c.page, c.content) for c in _chunks(session)] == [
            (1, "alpha page"),
            (2, "beta page"),
        ]

    def test_rerun_replacesChunksWithoutDuplicates(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        self._first = _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            make_pdf(["once"]),
            PDF_TYPE,
            "a.pdf",
        )
        from app.modules.processing.repository import PipelineRepository

        version_id = dispatcher.calls[-1]
        from app.modules.processing.extraction.chunking import Chunk

        PipelineRepository(session).replace_chunks(version_id, [Chunk(0, 1, "once", "x" * 64)])
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 1

    def test_docx_andXlsx_areExtracted(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            make_docx(["first paragraph", "second paragraph"]),
            DOCX,
            "a.docx",
        )
        assert "second paragraph" in _chunks(session)[0].content
        _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            make_xlsx([["name", "qty"], ["apple", 3]]),
            XLSX,
            "a.xlsx",
        )
        assert any("apple\t3" in c.content for c in _chunks(session))

    def test_text_withNul_isStoredWithoutIt(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            b"hello\x0b world",
            "text/plain",
            "a.txt",
        )
        assert [c.content for c in _chunks(session)] == ["hello world"]

    @pytest.mark.parametrize(
        ("body", "content_type", "name"),
        [(make_pdf([""]), PDF_TYPE, "a.pdf"), (b"   \n ", "text/plain", "a.txt")],
    )
    def test_noText_endsInNeedsOcr(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        body: bytes,
        content_type: str,
        name: str,
    ) -> None:
        file_id = _run(
            client, make_user, s3_client, dispatcher, session, storage, body, content_type, name
        )
        assert _status(session, file_id) == "needs_ocr"
        assert _chunks(session) == []

    @pytest.mark.parametrize(
        ("body", "content_type", "name"),
        [
            (make_zip_bomb("word/document.xml"), DOCX, "a.docx"),
            (make_zip_bomb("xl/workbook.xml"), XLSX, "a.xlsx"),
        ],
    )
    def test_zipBomb_isRejected(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        body: bytes,
        content_type: str,
        name: str,
    ) -> None:
        file_id = _run(
            client, make_user, s3_client, dispatcher, session, storage, body, content_type, name
        )
        assert _status(session, file_id) == "failed"
        assert _jobs(session)[JobStage.EXTRACT].error_code == "too_large_to_extract"

    def test_corruptPdf_failsWithACode(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        file_id = _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            b"%PDF-1.7\ngarbage",
            PDF_TYPE,
            "a.pdf",
        )
        assert _status(session, file_id) == "failed"
        assert _jobs(session)[JobStage.EXTRACT].error_code == "corrupt_file"


class TestChunking:
    def test_isDeterministicAndOverlaps(self) -> None:
        text = " ".join(f"word{i}" for i in range(400))
        first = chunk_sections([Section(None, text)], 200, 30)
        assert first == chunk_sections([Section(None, text)], 200, 30)
        assert [c.index for c in first] == list(range(len(first)))
        assert all(len(c.content) <= 200 for c in first)
        assert " ".join(c.content for c in first).count("word0 ") >= 1

    def test_cleanText_stripsControlCharactersAndNormalisesNewlines(self) -> None:
        assert clean_text("a\x00b\r\nc\x1fd") == "ab\ncd"

    def test_sectionsKeepTheirPage(self) -> None:
        chunks = chunk_sections([Section(1, "one"), Section(2, "two")], 100, 10)
        assert [(c.page, c.index) for c in chunks] == [(1, 0), (2, 1)]
