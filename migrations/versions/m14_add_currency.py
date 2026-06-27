"""Add currency column to amount-carrying tables

Revision ID: m14_add_currency
Revises: m13_recurring_group_expenses
Create Date: 2026-06-27

"""

import sqlalchemy as sa
from alembic import op

revision = "m14_add_currency"
down_revision = "m13_recurring_group_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE recurring_incomes ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE income_instances ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE recurring_personal_expenses ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE recurring_personal_expense_instances "
            "ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE recurring_group_expenses ADD COLUMN IF NOT EXISTS currency VARCHAR NOT NULL DEFAULT 'ARS'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS currency"))
    conn.execute(sa.text("ALTER TABLE recurring_incomes DROP COLUMN IF EXISTS currency"))
    conn.execute(sa.text("ALTER TABLE income_instances DROP COLUMN IF EXISTS currency"))
    conn.execute(sa.text("ALTER TABLE recurring_personal_expenses DROP COLUMN IF EXISTS currency"))
    conn.execute(sa.text("ALTER TABLE recurring_personal_expense_instances DROP COLUMN IF EXISTS currency"))
    conn.execute(sa.text("ALTER TABLE recurring_group_expenses DROP COLUMN IF EXISTS currency"))
