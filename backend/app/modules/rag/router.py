from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.core.deps import SessionDep, SettingsDep
from app.core.ratelimit import RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.rag.schemas import AnswerEvent, AnswerRequest
from app.modules.rag.service import RagService

router = APIRouter(prefix="/api/v1/answers", tags=["answers"])


# POST only so the question travels in the body, not the URL. It creates nothing (no history is
# kept), so the answer is 200. The body is a server-sent event stream; `response_model` documents
# the shape of each event's data.
@router.post(
    "",
    response_model=AnswerEvent,
    status_code=status.HTTP_200_OK,
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}},
)
def ask(
    body: AnswerRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> StreamingResponse:
    """A cited answer about files the caller may read, streamed as it is written."""
    enforce(
        limiter,
        "answer:user",
        str(user.id),
        settings.rate_limit_answer_per_user,
        settings.rate_limit_answer_window_seconds,
    )
    answer = RagService(session, settings).start(user.id, body.question, body.file_id)
    return StreamingResponse(
        answer.events(),
        media_type="text/event-stream",
        # Not stored by anything, and not held back by a buffering proxy (nginx honours this).
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        # If the client leaves before the first byte, `events` never starts and cannot clean up.
        background=BackgroundTask(answer.close),
    )
