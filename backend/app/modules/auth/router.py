from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.core.deps import SettingsDep
from app.modules.auth.deps import AuthServiceDep, CurrentUser
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.modules.auth.service import AuthTokens

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str, settings: SettingsDep) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.jwt_refresh_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _token_response(tokens: AuthTokens) -> TokenResponse:
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, service: AuthServiceDep) -> UserRead:
    user = service.register(body.email, body.password, body.display_name)
    response.headers["Location"] = "/api/v1/auth/me"
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login(
    body: LoginRequest, response: Response, service: AuthServiceDep, settings: SettingsDep
) -> TokenResponse:
    tokens = service.login(body.email, body.password)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def refresh(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    tokens = service.refresh(refresh_token)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    service: AuthServiceDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    service.logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get("/me", response_model=UserRead, status_code=status.HTTP_200_OK)
def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
