"""create audit_events

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = (
    "'file.uploaded', 'file.downloaded', 'file.deleted', 'folder.deleted', "
    "'permission.granted', 'permission.changed', 'permission.revoked', "
    "'auth.login', 'auth.login_failed'"
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("resource_type", sa.String(length=10), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.String(length=40), nullable=True),
        sa.Column("result", sa.String(length=10), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"action IN ({ACTIONS})", name=op.f("ck_audit_events_action_valid")),
        sa.CheckConstraint(
            "result IN ('success', 'failure')", name=op.f("ck_audit_events_result_valid")
        ),
        sa.CheckConstraint(
            "resource_type IN ('file', 'folder', 'user')",
            name=op.f("ck_audit_events_resource_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_audit_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_target_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"])
    op.create_index(
        "ix_audit_events_workspace_created",
        "audit_events",
        ["workspace_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_events_workspace_resource", "audit_events", ["workspace_id", "resource_id"]
    )
    # The target_user_id foreign key column gets its own index too.
    op.create_index(op.f("ix_audit_events_target_user_id"), "audit_events", ["target_user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_target_user_id"), table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_created", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_table("audit_events")
