"""Search must show exactly the files the access check allows, in every shape of tree.

Search re-states the access rule as SQL (it has to: it filters inside the ranking query), so the
two can drift. This builds many random trees, grants and deletions and compares, for every user and
every file, what search returns with what `AccessService` decides. A rule fixed in one place and not
the other fails here, whatever shape triggered it.
"""

import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.search import repository  # noqa: F401  (the code under comparison)
from app.modules.sharing.models import Permission
from app.modules.sharing.service import AccessService, Action
from app.modules.storage.models import File, FileVersion, Folder
from app.modules.workspaces.models import Workspace
from tests.conftest import FakeEmbedder
from tests.test_search import _index, _names, _search
from tests.test_sharing import Person, _person

TEXT = "alpha beta"
NOW = "2026-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def match_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "search_min_score", 0.1)


def _build(session: Session, rng: random.Random, workspace_id: uuid.UUID, users: list[User]):
    """A random tree, grants (folders and files) and deletions. Returns the files created."""
    folders: list[Folder] = []
    for index in range(rng.randint(1, 7)):
        parent = rng.choice([None, *folders]) if folders else None
        folder = Folder(workspace_id=workspace_id, parent_id=parent.id if parent else None)
        folder.name = f"f{index}"
        session.add(folder)
        session.flush()
        folders.append(folder)
    files: list[File] = []
    for index in range(rng.randint(2, 10)):
        folder = rng.choice([None, *folders])
        status = rng.choice(["ready", "ready", "ready", "processing", "failed"])
        file = File(
            workspace_id=workspace_id,
            folder_id=folder.id if folder else None,
            name=f"file{index}.txt",
            content_type="text/plain",
            size_bytes=10,
            status=status,
        )
        session.add(file)
        session.flush()
        session.add(
            FileVersion(
                file_id=file.id,
                version=1,
                s3_key=f"k/{uuid.uuid4()}",
                size_bytes=10,
                content_type="text/plain",
            )
        )
        files.append(file)
    session.flush()
    for user in users:
        for folder in folders:
            if rng.random() < 0.25:
                session.add(
                    Permission(
                        folder_id=folder.id,
                        grantee_id=user.id,
                        role=rng.choice(["viewer", "editor"]),
                    )
                )
        for file in files:
            if rng.random() < 0.2:
                session.add(
                    Permission(
                        file_id=file.id, grantee_id=user.id, role=rng.choice(["viewer", "editor"])
                    )
                )
    session.flush()
    from datetime import UTC, datetime

    for folder in folders:
        if rng.random() < 0.2:
            folder.deleted_at = datetime.now(UTC)
    for file in files:
        if rng.random() < 0.1:
            file.deleted_at = datetime.now(UTC)
    session.commit()
    return files


# A bug that needs one particular shape showed up in about 1 of 13 random trees; 80 makes a miss
# very unlikely while the whole file still runs in a few seconds.
@pytest.mark.parametrize("seed", range(80))
def test_searchShowsExactlyWhatTheAccessCheckAllows(
    seed: int, client: TestClient, session: Session, fake_embedder: FakeEmbedder
) -> None:
    people: dict[str, Person] = {n: _person(client, n) for n in ("owner", "grantee", "stranger")}
    users = {
        name: session.scalars(select(User).where(User.email == person.email)).one()
        for name, person in people.items()
    }
    workspace = session.scalars(
        select(Workspace).where(Workspace.owner_id == users["owner"].id)
    ).one()
    rng = random.Random(seed)
    files = _build(session, rng, workspace.id, [users["grantee"]])
    for file in files:
        _index(session, fake_embedder, str(file.id), TEXT)
    session.expire_all()

    access = AccessService(session)
    for name, person in people.items():
        expected = {
            file.name
            for file in files
            if file.deleted_at is None
            and file.status == "ready"
            and access.can_on_file(users[name].id, file, Action.READ)
        }
        found = set(_names(_search(client, person, TEXT, page_size=100)[1]))
        assert found == expected, (
            f"seed {seed}, {name}: search {sorted(found)} != access {sorted(expected)}"
        )
