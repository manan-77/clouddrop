"""add multipart columns to file_versions

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_versions", sa.Column("multipart_upload_id", sa.String(length=1024), nullable=True)
    )
    op.add_column("file_versions", sa.Column("part_size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("file_versions", "part_size_bytes")
    op.drop_column("file_versions", "multipart_upload_id")
