"""add files.created_by

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_files_created_by_users"),
        "files",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_files_created_by_users"), "files", type_="foreignkey")
    op.drop_column("files", "created_by")
