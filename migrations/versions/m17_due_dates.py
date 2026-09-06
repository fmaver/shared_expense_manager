"""due dates and their sent reminders

Revision ID: m17_due_dates
Revises: m16_push_subscriptions
"""

import sqlalchemy as sa
from alembic import op

revision = "m17_due_dates"
down_revision = "m16_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "due_dates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("created_by_member_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("category_name", sa.String(length=50), nullable=False, server_default="servicios"),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("every_n_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("anchor_year", sa.Integer(), nullable=False),
        sa.Column("anchor_month", sa.Integer(), nullable=False),
        sa.Column("notify_days_before", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "due_date_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("due_date_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["due_date_id"], ["due_dates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("due_date_id", "member_id", "due_on", name="uq_due_date_reminder"),
    )


def downgrade() -> None:
    op.drop_table("due_date_reminders")
    op.drop_table("due_dates")
