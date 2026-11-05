from fastapi import APIRouter, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.deps import SessionDep
from app.core.errors import ServiceUnavailableError
from app.modules.health.schemas import HealthRead

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthRead, status_code=status.HTTP_200_OK)
def liveness() -> HealthRead:
    return HealthRead(status="ok")


@router.get("/ready", response_model=HealthRead, status_code=status.HTTP_200_OK)
def readiness(session: SessionDep) -> HealthRead:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Database unavailable", code="db_unavailable") from exc
    return HealthRead(status="ready")
