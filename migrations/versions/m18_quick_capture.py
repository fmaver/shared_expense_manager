"""expense drafts and shortcut tokens (quick capture)

Revision ID: m18_quick_capture
Revises: m17_due_dates
"""

import sqlalchemy as sa
from alembic import op

revision = "m18_quick_capture"
down_revision = "m17_due_dates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expense_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=True),
        sa.Column("payment_type", sa.String(length=20), nullable=True),
        sa.Column("installments", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("suggested_group_id", sa.Integer(), nullable=True),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("image_mime", sa.String(length=50), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["suggested_group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expense_drafts_member_status", "expense_drafts", ["member_id", "status"])
    op.create_table(
        "shortcut_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("shortcut_tokens")
    op.drop_index("ix_expense_drafts_member_status", table_name="expense_drafts")
    op.drop_table("expense_drafts")
