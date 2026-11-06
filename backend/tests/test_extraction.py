import io
import zipfile
from dataclasses import replace

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from docx import Document
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.processing import extraction as _extraction  # noqa: F401
from app.modules.processing.constants import JobStage
from app.modules.processing.extraction import extractors
from app.modules.processing.extraction.chunking import Chunk, Section, chunk_sections, clean_text
from app.modules.processing.extraction.errors import ExtractionError, ExtractionLimits
from app.modules.processing.extraction.extractors import extract
from app.modules.processing.models import DocumentChunk
from app.modules.processing.pipeline import run_pipeline
from app.modules.processing.repository import PipelineRepository
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

    def test_rerun_replacesChunksAtomically(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            make_pdf(["one", "two", "three"]),
            PDF_TYPE,
            "a.pdf",
        )
        version_id = dispatcher.calls[-1]
        before = [(c.chunk_index, c.page, c.content, c.content_hash) for c in _chunks(session)]
        assert len(before) == 3
        repo = PipelineRepository(session)
        repo.replace_chunks(
            version_id,
            chunk_sections([Section(1, "one"), Section(2, "two"), Section(3, "three")], 1000, 150),
        )
        assert [
            (c.chunk_index, c.page, c.content, c.content_hash) for c in _chunks(session)
        ] == before
        repo.replace_chunks(version_id, chunk_sections([Section(1, "only")], 1000, 150))
        assert [c.content for c in _chunks(session)] == ["only"]
        with pytest.raises(IntegrityError), session.begin_nested():
            repo.replace_chunks(
                version_id, [Chunk(0, 1, "x", "h" * 64), Chunk(0, 1, "y", "h" * 64)]
            )
        assert [c.content for c in _chunks(session)] == ["only"]

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

    def test_text_withControlCharacter_isStoredWithoutIt(
        self, client, make_user, s3_client, dispatcher, session: Session, storage: S3Storage
    ) -> None:
        _run(
            client,
            make_user,
            s3_client,
            dispatcher,
            session,
            storage,
            b"hello\x01 world",
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
    def test_isDeterministicAndConsecutiveChunksOverlap(self) -> None:
        text = " ".join(f"word{i}" for i in range(400))
        first = chunk_sections([Section(None, text)], 200, 30)
        assert first == chunk_sections([Section(None, text)], 200, 30)
        assert [c.index for c in first] == list(range(len(first)))
        assert all(len(c.content) <= 200 for c in first)
        for left, right in zip(first, first[1:], strict=False):
            assert any(right.content.startswith(left.content[-n:]) for n in range(5, 31))

    def test_textWithoutWhitespace_isHardCutAndTerminates(self) -> None:
        chunks = chunk_sections([Section(None, "x" * 5000)], 1000, 150)
        assert 5 <= len(chunks) <= 7 and all(len(c.content) <= 1000 for c in chunks)

    def test_emptyAndWhitespaceInput_givesNoChunks(self) -> None:
        assert chunk_sections([Section(None, ""), Section(None, " \n\t ")], 100, 10) == []

    def test_cleanText_stripsControlCharactersAndNormalisesNewlines(self) -> None:
        assert clean_text("a\x00b\r\nc\x1fd\x0be") == "ab\ncd e"

    def test_sectionsKeepTheirPage(self) -> None:
        chunks = chunk_sections([Section(1, "one"), Section(2, "two")], 100, 10)
        assert [(c.page, c.index) for c in chunks] == [(1, 0), (2, 1)]


class TestLimits:
    LIMITS = ExtractionLimits(
        max_pages=2,
        max_chars=50,
        max_uncompressed_bytes=10_000_000,
        max_ratio=100,
        max_zip_entries=3,
        max_xml_part_bytes=1_000_000,
        max_sheets=1,
        max_cells=10,
    )

    def _code(self, content_type: str, body: bytes) -> str:
        with pytest.raises(ExtractionError) as raised:
            extract(content_type, io.BytesIO(body), self.LIMITS)
        return raised.value.code

    def test_pdf_pageAndCharacterCaps(self) -> None:
        assert self._code(PDF_TYPE, make_pdf(["a", "b", "c"])) == "too_large_to_extract"
        assert self._code(PDF_TYPE, make_pdf(["x" * 60])) == "too_large_to_extract"

    def test_xlsx_cellAndSheetCaps(self) -> None:
        assert self._code(XLSX, make_xlsx([[1] * 11])) == "too_large_to_extract"
        workbook = Workbook()
        workbook.create_sheet("second")
        buffer = io.BytesIO()
        workbook.save(buffer)
        assert self._code(XLSX, buffer.getvalue()) == "too_large_to_extract"

    def test_text_overTheCharacterCap(self) -> None:
        assert self._code("text/plain", b"x" * 60) == "too_large_to_extract"

    def test_unsupportedType(self) -> None:
        assert self._code("application/zip", b"PK") == "unsupported_type"

    def test_zip_tooManyEntriesTraversalAndWrongMember(self) -> None:
        def build(*names: str) -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name in names:
                    archive.writestr(name, b"x")
            return buffer.getvalue()

        assert self._code(DOCX, build("a", "b", "c", "d")) == "too_large_to_extract"
        assert self._code(DOCX, build("../evil", "word/document.xml")) == "corrupt_file"
        with pytest.raises(ExtractionError) as raised:
            extract(DOCX, io.BytesIO(make_xlsx([[1]])), replace(self.LIMITS, max_zip_entries=100))
        assert raised.value.code == "type_mismatch"

    def test_zip_totalUncompressedCap(self) -> None:
        limits = replace(self.LIMITS, max_uncompressed_bytes=1000, max_zip_entries=100)
        with pytest.raises(ExtractionError) as raised:
            extract(DOCX, io.BytesIO(make_docx(["x"])), limits)
        assert raised.value.code == "too_large_to_extract"

    def test_docx_hugeGridSpanTableIsCappedNotExpanded(self) -> None:
        document = Document()
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "y" * 40
        cell = table._tbl.tr_lst[0].tc_lst[0]
        cell.tcPr.get_or_add_gridSpan().val = (
            1_000_000 if hasattr(cell.tcPr, "get_or_add_gridSpan") else 1
        )
        buffer = io.BytesIO()
        document.save(buffer)
        sections = extract(
            DOCX, io.BytesIO(buffer.getvalue()), replace(self.LIMITS, max_zip_entries=100)
        )
        assert sum(len(s.text) for s in sections) < 100

    def test_overlapSetting_mustBeBelowHalfTheChunk(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, chunk_size_chars=100, chunk_overlap_chars=60)  # type: ignore[call-arg]

    def test_softTimeLimit_isNotReportedAsACorruptFile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def slow(*_: object) -> None:
            raise SoftTimeLimitExceeded

        monkeypatch.setitem(extractors._EXTRACTORS, PDF_TYPE, slow)
        with pytest.raises(SoftTimeLimitExceeded):
            extract(PDF_TYPE, io.BytesIO(b""), self.LIMITS)


def test_engine_hidesBoundParametersFromErrors() -> None:
    from app.db.session import get_engine

    assert get_engine().hide_parameters is True
