"""Reconcile monthly_shares and expenses schema drift between old Alembic baseline and current ORM.

The original baseline migration created a much simpler schema than the current ORM requires.
This migration is idempotent (checks column existence before altering) so it is safe to run
against the staging DB (which was bootstrapped from the old baseline) and is a no-op on prod
(where tables were created by create_all and already have the correct schema).

Revision ID: m4_reconcile_schema
Revises: m3_chat_sessions
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "m4_reconcile_schema"
down_revision: Union[str, None] = "m3_chat_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    """Return the set of column names currently in *table*."""
    conn = op.get_bind()
    return {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    """Add missing columns and remove obsolete ones introduced by the outdated baseline."""
    monthly_cols = _columns("monthly_shares")
    expense_cols = _columns("expenses")

    # ── monthly_shares ──────────────────────────────────────────────────────
    if "is_settled" not in monthly_cols:
        op.add_column(
            "monthly_shares",
            sa.Column("is_settled", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "balances" not in monthly_cols:
        op.add_column("monthly_shares", sa.Column("balances", sa.JSON(), nullable=True))
    if "member_id" in monthly_cols:
        op.drop_constraint("monthly_shares_member_id_fkey", "monthly_shares", type_="foreignkey")
        op.drop_column("monthly_shares", "member_id")
    if "amount" in monthly_cols and "balances" in _columns("monthly_shares"):
        op.drop_column("monthly_shares", "amount")

    # ── expenses ────────────────────────────────────────────────────────────
    if "member_id" in expense_cols and "payer_id" not in expense_cols:
        op.alter_column("expenses", "member_id", new_column_name="payer_id")
        expense_cols = _columns("expenses")  # refresh after rename

    for col_name, col_def in [
        ("category", sa.Column("category", sa.String(50), nullable=True)),
        ("payment_type", sa.Column("payment_type", sa.String(20), nullable=True)),
        ("installments", sa.Column("installments", sa.Integer(), nullable=True, server_default="1")),
        ("installment_no", sa.Column("installment_no", sa.Integer(), nullable=True, server_default="1")),
        ("split_strategy", sa.Column("split_strategy", sa.JSON(), nullable=True)),
        (
            "monthly_share_id",
            sa.Column("monthly_share_id", sa.Integer(), sa.ForeignKey("monthly_shares.id"), nullable=True),
        ),
    ]:
        if col_name not in expense_cols:
            op.add_column("expenses", col_def)  # type: ignore[arg-type]

    # Change date column from DateTime to Date if it is still DateTime
    conn = op.get_bind()
    date_type = next(
        (c["type"] for c in inspect(conn).get_columns("expenses") if c["name"] == "date"),
        None,
    )
    if date_type is not None and "timestamp" in str(date_type).lower():
        op.alter_column("expenses", "date", type_=sa.Date(), postgresql_using="date::date")


def downgrade() -> None:
    """Downgrade is intentionally a no-op — reversing schema reconciliation is not safe."""
