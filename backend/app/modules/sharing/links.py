import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.pagination import PageParams
from app.modules.audit.constants import AuditAction, ResourceType
from app.modules.audit.service import AuditService
from app.modules.sharing.models import ShareLink
from app.modules.sharing.repository import ShareLinkRepository
from app.modules.sharing.service import AccessService, Action
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File
from app.modules.storage.repository import FileRepository, FileVersionRepository
from app.modules.storage.s3 import S3Storage


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ShareLinkService:
    """View-only links to one file. The owner creates and revokes them; anyone with the token can
    read the file's name and download it until the link expires or is revoked. Every public
    failure (unknown, expired, revoked, file gone or not ready) is the same 404."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.access = AccessService(session)
        self.audit = AuditService(session)
        self.files = FileRepository(session)
        self.versions = FileVersionRepository(session)
        self.links = ShareLinkRepository(session)

    def _owned_file(
        self, user_id: uuid.UUID, file_id: uuid.UUID, *, for_update: bool = False
    ) -> File:
        file = self.files.get_any(file_id, for_update=for_update)
        if file is None or not self.access.can_on_file(user_id, file, Action.SHARE):
            raise NotFoundError("File not found", code="file_not_found")
        return file

    def create(self, user_id: uuid.UUID, file_id: uuid.UUID, days: int) -> tuple[ShareLink, str]:
        # The row lock serialises creates for one file, so the cap below cannot be raced past.
        file = self._owned_file(user_id, file_id, for_update=True)
        if days > self.settings.share_link_max_days:
            raise UnprocessableError(
                f"A link can last at most {self.settings.share_link_max_days} days",
                code="link_too_long",
            )
        if file.status != FileStatus.READY:
            raise ConflictError("The file is not available yet", code="file_not_ready")
        now = datetime.now(UTC)
        if self.links.count_active(file_id, now) >= self.settings.share_link_max_active_per_file:
            raise UnprocessableError("This file has too many active links", code="too_many_links")
        token = secrets.token_urlsafe(32)
        link = ShareLink(
            file_id=file_id,
            created_by=user_id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=days),
        )
        self.links.add(link)
        self._audit(user_id, file, AuditAction.LINK_CREATED, link)
        self.session.commit()
        return link, token

    def list_links(
        self, user_id: uuid.UUID, file_id: uuid.UUID, params: PageParams
    ) -> tuple[list[ShareLink], int]:
        self._owned_file(user_id, file_id)
        return self.links.list_for_file(file_id, params.page_size, params.offset)

    def get_link(self, user_id: uuid.UUID, file_id: uuid.UUID, link_id: uuid.UUID) -> ShareLink:
        self._owned_file(user_id, file_id)
        link = self.links.get(file_id, link_id)
        if link is None:
            raise NotFoundError("Link not found", code="link_not_found")
        return link

    def revoke(self, user_id: uuid.UUID, file_id: uuid.UUID, link_id: uuid.UUID) -> None:
        file = self._owned_file(user_id, file_id)
        link = self.links.get(file_id, link_id, lock=True)
        if link is None:
            raise NotFoundError("Link not found", code="link_not_found")
        if link.revoked_at is None:  # revoking twice is harmless and records nothing new
            link.revoked_at = datetime.now(UTC)
            self._audit(user_id, file, AuditAction.LINK_REVOKED, link)
        self.session.commit()

    def resolve(self, token: str) -> tuple[ShareLink, File]:
        """The link and its file, or the one generic 404 for anything that is not usable."""
        link = self.links.get_by_hash(hash_token(token))
        file = self.files.get_any(link.file_id) if link else None
        if (
            link is None
            or file is None
            or link.revoked_at is not None
            or link.expires_at <= datetime.now(UTC)
            or file.status != FileStatus.READY
        ):
            raise NotFoundError("This link is not available", code="link_not_found")
        return link, file

    def download(self, token: str, storage: S3Storage) -> tuple[str, int]:
        link, file = self.resolve(token)
        version = self.versions.get_current(file.id)
        if version is None:
            raise NotFoundError("This link is not available", code="link_not_found")
        url = storage.create_download_url(version.s3_key, file.name)
        self._record_download(link, file)
        self.session.commit()
        return url, self.settings.presigned_download_ttl_seconds

    def _record_download(self, link: ShareLink, file: File) -> None:
        """At most one event per link per window: the link's holder is anonymous and must not be
        able to fill the owner's trail. One conditional UPDATE decides, so concurrent downloads
        cannot both record and the database clock is the only clock."""
        if not self.links.claim_download_event(
            link.id, self.settings.share_link_audit_window_seconds
        ):
            return
        self.audit.record(
            workspace_id=file.workspace_id,
            actor_id=None,
            action=AuditAction.LINK_DOWNLOADED,
            resource_type=ResourceType.FILE,
            resource_id=file.id,
            detail=str(link.id),
        )

    def _audit(self, user_id: uuid.UUID, file: File, action: AuditAction, link: ShareLink) -> None:
        self.audit.record(
            workspace_id=file.workspace_id,
            actor_id=user_id,
            action=action,
            resource_type=ResourceType.FILE,
            resource_id=file.id,
            detail=str(link.id),
        )
