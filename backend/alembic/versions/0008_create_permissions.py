"""create permissions

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("grantee_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=10), nullable=False),
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
        sa.CheckConstraint(
            "num_nonnulls(file_id, folder_id) = 1", name=op.f("ck_permissions_exactly_one_resource")
        ),
        sa.CheckConstraint("role IN ('viewer', 'editor')", name=op.f("ck_permissions_role_valid")),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_permissions_file_id_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folders.id"],
            name=op.f("fk_permissions_folder_id_folders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_id"],
            ["users.id"],
            name=op.f("fk_permissions_grantee_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_permissions_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
    )
    op.create_index(op.f("ix_permissions_grantee_id"), "permissions", ["grantee_id"])
    op.create_index(
        "uq_permissions_folder_grantee",
        "permissions",
        ["folder_id", "grantee_id"],
        unique=True,
        postgresql_where=sa.text("folder_id IS NOT NULL"),
    )
    op.create_index(
        "uq_permissions_file_grantee",
        "permissions",
        ["file_id", "grantee_id"],
        unique=True,
        postgresql_where=sa.text("file_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_permissions_file_grantee", table_name="permissions")
    op.drop_index("uq_permissions_folder_grantee", table_name="permissions")
    op.drop_index(op.f("ix_permissions_grantee_id"), table_name="permissions")
    op.drop_table("permissions")
