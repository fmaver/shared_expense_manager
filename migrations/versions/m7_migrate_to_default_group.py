"""migrate to default group

Revision ID: m7_migrate_to_default_group
Revises: m6_add_groups_schema
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'm7_migrate_to_default_group'
down_revision = 'm6_add_groups_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Insert default group
    conn.execute(text(
        "INSERT INTO groups (name, status, group_type) VALUES ('Fran & Guada', 'active', 'regular')"
    ))
    default_group_id = conn.execute(text("SELECT id FROM groups WHERE name = 'Fran & Guada'")).scalar()

    # Add all existing members to default group
    conn.execute(text(
        f"INSERT INTO group_memberships (group_id, member_id) SELECT {default_group_id}, id FROM members"
    ))

    # Backfill expenses and monthly_shares
    conn.execute(text(f"UPDATE expenses SET group_id = {default_group_id} WHERE group_id IS NULL"))
    conn.execute(text(f"UPDATE monthly_shares SET group_id = {default_group_id} WHERE group_id IS NULL"))

    # Make group_id NOT NULL
    op.alter_column('expenses', 'group_id', nullable=False)
    op.alter_column('monthly_shares', 'group_id', nullable=False)

    # Add composite unique index on monthly_shares
    op.create_unique_constraint(
        'uq_monthly_shares_group_year_month',
        'monthly_shares',
        ['group_id', 'year', 'month']
    )


def downgrade() -> None:
    op.drop_constraint('uq_monthly_shares_group_year_month', 'monthly_shares', type_='unique')
    op.alter_column('expenses', 'group_id', nullable=True)
    op.alter_column('monthly_shares', 'group_id', nullable=True)
    conn = op.get_bind()
    conn.execute(text("UPDATE expenses SET group_id = NULL"))
    conn.execute(text("UPDATE monthly_shares SET group_id = NULL"))
    conn.execute(text("DELETE FROM group_memberships"))
    conn.execute(text("DELETE FROM groups"))
