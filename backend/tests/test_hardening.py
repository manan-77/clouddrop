from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, event

from app import main as app_main
from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.modules.storage.deps import get_storage
from tests.conftest import BUCKET

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]
PDF = "application/pdf"


def _init(client: TestClient, headers: Headers, **overrides: object):  # type: ignore[no-untyped-def]
    body = {"name": "a.pdf", "content_type": PDF, "size_bytes": 10, **overrides}
    return client.post("/api/v1/files/uploads", json=body, headers=headers)


@contextmanager
def _sql_log(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def test_settings_unknownEnvironmentString_isRejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", database_url="x", jwt_secret="a" * 32)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("environment", "secure", "docs"),
    [
        ("development", False, True),
        ("test", False, True),
        ("staging", True, False),
        ("production", True, False),
    ],
)
def test_settings_environment_failsClosedForCookiesAndDocs(
    environment: str, secure: bool, docs: bool
) -> None:
    settings = Settings(environment=environment, database_url="x", jwt_secret="a" * 32)  # type: ignore[arg-type]
    assert settings.cookie_secure is secure
    assert settings.docs_enabled is docs


def test_createApp_nonLocalEnvironment_disablesDocsAndOpenapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = get_settings().model_copy(update={"environment": "staging"})
    monkeypatch.setattr(app_main, "get_settings", lambda: staging)
    with TestClient(app_main.create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_login_nonLocalEnvironment_setsSecureCookie(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    email = "secure-cookie@example.com"
    body = {"email": email, "password": "a-long-test-password", "display_name": "S"}
    client.post("/api/v1/auth/register", json=body)
    production = get_settings().model_copy(update={"environment": "production"})
    client.app.dependency_overrides[get_settings] = lambda: production  # type: ignore[attr-defined]
    login = client.post("/api/v1/auth/login", json={"email": email, "password": body["password"]})
    assert "secure" in login.headers["set-cookie"].lower()


def test_routes_everyRouteDeclaresStatusCodeAndResponseModel(client: TestClient) -> None:
    # include_router wraps each router lazily in this FastAPI version, so unwrap it.
    routes: list[APIRoute] = []
    for entry in client.app.routes:  # type: ignore[attr-defined]
        inner = entry.original_router.routes if hasattr(entry, "original_router") else [entry]
        routes.extend(r for r in inner if isinstance(r, APIRoute))
    assert len(routes) >= 19  # guards against the unwrap silently finding nothing
    for route in routes:
        assert route.status_code is not None, f"{route.path} has no explicit status_code"
        assert route.response_model is not None or route.status_code == 204, route.path


def test_pagination_hugePage_returns422NotServerError(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    response = client.get("/api/v1/folders", params={"page": 10**20}, headers=make_user())
    assert response.status_code == 422


def test_unhandledError_returnsEnvelopeWithRequestIdAndHeader() -> None:
    app = app_main.create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-500"
    error = response.json()["error"]
    assert error["code"] == "internal_error" and error["request_id"] == "req-500"
    assert "secret internal detail" not in response.text


def test_initUpload_overQuota_returns422(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    small = get_settings().model_copy(update={"user_quota_bytes": 15})
    client.app.dependency_overrides[get_settings] = lambda: small  # type: ignore[attr-defined]
    headers = make_user()
    assert _init(client, headers, size_bytes=10).status_code == 201
    second = _init(client, headers, name="b.pdf", size_bytes=10)
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "quota_exceeded"


def test_download_failedUpload_returns409(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    init = _init(client, headers, size_bytes=10).json()
    s3_client.put_object(Bucket=BUCKET, Key=init["upload"]["fields"]["key"], Body=b"x" * 99)
    file_id = init["file"]["id"]
    client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
    response = client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_not_ready"


def test_initUpload_intoDeletedFolder_returns404(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    folder = client.post("/api/v1/folders", json={"name": "Gone"}, headers=headers).json()["id"]
    assert client.delete(f"/api/v1/folders/{folder}", headers=headers).status_code == 204
    assert _init(client, headers, folder_id=folder).status_code == 404


def test_folderWrites_lockTheFolderRow(
    client: TestClient, make_user: Callable[[], Headers], engine: Engine
) -> None:
    headers = make_user()
    folder = client.post("/api/v1/folders", json={"name": "Locked"}, headers=headers).json()["id"]
    with _sql_log(engine) as upload_sql:
        _init(client, headers, folder_id=folder)
    assert any("FOR SHARE" in sql for sql in upload_sql)
    with _sql_log(engine) as delete_sql:
        # not empty now, so the delete is refused, but the row must already be locked
        client.delete(f"/api/v1/folders/{folder}", headers=headers)
    assert any("FOR UPDATE" in sql for sql in delete_sql)


def test_initUpload_presignFailure_leavesNoRows(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    def _fail(*_: object) -> None:
        raise ServiceUnavailableError("storage down", code="storage_unavailable")

    client.app.dependency_overrides[get_storage] = lambda: SimpleNamespace(create_upload=_fail)  # type: ignore[attr-defined]
    headers = make_user()
    assert _init(client, headers).status_code == 503
    listing = client.get("/api/v1/files", params={"status": "pending_upload"}, headers=headers)
    assert listing.json()["total"] == 0
