import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.deps import SessionDep, SettingsDep
from app.core.pagination import Page, PageParamsDep
from app.core.ratelimit import RateLimiterDep, client_ip, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.sharing.link_schemas import (
    LinkTokenBody,
    PublicDownload,
    PublicLinkRead,
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkRead,
)
from app.modules.sharing.links import ShareLinkService
from app.modules.storage.deps import StorageDep

router = APIRouter(prefix="/api/v1", tags=["share-links"])


def get_link_service(session: SessionDep, settings: SettingsDep) -> ShareLinkService:
    return ShareLinkService(session, settings)


LinkServiceDep = Annotated[ShareLinkService, Depends(get_link_service)]


@router.post(
    "/files/{file_id}/share-links",
    response_model=ShareLinkCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_share_link(
    file_id: uuid.UUID,
    body: ShareLinkCreate,
    response: Response,
    user: CurrentUser,
    service: LinkServiceDep,
) -> ShareLinkCreated:
    link, token = service.create(user.id, file_id, body.expires_in_days)
    response.headers["Location"] = f"/api/v1/files/{file_id}/share-links/{link.id}"
    response.headers["Cache-Control"] = "no-store"  # the one-time token
    return ShareLinkCreated(**ShareLinkRead.model_validate(link).model_dump(), token=token)


@router.get(
    "/files/{file_id}/share-links",
    response_model=Page[ShareLinkRead],
    status_code=status.HTTP_200_OK,
)
def list_share_links(
    file_id: uuid.UUID, user: CurrentUser, service: LinkServiceDep, params: PageParamsDep
) -> Page[ShareLinkRead]:
    links, total = service.list_links(user.id, file_id, params)
    return Page[ShareLinkRead](
        items=[ShareLinkRead.model_validate(link) for link in links],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get(
    "/files/{file_id}/share-links/{link_id}",
    response_model=ShareLinkRead,
    status_code=status.HTTP_200_OK,
)
def get_share_link(
    file_id: uuid.UUID, link_id: uuid.UUID, user: CurrentUser, service: LinkServiceDep
) -> ShareLinkRead:
    return ShareLinkRead.model_validate(service.get_link(user.id, file_id, link_id))


@router.delete("/files/{file_id}/share-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share_link(
    file_id: uuid.UUID, link_id: uuid.UUID, user: CurrentUser, service: LinkServiceDep
) -> None:
    service.revoke(user.id, file_id, link_id)


# Public: no sign-in. Rate limited per client address, and POST so the token stays out of URLs.


def _limit_public(
    request: Request, token: str, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    window = settings.rate_limit_public_link_window_seconds
    enforce(
        limiter,
        "public-link:ip",
        client_ip(request),
        settings.rate_limit_public_link_per_ip,
        window,
    )
    # Per token as well: one leaked link cannot be hammered from many addresses.
    enforce(limiter, "public-link:token", token, settings.rate_limit_public_link_per_token, window)


@router.post(
    "/public/share-links/resolve", response_model=PublicLinkRead, status_code=status.HTTP_200_OK
)
def resolve_share_link(
    body: LinkTokenBody,
    request: Request,
    response: Response,
    service: LinkServiceDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> PublicLinkRead:
    _limit_public(request, body.token, limiter, settings)
    response.headers["Cache-Control"] = "no-store"
    link, file = service.resolve(body.token)
    return PublicLinkRead(
        file_name=file.name,
        size_bytes=file.size_bytes,
        content_type=file.content_type,
        expires_at=link.expires_at,
    )


@router.post(
    "/public/share-links/download", response_model=PublicDownload, status_code=status.HTTP_200_OK
)
def download_via_share_link(
    body: LinkTokenBody,
    request: Request,
    response: Response,
    service: LinkServiceDep,
    storage: StorageDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> PublicDownload:
    _limit_public(request, body.token, limiter, settings)
    response.headers["Cache-Control"] = "no-store"  # a live download URL
    url, expires_in = service.download(body.token, storage)
    return PublicDownload(url=url, expires_in=expires_in)
