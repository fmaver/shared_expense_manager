"""Add chat_sessions and processed_wpp_messages tables for DB-backed chatbot state and idempotency.

Revision ID: m3_chat_sessions
Revises: 20250318_add_last_wpp, add_member_auth_fields_20250128, c1bd079de122
Create Date: 2026-05-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m3_chat_sessions"
down_revision: Union[str, tuple, None] = ("20250318_add_last_wpp", "add_member_auth_fields_20250128", "c1bd079de122")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create chat_sessions and processed_wpp_messages tables."""
    op.create_table(
        "chat_sessions",
        sa.Column("telephone", sa.String(20), primary_key=True),
        sa.Column("estado", sa.String(50), nullable=False, server_default="inicial"),
        sa.Column("expense_data", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "processed_wpp_messages",
        sa.Column("message_id", sa.Text, primary_key=True),
        sa.Column("processed_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_processed_wpp_messages_processed_at", "processed_wpp_messages", ["processed_at"])


def downgrade() -> None:
    """Drop chat_sessions and processed_wpp_messages tables."""
    op.drop_index("ix_processed_wpp_messages_processed_at", table_name="processed_wpp_messages")
    op.drop_table("processed_wpp_messages")
    op.drop_table("chat_sessions")
