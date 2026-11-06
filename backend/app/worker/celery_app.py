from celery import Celery

from app.core.config import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()
    app = Celery(
        "clouddrop", broker=settings.redis_url.get_secret_value(), include=["app.worker.tasks"]
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,  # state lives in processing_jobs, not in Redis
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_time_limit=settings.celery_task_time_limit_seconds,
        task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        # Publishing happens on a request thread: fail fast instead of retrying for many seconds.
        broker_connection_timeout=2,
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 1,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 0.2,
        },
        broker_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
            "socket_connect_timeout": 2,
            "socket_timeout": 30,
        },
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "sweep-stuck-files": {
                "task": "processing.sweep_stuck_files",
                "schedule": settings.sweeper_interval_seconds,
                # A beat message that waits longer than one interval is dropped, so a stopped
                # worker does not come back to a pile of identical sweeps.
                "options": {"expires": settings.sweeper_interval_seconds},
            },
            "purge-expired-data": {
                "task": "storage.purge_expired",
                "schedule": settings.purge_interval_seconds,
                "options": {"expires": settings.purge_interval_seconds},
            },
        },
    )
    return app


celery_app = create_celery_app()
