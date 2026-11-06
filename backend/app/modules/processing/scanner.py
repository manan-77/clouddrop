"""Malware scanning through clamd's INSTREAM protocol (plain TCP, no extra dependency)."""

import logging
import re
import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_CLEAN_REPLY = "stream: OK"
_FOUND_REPLY = re.compile(r"^stream: (?P<signature>.+) FOUND$")
_MAX_REPLY_BYTES = 4096


@dataclass(frozen=True)
class ScanResult:
    infected: bool
    signature: str | None = None


class ScannerUnavailableError(Exception):
    """clamd could not be reached or answered with an error; the scan is retried later."""


class ScanTooLargeError(Exception):
    """The file is larger than the scanner accepts. It is failed, never silently skipped."""


class Scanner(Protocol):
    enabled: bool

    def scan(self, chunks: Iterable[bytes]) -> ScanResult: ...


class DisabledScanner:
    """Local development only (rejected outside development and test by the settings)."""

    enabled = False

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        return ScanResult(infected=False)


class ClamAvScanner:
    enabled = True

    def __init__(self, host: str, port: int, timeout_seconds: int, max_stream_bytes: int) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.max_stream_bytes = max_stream_bytes

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), self.timeout_seconds) as sock:
                sock.settimeout(self.timeout_seconds)
                sock.sendall(b"zINSTREAM\0")
                sent = 0
                for chunk in chunks:
                    if not chunk:
                        continue
                    sent += len(chunk)
                    if sent > self.max_stream_bytes:
                        raise ScanTooLargeError
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                sock.sendall(struct.pack("!I", 0))
                reply = self._read_reply(sock)
        except OSError as exc:  # refused, reset, timed out
            raise ScannerUnavailableError from exc
        return self._interpret(reply)

    @staticmethod
    def _read_reply(sock: socket.socket) -> str:
        """A complete NUL-terminated reply, or ScannerUnavailableError: never a partial one.

        A reply cut short must not be interpreted at all (a signature name can end in "OK").
        """
        data = b""
        while len(data) < _MAX_REPLY_BYTES:
            part = sock.recv(1024)
            if not part:  # closed before the reply was complete
                raise ScannerUnavailableError
            data += part
            if data.endswith(b"\0"):
                return data.rstrip(b"\0").decode("utf-8", errors="replace").strip()
        raise ScannerUnavailableError

    @staticmethod
    def _interpret(reply: str) -> ScanResult:
        # Exact matches only: anything unrecognised is "unavailable", never "clean".
        if reply == _CLEAN_REPLY:
            return ScanResult(infected=False)
        found = _FOUND_REPLY.match(reply)
        if found:
            return ScanResult(infected=True, signature=found.group("signature"))
        if "size limit exceeded" in reply.lower():
            raise ScanTooLargeError
        logger.warning("clamd returned an unexpected reply")  # not logged: it may echo data
        raise ScannerUnavailableError


@lru_cache
def _build(mode: str, host: str, port: int, timeout: int, max_bytes: int) -> Scanner:
    if mode == "off":
        logger.warning(
            "Malware scanning is OFF (SCANNER_MODE=off); do not use this outside development"
        )
        return DisabledScanner()
    return ClamAvScanner(host, port, timeout, max_bytes)


def get_scanner() -> Scanner:
    settings = get_settings()
    return _build(
        settings.scanner_mode,
        settings.clamav_host,
        settings.clamav_port,
        settings.scanner_timeout_seconds,
        settings.scanner_max_stream_bytes,
    )
