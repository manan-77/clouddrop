import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import SessionDep, SettingsDep
from app.core.ratelimit import RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.sharing.service import Action
from app.modules.storage.deps import FileServiceDep
from app.modules.summaries.dispatcher import SummaryDispatcher, get_summary_dispatcher
from app.modules.summaries.schemas import FileSummaryRead
from app.modules.summaries.service import SummaryService

router = APIRouter(prefix="/api/v1/files/{file_id}/summary", tags=["summaries"])


def get_summary_service(session: SessionDep, settings: SettingsDep) -> SummaryService:
    return SummaryService(session, settings)


SummaryServiceDep = Annotated[SummaryService, Depends(get_summary_service)]
DispatcherDep = Annotated[SummaryDispatcher, Depends(get_summary_dispatcher)]


@router.get("", response_model=FileSummaryRead, status_code=status.HTTP_200_OK)
def read_summary(
    file_id: uuid.UUID, user: CurrentUser, files: FileServiceDep, service: SummaryServiceDep
) -> FileSummaryRead:
    """The summary, category and tags of a file the caller can read."""
    file = files.get_file(user.id, file_id)  # 404 for a file the caller may not see
    return FileSummaryRead.model_validate(service.read(file))


@router.post("", response_model=FileSummaryRead, status_code=status.HTTP_202_ACCEPTED)
def request_summary(
    file_id: uuid.UUID,
    user: CurrentUser,
    files: FileServiceDep,
    service: SummaryServiceDep,
    dispatcher: DispatcherDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> FileSummaryRead:
    """Asks for a new summary (it is written in the background). Needs write access."""
    enforce(
        limiter,
        "summary:user",
        str(user.id),
        settings.rate_limit_summary_per_user,
        settings.rate_limit_summary_window_seconds,
    )
    file = files.get_file(user.id, file_id, Action.WRITE)
    return FileSummaryRead.model_validate(service.request(file, dispatcher))
