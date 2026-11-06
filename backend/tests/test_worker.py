import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from app.core.errors import ServiceUnavailableError
from app.modules.processing.stages import TransientStageError
from app.worker import tasks
from app.worker.celery_app import celery_app


def test_celeryApp_isConfiguredForSafeRecoveryAndSmallMessages() -> None:
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_serializer == "json" and list(conf.accept_content) == ["json"]
    assert conf.task_ignore_result is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_soft_time_limit < conf.task_time_limit


def test_visibilityTimeout_exceedsTheLongestTaskIncludingBackoff() -> None:
    conf = celery_app.conf
    longest = conf.task_time_limit + tasks.process_file_version.retry_backoff_max
    assert conf.broker_transport_options["visibility_timeout"] > longest


def test_tasks_areRegisteredWithRetryAndASweeperSchedule() -> None:
    assert "processing.process_file_version" in celery_app.tasks
    assert "processing.sweep_stuck_files" in celery_app.tasks
    task: Any = tasks.process_file_version
    assert task.autoretry_for == (TransientStageError,)
    assert task.retry_backoff is True and task.retry_jitter is True
    assert task.max_retries == 5
    schedule = celery_app.conf.beat_schedule["sweep-stuck-files"]
    assert schedule["task"] == "processing.sweep_stuck_files"


def test_processTask_takesAnIdAndRunsThePipelineInItsOwnSession(
    monkeypatch: pytest.MonkeyPatch, session: Any, storage: Any
) -> None:
    calls: list[tuple[Any, Any, uuid.UUID]] = []

    @contextmanager
    def fake_session():  # type: ignore[no-untyped-def]
        yield session

    monkeypatch.setattr(tasks, "open_session", fake_session)
    monkeypatch.setattr(tasks, "storage_for_worker", lambda: storage)
    monkeypatch.setattr(
        tasks, "run_pipeline", lambda s, st, version_id, **_: calls.append((s, st, version_id))
    )
    version_id = uuid.uuid4()
    tasks.process_file_version.run(str(version_id))
    assert calls == [(session, storage, version_id)]


def test_processTask_transientFailure_surfacesSoCeleryRetries(
    monkeypatch: pytest.MonkeyPatch, session: Any
) -> None:
    @contextmanager
    def fake_session():  # type: ignore[no-untyped-def]
        yield session

    def boom(*_: object, **__: object) -> None:
        raise TransientStageError("storage unavailable")

    monkeypatch.setattr(tasks, "open_session", fake_session)
    monkeypatch.setattr(tasks, "storage_for_worker", lambda: object())
    monkeypatch.setattr(tasks, "run_pipeline", boom)
    with pytest.raises(TransientStageError):
        tasks.process_file_version.run(str(uuid.uuid4()))


def test_sweepTask_usesTheConfiguredThresholdsAndReturnsTheCount(
    monkeypatch: pytest.MonkeyPatch, session: Any
) -> None:
    seen: dict[str, Any] = {}

    @contextmanager
    def fake_session():  # type: ignore[no-untyped-def]
        yield session

    def fake_sweep(_session: Any, _dispatcher: Any, *, stuck_after: Any, limit: int) -> int:
        seen.update(stuck_after=stuck_after.total_seconds(), limit=limit)
        return 3

    monkeypatch.setattr(tasks, "open_session", fake_session)
    monkeypatch.setattr(tasks, "sweep", fake_sweep)
    assert tasks.sweep_stuck_files.run() == 3
    assert seen == {"stuck_after": 600.0, "limit": 100}


def test_storageUnavailable_isATransientErrorForTheWorker() -> None:
    from app.modules.processing.stages import VerifyObjectStage

    class Down:
        def head(self, key: str) -> None:
            raise ServiceUnavailableError("down", code="storage_unavailable")

    with pytest.raises(TransientStageError):
        VerifyObjectStage().run(object(), type("V", (), {"s3_key": "k"})(), Down())  # type: ignore[arg-type]
