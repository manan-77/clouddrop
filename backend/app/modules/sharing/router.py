import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.core.deps import SessionDep, SettingsDep
from app.core.pagination import Page, PageParamsDep
from app.core.ratelimit import RateLimiter, RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.auth.models import User
from app.modules.sharing.grants import SharingService
from app.modules.sharing.models import Permission
from app.modules.sharing.repository import Kind
from app.modules.sharing.schemas import GrantCreate, GrantRead, GrantUpdate, SharedItem

router = APIRouter(prefix="/api/v1", tags=["sharing"])


def get_sharing_service(session: SessionDep) -> SharingService:
    return SharingService(session)


SharingServiceDep = Annotated[SharingService, Depends(get_sharing_service)]
# FastAPI types `responses` with Any values, so the annotation has to match it.
GRANTED: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {"model": GrantRead, "description": "The grant already existed"}
}


def _read(permission: Permission, grantee: User) -> GrantRead:
    # The schema validates the role, so a corrupt stored value fails loudly instead of being masked.
    return GrantRead.model_validate(
        {
            "id": permission.id,
            "email": grantee.email,
            "display_name": grantee.display_name,
            "role": permission.role,
            "created_at": permission.created_at,
        }
    )


def _grant(
    kind: Kind,
    resource_id: uuid.UUID,
    body: GrantCreate,
    response: Response,
    user: User,
    service: SharingService,
    limiter: RateLimiter,
    settings: SettingsDep,
) -> GrantRead:
    # Granting reveals whether an email has an account, so it is rate limited per user.
    enforce(
        limiter,
        "grant:user",
        str(user.id),
        settings.rate_limit_grant_per_user,
        settings.rate_limit_grant_window_seconds,
    )
    permission, grantee, created = service.grant(user.id, kind, resource_id, body.email, body.role)
    response.headers["Location"] = f"/api/v1/{kind}/{resource_id}/permissions/{permission.id}"
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _read(permission, grantee)


def _list(
    kind: Kind,
    resource_id: uuid.UUID,
    user: User,
    service: SharingService,
    params: PageParamsDep,
) -> Page[GrantRead]:
    rows, total = service.list_grants(user.id, kind, resource_id, params)
    return Page[GrantRead](
        items=[_read(p, u) for p, u in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/shared-with-me", response_model=Page[SharedItem], status_code=status.HTTP_200_OK)
def shared_with_me(
    user: CurrentUser, service: SharingServiceDep, params: PageParamsDep
) -> Page[SharedItem]:
    items, total = service.shared_with_me(user.id, params)
    return Page[SharedItem](
        items=[SharedItem.model_validate(item) for item in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


# ---- files -----------------------------------------------------------------------------------


@router.post(
    "/files/{file_id}/permissions",
    response_model=GrantRead,
    status_code=status.HTTP_201_CREATED,
    responses=GRANTED,
)
def grant_file_access(
    file_id: uuid.UUID,
    body: GrantCreate,
    response: Response,
    user: CurrentUser,
    service: SharingServiceDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> GrantRead:
    return _grant("files", file_id, body, response, user, service, limiter, settings)


@router.get(
    "/files/{file_id}/permissions", response_model=Page[GrantRead], status_code=status.HTTP_200_OK
)
def list_file_grants(
    file_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep, params: PageParamsDep
) -> Page[GrantRead]:
    return _list("files", file_id, user, service, params)


@router.get(
    "/files/{file_id}/permissions/{permission_id}",
    response_model=GrantRead,
    status_code=status.HTTP_200_OK,
)
def get_file_grant(
    file_id: uuid.UUID, permission_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep
) -> GrantRead:
    return _read(*service.get_grant(user.id, "files", file_id, permission_id))


@router.patch(
    "/files/{file_id}/permissions/{permission_id}",
    response_model=GrantRead,
    status_code=status.HTTP_200_OK,
)
def change_file_grant(
    file_id: uuid.UUID,
    permission_id: uuid.UUID,
    body: GrantUpdate,
    user: CurrentUser,
    service: SharingServiceDep,
) -> GrantRead:
    return _read(*service.change_role(user.id, "files", file_id, permission_id, body.role))


@router.delete(
    "/files/{file_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_file_grant(
    file_id: uuid.UUID, permission_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep
) -> None:
    service.revoke(user.id, "files", file_id, permission_id)


# ---- folders ---------------------------------------------------------------------------------


@router.post(
    "/folders/{folder_id}/permissions",
    response_model=GrantRead,
    status_code=status.HTTP_201_CREATED,
    responses=GRANTED,
)
def grant_folder_access(
    folder_id: uuid.UUID,
    body: GrantCreate,
    response: Response,
    user: CurrentUser,
    service: SharingServiceDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> GrantRead:
    return _grant("folders", folder_id, body, response, user, service, limiter, settings)


@router.get(
    "/folders/{folder_id}/permissions",
    response_model=Page[GrantRead],
    status_code=status.HTTP_200_OK,
)
def list_folder_grants(
    folder_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep, params: PageParamsDep
) -> Page[GrantRead]:
    return _list("folders", folder_id, user, service, params)


@router.get(
    "/folders/{folder_id}/permissions/{permission_id}",
    response_model=GrantRead,
    status_code=status.HTTP_200_OK,
)
def get_folder_grant(
    folder_id: uuid.UUID, permission_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep
) -> GrantRead:
    return _read(*service.get_grant(user.id, "folders", folder_id, permission_id))


@router.patch(
    "/folders/{folder_id}/permissions/{permission_id}",
    response_model=GrantRead,
    status_code=status.HTTP_200_OK,
)
def change_folder_grant(
    folder_id: uuid.UUID,
    permission_id: uuid.UUID,
    body: GrantUpdate,
    user: CurrentUser,
    service: SharingServiceDep,
) -> GrantRead:
    return _read(*service.change_role(user.id, "folders", folder_id, permission_id, body.role))


@router.delete(
    "/folders/{folder_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_folder_grant(
    folder_id: uuid.UUID, permission_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep
) -> None:
    service.revoke(user.id, "folders", folder_id, permission_id)
