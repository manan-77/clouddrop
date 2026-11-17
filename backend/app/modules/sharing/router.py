import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status

from app.core.deps import SessionDep, SettingsDep
from app.core.pagination import Page, PageParamsDep
from app.core.ratelimit import RateLimiterDep, enforce
from app.modules.auth.deps import CurrentUser
from app.modules.auth.models import User
from app.modules.sharing.grants import SharingService
from app.modules.sharing.models import Permission
from app.modules.sharing.schemas import (
    GrantCreate,
    GrantRead,
    GrantRole,
    GrantUpdate,
    SharedItem,
)

router = APIRouter(prefix="/api/v1", tags=["sharing"])


def get_sharing_service(session: SessionDep) -> SharingService:
    return SharingService(session)


SharingServiceDep = Annotated[SharingService, Depends(get_sharing_service)]


def _read(permission: Permission, grantee: User) -> GrantRead:
    return GrantRead(
        id=permission.id,
        email=grantee.email,
        display_name=grantee.display_name,
        role=_role(permission.role),
        created_at=permission.created_at,
    )


def _role(value: str) -> GrantRole:
    return "editor" if value == "editor" else "viewer"


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


def _register(kind: Literal["files", "folders"]) -> None:
    base = f"/{kind}/{{resource_id}}/permissions"

    @router.post(
        base, response_model=GrantRead, status_code=status.HTTP_201_CREATED, name=f"grant_{kind}"
    )
    def grant(
        resource_id: uuid.UUID,
        body: GrantCreate,
        response: Response,
        user: CurrentUser,
        service: SharingServiceDep,
        limiter: RateLimiterDep,
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
        permission, grantee, created = service.grant(
            user.id, kind, resource_id, body.email, body.role
        )
        response.headers["Location"] = f"/api/v1/{kind}/{resource_id}/permissions/{permission.id}"
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return _read(permission, grantee)

    @router.get(
        base,
        response_model=Page[GrantRead],
        status_code=status.HTTP_200_OK,
        name=f"list_{kind}_grants",
    )
    def list_grants(
        resource_id: uuid.UUID, user: CurrentUser, service: SharingServiceDep, params: PageParamsDep
    ) -> Page[GrantRead]:
        rows, total = service.list_grants(user.id, kind, resource_id, params)
        return Page[GrantRead](
            items=[_read(p, u) for p, u in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    @router.get(
        f"{base}/{{permission_id}}",
        response_model=GrantRead,
        status_code=status.HTTP_200_OK,
        name=f"get_{kind}_grant",
    )
    def get_grant(
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        user: CurrentUser,
        service: SharingServiceDep,
    ) -> GrantRead:
        return _read(*service.get_grant(user.id, kind, resource_id, permission_id))

    @router.patch(
        f"{base}/{{permission_id}}",
        response_model=GrantRead,
        status_code=status.HTTP_200_OK,
        name=f"change_{kind}_grant",
    )
    def change_grant(
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        body: GrantUpdate,
        user: CurrentUser,
        service: SharingServiceDep,
    ) -> GrantRead:
        return _read(*service.change_role(user.id, kind, resource_id, permission_id, body.role))

    @router.delete(
        f"{base}/{{permission_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"revoke_{kind}_grant",
    )
    def revoke_grant(
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        user: CurrentUser,
        service: SharingServiceDep,
    ) -> None:
        service.revoke(user.id, kind, resource_id, permission_id)


_register("files")
_register("folders")
