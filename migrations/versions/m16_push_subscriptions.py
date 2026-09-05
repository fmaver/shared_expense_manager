"""Add push_subscriptions

One row per browser a member registered for web push. A member may have several — phone plus
laptop — so this is a table rather than a column on members.

Revision ID: m16_push_subscriptions
Revises: m15_archive_group_memberships
Create Date: 2026-09-05

"""

import sqlalchemy as sa
from alembic import op

revision = "m16_push_subscriptions"
down_revision = "m15_archive_group_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS because create_all may already have made the table on startup.
    op.get_bind().execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh VARCHAR(255) NOT NULL,
                auth VARCHAR(255) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_used_at TIMESTAMP NULL
            )
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS push_subscriptions"))
