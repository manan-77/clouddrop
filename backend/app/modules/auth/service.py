import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.repository import RefreshTokenRepository, UserRepository
from app.modules.workspaces.service import WorkspaceService


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.workspaces = WorkspaceService(session)

    def register(self, email: str, password: str, display_name: str) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=hash_password(password),
            display_name=display_name.strip(),
        )
        try:
            # The unique constraint is the arbiter; no check-then-insert.
            with self.session.begin_nested():
                self.users.add(user)
                self.workspaces.create_personal(user.id, user.display_name)
        except IntegrityError as exc:
            raise ConflictError("An account with this email already exists") from exc
        self.session.commit()
        return user

    def login(self, email: str, password: str) -> AuthTokens:
        user = self.users.get_by_email(email.strip().lower())
        password_ok = verify_password(password, user.password_hash if user else None)
        if user is None or not password_ok or not user.is_active:
            raise UnauthorizedError("Invalid email or password", code="invalid_credentials")
        tokens = self._issue_tokens(user.id, family_id=uuid.uuid4())
        self.session.commit()
        return tokens

    def refresh(self, raw_refresh_token: str | None) -> AuthTokens:
        if not raw_refresh_token:
            raise UnauthorizedError("Invalid session", code="invalid_session")
        now = datetime.now(UTC)
        stored = self.refresh_tokens.get_for_update(hash_refresh_token(raw_refresh_token))
        if stored is None:
            raise UnauthorizedError("Invalid session", code="invalid_session")
        if stored.revoked_at is not None:
            # An already-rotated token came back: assume theft and kill the whole family.
            self.refresh_tokens.revoke_family(stored.family_id, now)
            self.session.commit()
            raise UnauthorizedError("Invalid session", code="invalid_session")
        user = self.users.get(stored.user_id)
        if stored.expires_at <= now or user is None or not user.is_active:
            raise UnauthorizedError("Invalid session", code="invalid_session")
        stored.revoked_at = now
        tokens = self._issue_tokens(user.id, family_id=stored.family_id)
        self.session.commit()
        return tokens

    def logout(self, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return
        stored = self.refresh_tokens.get_for_update(hash_refresh_token(raw_refresh_token))
        if stored is not None:
            self.refresh_tokens.revoke_family(stored.family_id, datetime.now(UTC))
            self.session.commit()

    def _issue_tokens(self, user_id: uuid.UUID, family_id: uuid.UUID) -> AuthTokens:
        raw = new_refresh_token()
        self.refresh_tokens.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(raw),
                expires_at=datetime.now(UTC) + timedelta(days=self.settings.jwt_refresh_ttl_days),
            )
        )
        return AuthTokens(
            access_token=create_access_token(user_id, self.settings),
            refresh_token=raw,
            expires_in=self.settings.jwt_access_ttl_minutes * 60,
        )
