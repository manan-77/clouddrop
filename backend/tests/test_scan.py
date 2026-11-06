import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.processing import scanner as scanner_module
from app.modules.processing.constants import JobStage, JobStatus
from app.modules.processing.pipeline import run_pipeline
from app.modules.processing.scanner import (
    ClamAvScanner,
    DisabledScanner,
    ScannerUnavailableError,
    ScanResult,
    ScanTooLargeError,
)
from app.modules.processing.stages import ScanStage, TransientStageError
from app.modules.storage.s3 import ObjectChangedError, S3Storage
from tests.conftest import BUCKET, FakeDispatcher, FakeScanner
from tests.test_pipeline import _jobs, _status, _upload

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]


class FakeClamd:
    "A tiny clamd: speaks just enough of the INSTREAM protocol to be tested against."

    def __init__(self, reply: bytes | None = b"stream: OK\0") -> None:
        self.reply = reply
        self.command = b""
        self.payload = b""
        self.frames: list[int] = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _read(self, connection: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            part = connection.recv(size - len(data))
            if not part:
                break
            data += part
        return data

    def _serve(self) -> None:
        try:
            connection, _ = self.server.accept()
        except OSError:
            return
        with connection:
            while not self.command.endswith(b"\0"):
                part = connection.recv(1)
                if not part:
                    return
                self.command += part
            while True:
                header = self._read(connection, 4)
                if len(header) < 4:
                    return
                (size,) = struct.unpack("!I", header)
                self.frames.append(size)
                if size == 0:
                    break
                self.payload += self._read(connection, size)
            if self.reply is not None:
                connection.sendall(self.reply)
                time.sleep(0.05)

    def close(self) -> None:
        self.server.close()


@pytest.fixture
def clamd() -> Iterator[Callable[[bytes | None], FakeClamd]]:
    servers: list[FakeClamd] = []

    def start(reply: bytes | None = b"stream: OK\0") -> FakeClamd:
        servers.append(FakeClamd(reply))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def _scanner(port: int, *, timeout: int = 5, max_bytes: int = 10_000) -> ClamAvScanner:
    return ClamAvScanner("127.0.0.1", port, timeout, max_bytes)


class TestClamAvScanner:
    def test_cleanFile_isReportedCleanAndTheProtocolIsFollowed(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(b"stream: OK\0")
        result = _scanner(server.port).scan(iter([b"hello ", b"", b"world"]))
        assert result == ScanResult(infected=False)
        server.thread.join(2)
        assert server.command == b"zINSTREAM\0"
        assert server.payload == b"hello world"
        assert server.frames == [6, 5, 0]  # empty chunks are skipped, a zero frame ends the stream

    def test_infectedFile_reportsTheSignature(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(b"stream: Eicar-Test-Signature FOUND\0")
        result = _scanner(server.port).scan([b"X5O!P%@AP"])
        assert result == ScanResult(infected=True, signature="Eicar-Test-Signature")

    def test_scannerSizeLimitReply_isTooLargeNotAFailureToScan(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(b"INSTREAM size limit exceeded. ERROR\0")
        with pytest.raises(ScanTooLargeError):
            _scanner(server.port).scan([b"data"])

    def test_ourOwnStreamLimit_stopsEarlyWithTooLarge(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(None)
        with pytest.raises(ScanTooLargeError):
            _scanner(server.port, max_bytes=10).scan([b"0123456", b"789abc"])

    def test_unexpectedReply_isTreatedAsUnavailableSoItIsRetried(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(b"stream: something odd ERROR\0")
        with pytest.raises(ScannerUnavailableError):
            _scanner(server.port).scan([b"data"])

    def test_connectionRefused_isUnavailable(self) -> None:
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with pytest.raises(ScannerUnavailableError):
            _scanner(port).scan([b"data"])

    def test_noAnswer_timesOutAsUnavailable(self, clamd) -> None:  # type: ignore[no-untyped-def]
        server = clamd(None)
        started = time.monotonic()
        with pytest.raises(ScannerUnavailableError):
            _scanner(server.port, timeout=1).scan([b"data"])
        assert time.monotonic() - started < 5


def test_disabledScanner_doesNotReadAnythingAndReportsClean() -> None:
    scanner = DisabledScanner()
    assert scanner.enabled is False
    assert scanner.scan(iter(())) == ScanResult(infected=False)


def test_settings_scanningCannotBeSwitchedOffOutsideLocalEnvironments() -> None:
    Settings(database_url="x", jwt_secret="a" * 32, scanner_mode="off")  # type: ignore[arg-type]
    for environment in ("staging", "production"):
        with pytest.raises(ValidationError):
            Settings(
                database_url="x",  # type: ignore[arg-type]
                jwt_secret="a" * 32,
                scanner_mode="off",
                environment=environment,
            )


def test_getScanner_buildsFromSettings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the autouse fake replaced get_scanner for the other tests
    scanner = scanner_module.get_scanner()
    assert isinstance(scanner, ClamAvScanner)
    assert (scanner.host, scanner.port) == (get_settings().clamav_host, get_settings().clamav_port)


class TestScanStage:
    def _uploaded(
        self,
        client: TestClient,
        make_user: Callable[[], Headers],
        s3_client: "S3Client",
        dispatcher: FakeDispatcher,
        headers: Headers | None = None,
    ):  # type: ignore[no-untyped-def]
        headers = headers or make_user()
        file_id, key = _upload(client, headers, s3_client)
        return headers, file_id, dispatcher.calls[-1], key

    def test_cleanFile_isStreamedToTheScannerAndPassesAllStages(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_scanner: FakeScanner,
    ) -> None:
        _, file_id, version_id, _ = self._uploaded(client, make_user, s3_client, dispatcher)
        run_pipeline(session, storage, version_id)
        assert fake_scanner.scanned == [b"%PDF-1.7\nrest of a document"]
        assert {j.status for j in _jobs(session).values()} == {JobStatus.SUCCEEDED}
        assert _status(session, file_id) == "processing"

    def test_infectedFile_endsInfectedStopsThePipelineAndCannotBeDownloaded(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_scanner: FakeScanner,
    ) -> None:
        headers, file_id, version_id, _ = self._uploaded(client, make_user, s3_client, dispatcher)
        fake_scanner.result = ScanResult(infected=True, signature="Eicar-Test-Signature")
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "infected"
        jobs = _jobs(session)
        assert jobs[JobStage.SCAN].status == JobStatus.FAILED
        assert jobs[JobStage.SCAN].error_code == "infected"
        assert "Eicar" not in (jobs[JobStage.SCAN].error_code or "")
        assert JobStage.DETECT_TYPE not in jobs
        download = client.get(f"/api/v1/files/{file_id}/download", headers=headers)
        assert download.status_code == 403
        assert download.json()["error"]["code"] == "file_infected"

    def test_scannerDown_isTransientAndTheScanIsRetriedLater(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_scanner: FakeScanner,
    ) -> None:
        _, file_id, version_id, _ = self._uploaded(client, make_user, s3_client, dispatcher)
        fake_scanner.error = ScannerUnavailableError()
        with pytest.raises(TransientStageError):
            run_pipeline(session, storage, version_id)
        assert _jobs(session)[JobStage.SCAN].status == JobStatus.PENDING
        assert _status(session, file_id) == "scanning"
        fake_scanner.error = None
        run_pipeline(session, storage, version_id)
        assert _status(session, file_id) == "processing"
        assert (
            _jobs(session)[JobStage.VERIFY_OBJECT].attempts == 1
        )  # finished stages are not redone

    def test_tooLargeToScan_failsTheFileWithAClearCode(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_scanner: FakeScanner,
    ) -> None:
        _, file_id, version_id, _ = self._uploaded(client, make_user, s3_client, dispatcher)
        fake_scanner.error = ScanTooLargeError()
        run_pipeline(session, storage, version_id)
        assert _jobs(session)[JobStage.SCAN].error_code == "too_large_to_scan"
        assert _status(session, file_id) == "failed"

    def test_scanningTurnedOff_skipsTheReadButStillRecordsTheStage(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
        fake_scanner: FakeScanner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, file_id, version_id, _ = self._uploaded(client, make_user, s3_client, dispatcher)
        fake_scanner.enabled = False

        def never(*_: object, **__: object) -> None:
            raise AssertionError("the object must not be read when scanning is off")

        monkeypatch.setattr(storage, "iter_object", never)
        run_pipeline(session, storage, version_id)
        assert _jobs(session)[JobStage.SCAN].status == JobStatus.SUCCEEDED
        assert fake_scanner.scanned == []
        assert _status(session, file_id) == "processing"

    def test_objectSwappedAfterVerify_isRejectedAsChanged(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
    ) -> None:
        _, file_id, version_id, key = self._uploaded(client, make_user, s3_client, dispatcher)
        s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"%PDF-1.7\nSWAPPED AFTER VERIFY!!!")
        run_pipeline(session, storage, version_id, stages=(ScanStage(),))
        assert _jobs(session)[JobStage.SCAN].error_code == "object_changed"
        assert _status(session, file_id) == "failed"

    def test_objectMissing_failsTheScan(
        self,
        client,
        make_user,
        s3_client,
        dispatcher,
        session: Session,
        storage: S3Storage,
    ) -> None:
        _, file_id, version_id, key = self._uploaded(client, make_user, s3_client, dispatcher)
        s3_client.delete_object(Bucket=BUCKET, Key=key)
        run_pipeline(session, storage, version_id, stages=(ScanStage(),))
        assert _jobs(session)[JobStage.SCAN].error_code == "object_missing"


class TestIterObject:
    def test_streamsInBoundedChunksThatReassembleTheObject(
        self, s3_client: "S3Client", storage: S3Storage
    ) -> None:
        body = bytes(range(256)) * 40
        s3_client.put_object(Bucket=BUCKET, Key="big", Body=body)
        stream = storage.iter_object("big", 1000)
        assert stream is not None
        chunks = list(stream)
        assert b"".join(chunks) == body
        assert max(len(chunk) for chunk in chunks) <= 1000

    def test_missingObject_returnsNone(self, storage: S3Storage) -> None:
        assert storage.iter_object("nope", 100) is None

    def test_changedObject_raisesObjectChanged(
        self, s3_client: "S3Client", storage: S3Storage
    ) -> None:
        s3_client.put_object(Bucket=BUCKET, Key="k", Body=b"first")
        with pytest.raises(ObjectChangedError):
            storage.iter_object("k", 100, if_match="0" * 32)
