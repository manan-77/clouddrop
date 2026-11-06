"""index refresh_tokens expires_at

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_expires_at"), table_name="refresh_tokens")
