"""Finds the chunks closest in meaning to a query, among files the caller may read.

The access rule is the one in docs/permissions.md, written as set operations so it runs in the
same statement as the ranking: owner of the workspace, or a grant on the file, or a grant on any
folder above it, and never below a deleted folder. Only `ready` files that are not deleted count.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, literal, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, aliased

from app.modules.processing.models import ChunkEmbedding, DocumentChunk
from app.modules.sharing.models import Permission
from app.modules.storage.constants import MAX_FOLDER_DEPTH, FileStatus
from app.modules.storage.models import File, FileVersion, Folder
from app.modules.workspaces.models import Workspace

# Module-level so a test can prove the fallback for a server without iterative scans.
ITERATIVE_SCAN_SQL = "SET LOCAL hnsw.iterative_scan = 'strict_order'"


@dataclass(frozen=True)
class ChunkMatch:
    file_id: uuid.UUID
    file_name: str
    chunk_id: uuid.UUID
    page: int | None
    content: str
    score: float


def _folders_granted_to(user_id: uuid.UUID):  # type: ignore[no-untyped-def]  # a recursive CTE
    """Every live folder the user was granted, and every live folder below one of them.

    Walking down (not up per file) keeps this one small set; a deleted folder stops the walk, so
    nothing below it is reachable.
    """
    granted = (
        select(Folder.id.label("id"), literal(1).label("depth"))
        .join(Permission, Permission.folder_id == Folder.id)
        .where(Permission.grantee_id == user_id, Folder.deleted_at.is_(None))
        .cte("visible_folders", recursive=True)
    )
    child = aliased(Folder)
    return granted.union(
        select(child.id, granted.c.depth + 1)
        .join(granted, child.parent_id == granted.c.id)
        .where(child.deleted_at.is_(None), granted.c.depth < MAX_FOLDER_DEPTH)
    )


def _files_blocked_by_a_deleted_folder(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Files the user holds a direct grant on that sit below a deleted folder (they lose access)."""
    direct = select(Permission.file_id).where(
        Permission.grantee_id == user_id, Permission.file_id.is_not(None)
    )
    chain = (
        select(
            File.id.label("file_id"),
            Folder.id.label("folder_id"),
            Folder.parent_id.label("parent_id"),
            Folder.deleted_at.is_not(None).label("deleted"),
            literal(1).label("depth"),
        )
        .join(Folder, Folder.id == File.folder_id)
        .where(File.id.in_(direct))
        .cte("file_ancestors", recursive=True)
    )
    parent = aliased(Folder)
    chain = chain.union_all(
        select(
            chain.c.file_id,
            parent.id,
            parent.parent_id,
            parent.deleted_at.is_not(None),
            chain.c.depth + 1,
        )
        .join(parent, parent.id == chain.c.parent_id)
        .where(chain.c.depth < MAX_FOLDER_DEPTH)
    )
    return select(chain.c.file_id).where(chain.c.deleted)


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _can_read(self, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
        owned = select(Workspace.id).where(Workspace.owner_id == user_id)
        file_grants = select(Permission.file_id).where(
            Permission.grantee_id == user_id, Permission.file_id.is_not(None)
        )
        return or_(
            File.workspace_id.in_(owned),
            File.id.in_(file_grants) & File.id.not_in(_files_blocked_by_a_deleted_folder(user_id)),
            File.folder_id.in_(select(_folders_granted_to(user_id).c.id)),
        )

    def _prepare_index_scan(self) -> None:
        """Makes the approximate index keep scanning until the access filter is satisfied.

        Without this the index returns its few nearest candidates and the filter may drop all of
        them, so a user who can see a small slice would get no results. pgvector 0.8 added
        iterative scans; on an older server fall back to a wider candidate list.
        """
        try:
            with self.session.begin_nested():
                self.session.execute(text(ITERATIVE_SCAN_SQL))
        except DBAPIError:
            self.session.execute(text("SET LOCAL hnsw.ef_search = 1000"))

    def closest_chunks(
        self, user_id: uuid.UUID, query_vector: list[float], min_score: float, limit: int
    ) -> list[ChunkMatch]:
        self._prepare_index_scan()
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        newer = aliased(FileVersion)  # an alias, or the subquery correlates away its own table
        latest_version = (
            select(func.max(newer.version)).where(newer.file_id == File.id).scalar_subquery()
        )
        query: Select[tuple[object, ...]] = (
            select(
                File.id.label("file_id"),
                File.name.label("file_name"),
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.page.label("page"),
                DocumentChunk.content.label("content"),
                (1 - distance).label("score"),
            )
            .select_from(ChunkEmbedding)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .join(FileVersion, FileVersion.id == DocumentChunk.file_version_id)
            .join(File, File.id == FileVersion.file_id)
            .where(
                File.deleted_at.is_(None),
                File.status == FileStatus.READY.value,
                FileVersion.version == latest_version,
                distance <= 1 - min_score,
                self._can_read(user_id),
            )
            .order_by(distance, DocumentChunk.id)
            .limit(limit)
        )
        return [
            ChunkMatch(
                row.file_id, row.file_name, row.chunk_id, row.page, row.content, float(row.score)
            )
            for row in self.session.execute(query)
        ]
