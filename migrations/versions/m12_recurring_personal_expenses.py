"""Add recurring personal expenses tables

Revision ID: m12_recurring_personal_expenses
Revises: m11_recurring_income_start_month
Create Date: 2026-06-02

"""

import sqlalchemy as sa
from alembic import op

revision = "m12_recurring_personal_expenses"
down_revision = "m11_recurring_income_start_month"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Recurring personal expense templates table
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS recurring_personal_expenses (
                id SERIAL PRIMARY KEY,
                personal_group_id INTEGER NOT NULL REFERENCES groups(id),
                owner_member_id INTEGER NOT NULL REFERENCES members(id),
                label VARCHAR(255) NOT NULL,
                amount FLOAT NOT NULL,
                category_name VARCHAR(50) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                start_year INTEGER,
                start_month INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                updated_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )

    # Per-month recurring expense instances
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS recurring_personal_expense_instances (
                id SERIAL PRIMARY KEY,
                personal_group_id INTEGER NOT NULL REFERENCES groups(id),
                recurring_expense_id INTEGER NOT NULL
                    REFERENCES recurring_personal_expenses(id) ON DELETE CASCADE,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                label VARCHAR(255) NOT NULL,
                amount FLOAT NOT NULL,
                category_name VARCHAR(50) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT ck_recurring_expense_instance_amount CHECK (amount > 0)
            )
            """
        )
    )

    # Idempotency guard: one snapshot per template per month
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_expense_instance_per_month
            ON recurring_personal_expense_instances (personal_group_id, recurring_expense_id, year, month)
            """
        )
    )

    # Covering index for ledger queries
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_recurring_expense_instances_group_period
            ON recurring_personal_expense_instances (personal_group_id, year, month)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_recurring_expense_instances_group_period", table_name="recurring_personal_expense_instances")
    op.drop_index("uq_recurring_expense_instance_per_month", table_name="recurring_personal_expense_instances")
    op.drop_table("recurring_personal_expense_instances")
    op.drop_table("recurring_personal_expenses")
