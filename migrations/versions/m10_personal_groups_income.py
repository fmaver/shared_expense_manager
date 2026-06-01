"""Add personal group income tracking tables and constraints

Revision ID: m10_personal_groups_income
Revises: m9_invitations_and_stubs
Create Date: 2026-06-01

"""

import sqlalchemy as sa
from alembic import op

revision = "m10_personal_groups_income"
down_revision = "m9_invitations_and_stubs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Partial unique index: one personal group per owner member (enforced by group_type='personal')
    # Note: group_type and owner_member_id columns already exist on the groups table (added in m6)
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_one_personal_group_per_owner
            ON groups (owner_member_id)
            WHERE group_type = 'personal'
            """
        )
    )

    # Recurring income templates table
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS recurring_incomes (
                id SERIAL PRIMARY KEY,
                owner_member_id INTEGER NOT NULL REFERENCES members(id),
                personal_group_id INTEGER NOT NULL REFERENCES groups(id),
                label VARCHAR(255) NOT NULL,
                amount FLOAT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                updated_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )

    # Per-month income instances (both recurring snapshots and one-off variable entries)
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS income_instances (
                id SERIAL PRIMARY KEY,
                personal_group_id INTEGER NOT NULL REFERENCES groups(id),
                owner_member_id INTEGER NOT NULL REFERENCES members(id),
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                source VARCHAR(20) NOT NULL,
                recurring_income_id INTEGER REFERENCES recurring_incomes(id) ON DELETE SET NULL,
                label VARCHAR(255) NOT NULL,
                amount FLOAT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                updated_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT ck_income_instance_source CHECK (source IN ('recurring', 'variable')),
                CONSTRAINT ck_income_instance_recurring_has_id CHECK (
                    source != 'recurring' OR recurring_income_id IS NOT NULL
                )
            )
            """
        )
    )

    # Partial unique index: idempotency guard — one recurring snapshot per template per month
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_income_instance_recurring_per_month
            ON income_instances (personal_group_id, year, month, recurring_income_id)
            WHERE source = 'recurring'
            """
        )
    )

    # Covering index for ledger queries: fast lookup by group + year + month
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_income_instances_group_period
            ON income_instances (personal_group_id, year, month)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_income_instances_group_period", table_name="income_instances")
    op.drop_index("uq_income_instance_recurring_per_month", table_name="income_instances")
    op.drop_table("income_instances")
    op.drop_table("recurring_incomes")
    op.drop_index("uq_one_personal_group_per_owner", table_name="groups")
