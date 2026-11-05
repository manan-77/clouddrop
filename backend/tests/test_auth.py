import uuid

from fastapi.testclient import TestClient

PASSWORD = "a-long-test-password"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def _register(client: TestClient, email: str | None = None) -> str:
    email = email or _email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201, response.text
    return email


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def test_register_validData_returns201WithLocationAndNoSecrets(client: TestClient) -> None:
    email = _email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email.upper(), "password": PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/api/v1/auth/me"
    body = response.json()
    assert body["email"] == email
    assert "password" not in response.text and "hash" not in response.text


def test_register_duplicateEmailDifferentCase_returns409(client: TestClient) -> None:
    email = _register(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email.upper(), "password": PASSWORD, "display_name": "Other"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_register_shortPassword_returns422WithoutEchoingPassword(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": _email(), "password": "short-pw", "display_name": "X"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "password"
    assert "short-pw" not in response.text


def test_login_validCredentials_returnsTokenAndHttpOnlyCookie(client: TestClient) -> None:
    email = _register(client)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie
    assert "refresh_token" not in response.text


def test_login_wrongPasswordAndUnknownUser_returnSameGenericError(client: TestClient) -> None:
    email = _register(client)
    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password!"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": _email(), "password": "wrong-password!"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_me_validToken_returnsCurrentUser(client: TestClient) -> None:
    email = _register(client)
    token = _login(client, email)["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == email


def test_me_noOrGarbageToken_returns401(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    bad = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    assert bad.headers["www-authenticate"] == "Bearer"


def test_refresh_validCookie_rotatesAndOldTokenIsDead(client: TestClient) -> None:
    email = _register(client)
    _login(client, email)
    old = client.cookies.get("refresh_token")
    assert old

    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new = client.cookies.get("refresh_token")
    assert new and new != old

    replay = client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={old}"})
    assert replay.status_code == 401


def test_refresh_reusedToken_revokesWholeFamily(client: TestClient) -> None:
    email = _register(client)
    _login(client, email)
    old = client.cookies.get("refresh_token")
    client.post("/api/v1/auth/refresh")
    newest = client.cookies.get("refresh_token")

    assert (
        client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={old}"}).status_code
        == 401
    )
    after_theft = client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={newest}"})
    assert after_theft.status_code == 401


def test_refresh_noCookie_returns401(client: TestClient) -> None:
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_validCookie_returns204AndRefreshStopsWorking(client: TestClient) -> None:
    email = _register(client)
    _login(client, email)
    token = client.cookies.get("refresh_token")

    assert client.post("/api/v1/auth/logout").status_code == 204
    after = client.post("/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={token}"})
    assert after.status_code == 401


def test_errorEnvelope_unknownRoute_usesSharedShapeAndRequestId(client: TestClient) -> None:
    response = client.get("/api/v1/nope", headers={"X-Request-ID": "abc-123"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == "abc-123"
    assert response.headers["x-request-id"] == "abc-123"


def test_health_liveAndReady_returnOk(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
