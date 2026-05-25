"""Add invitations, join links, and stub-member support

Revision ID: m9_invitations_and_stubs
Revises: m8_drop_shares_constraint
Create Date: 2026-05-24

"""

import sqlalchemy as sa
from alembic import op

revision = "m9_invitations_and_stubs"
down_revision = "m8_drop_shares_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Collapse duplicate telephone values before adding the unique index.
    # Keep the row with the most recent last_wpp_chat_datetime (then lowest id); null out duplicates.
    conn.execute(
        sa.text(
            """
            UPDATE members
            SET telephone = NULL
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY telephone
                               ORDER BY last_wpp_chat_datetime DESC NULLS LAST, id ASC
                           ) AS rn
                    FROM members
                    WHERE telephone IS NOT NULL
                ) ranked
                WHERE rn > 1
            )
        """
        )
    )

    # Allow NULL on email and telephone (stub members may lack one or both).
    op.alter_column("members", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("members", "telephone", existing_type=sa.String(20), nullable=True)

    # Track when a phone number was verified via WhatsApp roundtrip.
    op.add_column("members", sa.Column("phone_verified_at", sa.DateTime(), nullable=True))

    # Backfill: members who have chatted have already proven phone ownership.
    conn.execute(
        sa.text(
            "UPDATE members SET phone_verified_at = last_wpp_chat_datetime WHERE last_wpp_chat_datetime IS NOT NULL"
        )
    )

    # Partial unique index: no two members may share the same telephone (when not NULL).
    op.create_index(
        "uq_member_telephone",
        "members",
        ["telephone"],
        unique=True,
        postgresql_where=sa.text("telephone IS NOT NULL"),
    )

    # Group invitations table.
    op.create_table(
        "group_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inviter_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("invitee_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
    )
    op.create_index("ix_group_invitations_token", "group_invitations", ["token"], unique=True)
    op.create_index("ix_group_invitations_group_status", "group_invitations", ["group_id", "status"])

    # Shareable group join links table (one per group; rotating changes the token).
    op.create_table(
        "group_join_links",
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
    )
    op.create_index("ix_group_join_links_token", "group_join_links", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_group_join_links_token", table_name="group_join_links")
    op.drop_table("group_join_links")
    op.drop_index("ix_group_invitations_group_status", table_name="group_invitations")
    op.drop_index("ix_group_invitations_token", table_name="group_invitations")
    op.drop_table("group_invitations")
    op.drop_index("uq_member_telephone", table_name="members")
    op.drop_column("members", "phone_verified_at")
    op.alter_column("members", "telephone", existing_type=sa.String(20), nullable=False)
    op.alter_column("members", "email", existing_type=sa.String(255), nullable=False)
