"""add_last_wpp_chat_datetime

Revision ID: 20250318_add_last_wpp
Revises: 20250318_baseline
Create Date: 2025-03-18 17:16:00

"""

from typing import Sequence, Union

# pylint: disable=invalid-name
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250318_add_last_wpp"
down_revision: Union[str, None] = "20250318_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add last wpp chat datetime column to members table"""
    op.add_column("members", sa.Column("last_wpp_chat_datetime", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove last wpp chat datetime column from members table"""
    op.drop_column("members", "last_wpp_chat_datetime")
