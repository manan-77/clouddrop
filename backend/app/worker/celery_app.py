from celery import Celery

from app.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("clouddrop", broker=settings.redis_url, include=["app.worker.tasks"])
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
        broker_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
            "socket_connect_timeout": 5,
            "socket_timeout": 30,
        },
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "sweep-stuck-files": {
                "task": "processing.sweep_stuck_files",
                "schedule": settings.sweeper_interval_seconds,
            }
        },
    )
    return app


celery_app = create_celery_app()
