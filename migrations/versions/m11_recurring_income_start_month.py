"""Add start_year and start_month to recurring_incomes

Revision ID: m11_recurring_income_start_month
Revises: m10_personal_groups_income
Create Date: 2026-06-02

"""

import sqlalchemy as sa
from alembic import op

revision = "m11_recurring_income_start_month"
down_revision = "m10_personal_groups_income"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TABLE recurring_incomes ADD COLUMN IF NOT EXISTS start_year INTEGER"))
    conn.execute(sa.text("ALTER TABLE recurring_incomes ADD COLUMN IF NOT EXISTS start_month INTEGER"))

    # Backfill existing rows: use created_at year/month so they keep their current behaviour
    conn.execute(
        sa.text(
            """
            UPDATE recurring_incomes
            SET start_year  = EXTRACT(YEAR  FROM created_at)::INTEGER,
                start_month = EXTRACT(MONTH FROM created_at)::INTEGER
            WHERE start_year IS NULL OR start_month IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("recurring_incomes", "start_month")
    op.drop_column("recurring_incomes", "start_year")
