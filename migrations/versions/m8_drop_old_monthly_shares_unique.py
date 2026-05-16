"""drop old monthly shares unique constraint

Revision ID: m8_drop_old_monthly_shares_unique
Revises: m7_migrate_to_default_group
Create Date: 2026-05-16

"""
from alembic import op

revision = 'm8_drop_old_monthly_shares_unique'
down_revision = 'm7_migrate_to_default_group'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old (year, month) unique constraint if it exists
    try:
        op.drop_constraint('monthly_shares_year_month_key', 'monthly_shares', type_='unique')
    except Exception:
        pass  # constraint may not exist in all environments


def downgrade() -> None:
    op.create_unique_constraint('monthly_shares_year_month_key', 'monthly_shares', ['year', 'month'])
