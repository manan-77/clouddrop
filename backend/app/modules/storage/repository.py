import uuid
from typing import Literal

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.db.soft_delete import only_active
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion, Folder


class FolderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, folder: Folder) -> None:
        self.session.add(folder)
        self.session.flush()

    def get(
        self,
        workspace_id: uuid.UUID,
        folder_id: uuid.UUID,
        *,
        lock: Literal["update", "share"] | None = None,
    ) -> Folder | None:
        query = select(Folder).where(
            Folder.id == folder_id, Folder.workspace_id == workspace_id, only_active(Folder)
        )
        # Writers into a folder take FOR SHARE, a delete takes FOR UPDATE, so a folder can
        # never be deleted while a child is being added to it.
        if lock == "update":
            query = query.with_for_update()
        elif lock == "share":
            query = query.with_for_update(read=True)
        return self.session.scalar(query)

    def get_path(
        self, workspace_id: uuid.UUID, folder_id: uuid.UUID, max_depth: int
    ) -> list[Folder]:
        """The folder and its ancestors, root first, in one recursive query."""
        chain = (
            select(Folder.id, Folder.parent_id, literal(1).label("depth"))
            .where(Folder.id == folder_id, Folder.workspace_id == workspace_id, only_active(Folder))
            .cte("chain", recursive=True)
        )
        parent = aliased(Folder)
        chain = chain.union_all(
            select(parent.id, parent.parent_id, chain.c.depth + 1)
            .join(chain, parent.id == chain.c.parent_id)
            .where(
                parent.workspace_id == workspace_id,
                only_active(parent),
                chain.c.depth < max_depth,
            )
        )
        rows = self.session.scalars(
            select(Folder).join(chain, Folder.id == chain.c.id).order_by(chain.c.depth.desc())
        )
        return list(rows)

    def list_children(
        self, workspace_id: uuid.UUID, parent_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Folder], int]:
        where = self._children_filter(workspace_id, parent_id)
        total = self.session.scalar(select(func.count()).select_from(Folder).where(*where)) or 0
        rows = self.session.scalars(
            select(Folder)
            .where(*where)
            .order_by(Folder.name, Folder.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total

    def has_subfolders(self, workspace_id: uuid.UUID, folder_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(Folder.id).where(*self._children_filter(workspace_id, folder_id)).limit(1)
            )
            is not None
        )

    @staticmethod
    def _children_filter(
        workspace_id: uuid.UUID, parent_id: uuid.UUID | None
    ) -> list[ColumnElement[bool]]:
        parent = Folder.parent_id.is_(None) if parent_id is None else Folder.parent_id == parent_id
        return [Folder.workspace_id == workspace_id, parent, only_active(Folder)]


class FileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, file: File) -> None:
        self.session.add(file)
        self.session.flush()

    def get(
        self, workspace_id: uuid.UUID, file_id: uuid.UUID, *, for_update: bool = False
    ) -> File | None:
        query = select(File).where(
            File.id == file_id, File.workspace_id == workspace_id, only_active(File)
        )
        return self.session.scalar(query.with_for_update() if for_update else query)

    def list_files(
        self,
        workspace_id: uuid.UUID,
        folder_id: uuid.UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[File], int]:
        where = self._filter(workspace_id, folder_id, status)
        total = self.session.scalar(select(func.count()).select_from(File).where(*where)) or 0
        rows = self.session.scalars(
            select(File).where(*where).order_by(File.name, File.id).limit(limit).offset(offset)
        )
        return list(rows), total

    def sum_size(self, workspace_id: uuid.UUID) -> int:
        total = self.session.scalar(
            select(func.coalesce(func.sum(File.size_bytes), 0)).where(
                File.workspace_id == workspace_id,
                only_active(File),
                File.status != FileStatus.FAILED.value,
            )
        )
        return int(total or 0)

    def has_files_in(self, workspace_id: uuid.UUID, folder_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(File.id).where(*self._filter(workspace_id, folder_id, None)).limit(1)
            )
            is not None
        )

    @staticmethod
    def _filter(
        workspace_id: uuid.UUID, folder_id: uuid.UUID | None, status: str | None
    ) -> list[ColumnElement[bool]]:
        folder = File.folder_id.is_(None) if folder_id is None else File.folder_id == folder_id
        conditions = [File.workspace_id == workspace_id, folder, only_active(File)]
        if status is not None:
            conditions.append(File.status == status)
        return conditions


class FileVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, version: FileVersion) -> None:
        self.session.add(version)
        self.session.flush()

    def get_current(self, file_id: uuid.UUID) -> FileVersion | None:
        return self.session.scalar(
            select(FileVersion)
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version.desc())
            .limit(1)
        )
