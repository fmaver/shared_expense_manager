"""Add recurring group expenses tables

Revision ID: m13_recurring_group_expenses
Revises: m12_recurring_personal_expenses
Create Date: 2026-06-05

"""

import sqlalchemy as sa
from alembic import op

revision = "m13_recurring_group_expenses"
down_revision = "m12_recurring_personal_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Recurring group expense templates table
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS recurring_group_expenses (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                description VARCHAR(255) NOT NULL,
                amount FLOAT NOT NULL CHECK (amount > 0),
                category VARCHAR(50) NOT NULL,
                payer_id INTEGER NOT NULL REFERENCES members(id),
                payment_type VARCHAR(20) NOT NULL,
                split_strategy JSON NOT NULL,
                start_year INTEGER NOT NULL CHECK (start_year BETWEEN 2000 AND 2100),
                start_month INTEGER NOT NULL CHECK (start_month BETWEEN 1 AND 12),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )

    # Per-month recurring group expense instances
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS recurring_group_expense_instances (
                id SERIAL PRIMARY KEY,
                recurring_expense_id INTEGER NOT NULL REFERENCES recurring_group_expenses(id) ON DELETE CASCADE,
                group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_recurring_group_expense_instance
                    UNIQUE (group_id, recurring_expense_id, year, month)
            )
            """
        )
    )

    # Covering index for period queries
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_recurring_group_expense_instances_group_period
            ON recurring_group_expense_instances (group_id, year, month)
            """
        )
    )

    # Add nullable FK column to expenses referencing a recurring group expense template
    conn.execute(
        sa.text(
            """
            ALTER TABLE expenses ADD COLUMN IF NOT EXISTS
                recurring_template_id INTEGER REFERENCES recurring_group_expenses(id) ON DELETE SET NULL
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TABLE expenses DROP COLUMN IF EXISTS recurring_template_id"))
    conn.execute(
        sa.text("DROP INDEX IF EXISTS ix_recurring_group_expense_instances_group_period")
    )
    conn.execute(sa.text("DROP TABLE IF EXISTS recurring_group_expense_instances CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS recurring_group_expenses CASCADE"))
