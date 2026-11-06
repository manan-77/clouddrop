import logging
import time
import uuid

import pytest
import redis
from fastapi.testclient import TestClient

from app.core.ratelimit import RedisRateLimiter, enforce, ip_bucket
from tests.conftest import FakeRateLimiter

CREDENTIALS = {"email": "a@example.com", "password": "wrong-password-1"}
NO_CSRF = {"X-Requested-With": ""}


def _login(client: TestClient, email: str = "a@example.com") -> int:
    return client.post("/api/v1/auth/login", json={**CREDENTIALS, "email": email}).status_code


class TestLoginLimits:
    def test_perAccount_limitTriggersWith429AndRetryAfter(self, client: TestClient) -> None:
        statuses = [_login(client) for _ in range(10)]
        assert 429 not in statuses
        response = client.post("/api/v1/auth/login", json=CREDENTIALS)
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1
        assert response.json()["error"]["code"] == "rate_limited"

    def test_429_usesTheStandardEnvelopeWithARequestId(self, client: TestClient) -> None:
        for _ in range(10):
            _login(client)
        body = client.post("/api/v1/auth/login", json=CREDENTIALS).json()["error"]
        assert body["code"] == "rate_limited" and body["request_id"] and body["details"] == []

    def test_accountBudget_isPerClient_soAStrangerCannotLockTheOwnerOut(
        self, rate_limiter: FakeRateLimiter
    ) -> None:
        for _ in range(10):
            enforce(rate_limiter, "login:account", "victim@example.com|203.0.113.9", 10, 900)
        enforce(rate_limiter, "login:account", "victim@example.com|198.51.100.4", 10, 900)

    def test_oneAccountBeingHammered_doesNotBlockAnother(self, client: TestClient) -> None:
        for _ in range(11):
            _login(client, "victim@example.com")
        assert _login(client, "other@example.com") != 429

    def test_accountKeyIgnoresCaseAndWhitespace(self, client: TestClient) -> None:
        for _ in range(10):
            _login(client, " A@Example.com ")
        assert _login(client, "a@example.com") == 429

    def test_perIp_limitTriggersAcrossAccounts(self, client: TestClient) -> None:
        statuses = [_login(client, f"user{i}@example.com") for i in range(21)]
        assert statuses[:20].count(429) == 0 and statuses[20] == 429

    def test_register_isLimitedPerIp(self, client: TestClient) -> None:
        codes = [
            client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"n{i}@example.com",
                    "password": "correct-horse-1",
                    "display_name": "N",
                },
            ).status_code
            for i in range(11)
        ]
        assert codes[-1] == 429 and 429 not in codes[:10]

    def test_refresh_isLimitedPerIp(self, client: TestClient) -> None:
        codes = [client.post("/api/v1/auth/refresh").status_code for _ in range(61)]
        assert codes[-1] == 429 and 429 not in codes[:60]

    def test_storedKeysContainNoEmailOrAddress(
        self, client: TestClient, rate_limiter: FakeRateLimiter
    ) -> None:
        _login(client)
        assert rate_limiter.counts
        assert all(
            "example.com" not in key and "testclient" not in key for key in rate_limiter.counts
        )


class TestCsrfHeader:
    @pytest.mark.parametrize("path", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
    def test_cookieEndpoints_rejectRequestsWithoutTheHeader(
        self, client: TestClient, path: str
    ) -> None:
        response = client.post(path, headers=NO_CSRF)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_check_failed"

    def test_login_doesNotNeedTheHeader(self, client: TestClient) -> None:
        assert (
            client.post("/api/v1/auth/login", json=CREDENTIALS, headers=NO_CSRF).status_code == 401
        )


@pytest.mark.parametrize(
    ("host", "bucket"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:1::1", "2001:db8:1:2::/64"),
        ("not-an-ip", "not-an-ip"),
    ],
)
def test_ipBucket_groupsIpv6ByTheir64(host: str, bucket: str) -> None:
    assert ip_bucket(host) == bucket


@pytest.fixture
def redis_limiter() -> RedisRateLimiter:
    # Database 15 with unique keys; nothing is flushed, so shared data is never touched.
    client = redis.Redis.from_url("redis://localhost:6379/15", socket_connect_timeout=0.5)
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip("local Redis not available")
    return RedisRateLimiter(client)


class TestRedisLimiter:
    def test_countsThenBlocksThenResetsAfterTheWindow(
        self, redis_limiter: RedisRateLimiter
    ) -> None:
        key = f"rl:test:{uuid.uuid4()}"
        assert [redis_limiter.hit(key, 2, 1).allowed for _ in range(3)] == [True, True, False]
        blocked = redis_limiter.hit(key, 2, 1)
        assert not blocked.allowed and 1 <= blocked.retry_after_seconds <= 1
        time.sleep(1.2)
        assert redis_limiter.hit(key, 2, 1).allowed

    def test_separateKeysHaveSeparateBudgets(self, redis_limiter: RedisRateLimiter) -> None:
        first, second = f"rl:test:{uuid.uuid4()}", f"rl:test:{uuid.uuid4()}"
        redis_limiter.hit(first, 1, 5)
        assert not redis_limiter.hit(first, 1, 5).allowed
        assert redis_limiter.hit(second, 1, 5).allowed

    def test_keyWithoutExpiry_getsOne(self, redis_limiter: RedisRateLimiter) -> None:
        key = f"rl:test:{uuid.uuid4()}"
        redis_limiter.client.set(key, 5)  # a leftover counter with no TTL
        result = redis_limiter.hit(key, 2, 30)
        assert not result.allowed and result.retry_after_seconds == 30
        assert 0 < redis_limiter.client.ttl(key) <= 30

    def test_redisDown_failsOpenAndLogsNoKey(self, caplog: pytest.LogCaptureFixture) -> None:
        down = redis.Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.2)
        with caplog.at_level(logging.WARNING):
            assert RedisRateLimiter(down).hit("rl:secret-key", 1, 5).allowed
        assert "Rate limiter unavailable" in caplog.text and "secret-key" not in caplog.text
