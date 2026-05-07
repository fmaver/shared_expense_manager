"""Rename category 'compras' to 'supermercado' in expenses table.

Revision ID: m5_rename_compras
Revises: m4_reconcile_schema
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "m5_rename_compras"
down_revision: Union[str, None] = "m4_reconcile_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE expenses SET category = 'supermercado' WHERE category = 'compras'")


def downgrade() -> None:
    op.execute("UPDATE expenses SET category = 'compras' WHERE category = 'supermercado'")
