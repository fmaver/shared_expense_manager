"""Add authentication fields to members table

Revision ID: add_member_auth_fields_20250128
Revises: add_parent_expense_id_20250128
Create Date: 2025-01-28 14:30:15.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_member_auth_fields_20250128"
down_revision: str = "add_parent_expense_id_20250128"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add authentication fields to members table"""
    # Using a transaction to ensure atomicity
    with op.get_context().begin_transaction():
        # First check if the columns exist
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [col["name"] for col in inspector.get_columns("members")]

        # Add email column if it doesn't exist
        if "email" not in columns:
            op.add_column("members", sa.Column("email", sa.String(255), nullable=True))
            # Add unique constraint to email
            op.create_unique_constraint("uq_members_email", "members", ["email"])

        # Add hashed_password column if it doesn't exist
        if "hashed_password" not in columns:
            op.add_column("members", sa.Column("hashed_password", sa.String(255), nullable=True))

        # Create an index on email for faster lookups
        if "ix_members_email" not in [idx["name"] for idx in inspector.get_indexes("members")]:
            op.create_index("ix_members_email", "members", ["email"])


def downgrade() -> None:
    """Drop authentication fields from members table"""
    # Using a transaction to ensure atomicity
    with op.get_context().begin_transaction():
        conn = op.get_bind()
        inspector = sa.inspect(conn)

        # Drop index if it exists
        indexes = [idx["name"] for idx in inspector.get_indexes("members")]
        if "ix_members_email" in indexes:
            op.drop_index("ix_members_email")

        # Drop unique constraint if it exists
        constraints = [const["name"] for const in inspector.get_unique_constraints("members")]
        if "uq_members_email" in constraints:
            op.drop_constraint("uq_members_email", "members", type_="unique")

        # Drop columns if they exist
        columns = [col["name"] for col in inspector.get_columns("members")]
        if "hashed_password" in columns:
            op.drop_column("members", "hashed_password")
        if "email" in columns:
            op.drop_column("members", "email")
