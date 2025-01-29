"""Add parent_expense_id column to expenses table

Revision ID: add_parent_expense_id_20250128
Revises:
Create Date: 2025-01-28 14:17:40.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_parent_expense_id_20250128"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add parent_expense_id column to expenses table"""
    # Add parent_expense_id column with foreign key reference to expenses.id
    # Using a transaction to ensure atomicity
    with op.get_context().begin_transaction():
        # First check if the column exists
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [col["name"] for col in inspector.get_columns("expenses")]

        if "parent_expense_id" not in columns:
            op.add_column("expenses", sa.Column("parent_expense_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_expense_parent",
                "expenses",
                "expenses",
                ["parent_expense_id"],
                ["id"],
                ondelete="CASCADE",  # When parent is deleted, delete all children
            )


def downgrade() -> None:
    """Drop parent_expense_id column from expenses table"""
    # Using a transaction to ensure atomicity
    with op.get_context().begin_transaction():
        # First check if the constraint exists
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        fks = inspector.get_foreign_keys("expenses")
        for fk in fks:
            if fk["name"] == "fk_expense_parent":
                op.drop_constraint("fk_expense_parent", "expenses", type_="foreignkey")
                break

        # Then check if the column exists before trying to drop it
        columns = [col["name"] for col in inspector.get_columns("expenses")]
        if "parent_expense_id" in columns:
            op.drop_column("expenses", "parent_expense_id")
