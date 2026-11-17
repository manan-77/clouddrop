"""create share_links and extend the audit actions

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "'file.uploaded', 'file.downloaded', 'file.deleted', 'folder.deleted', "
    "'permission.granted', 'permission.changed', 'permission.revoked', 'auth.login'"
)
NEW_ACTIONS = OLD_ACTIONS + ", 'share_link.created', 'share_link.revoked', 'share_link.downloaded'"


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_share_links_file_id_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_share_links_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_share_links_token_hash")),
    )
    op.create_index("ix_share_links_file_id", "share_links", ["file_id"])
    op.create_index(op.f("ix_share_links_created_by"), "share_links", ["created_by"])
    op.drop_constraint(op.f("ck_audit_events_action_valid"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action_valid"), "audit_events", f"action IN ({NEW_ACTIONS})"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM audit_events WHERE action IN "
        "('share_link.created', 'share_link.revoked', 'share_link.downloaded')"
    )
    op.drop_constraint(op.f("ck_audit_events_action_valid"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action_valid"), "audit_events", f"action IN ({OLD_ACTIONS})"
    )
    op.drop_index(op.f("ix_share_links_created_by"), table_name="share_links")
    op.drop_index("ix_share_links_file_id", table_name="share_links")
    op.drop_table("share_links")
