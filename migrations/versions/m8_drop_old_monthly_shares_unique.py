"""drop old monthly shares unique constraint

Revision ID: m8_drop_old_monthly_shares_unique
Revises: m7_migrate_to_default_group
Create Date: 2026-05-16

"""

from alembic import op

revision = "m8_drop_shares_constraint"
down_revision = "m7_migrate_to_default_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use IF EXISTS so this is a no-op when the constraint was never created (e.g. fresh create_all envs)
    op.execute("ALTER TABLE monthly_shares DROP CONSTRAINT IF EXISTS monthly_shares_year_month_key")


def downgrade() -> None:
    op.create_unique_constraint("monthly_shares_year_month_key", "monthly_shares", ["year", "month"])
