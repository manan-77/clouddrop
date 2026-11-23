from fastapi import APIRouter, status

from app.core.deps import SessionDep, SettingsDep
from app.core.pagination import Page, PageParamsDep
from app.core.ratelimit import RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.search.schemas import SearchHit, SearchRequest
from app.modules.search.service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["search"])


# POST only so the search terms travel in the body, not the URL (root CLAUDE.md: terms never reach
# logs, history or referrers). It creates nothing, so the answer is 200, not 201.
@router.post("", response_model=Page[SearchHit], status_code=status.HTTP_200_OK)
def search(
    body: SearchRequest,
    user: CurrentUser,
    params: PageParamsDep,
    session: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> Page[SearchHit]:
    """Files whose content is closest in meaning to the query, among files the caller may read."""
    enforce(
        limiter,
        "search:user",
        str(user.id),
        settings.rate_limit_search_per_user,
        settings.rate_limit_search_window_seconds,
    )
    items, total = SearchService(session, settings).search(user.id, body.query, params)
    return Page[SearchHit](items=items, total=total, page=params.page, page_size=params.page_size)
