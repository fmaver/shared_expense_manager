"""Add archived_at to group_memberships

Archiving is per member, so it belongs on the membership rather than on the group: one member
can archive a group while everyone else keeps using it.

Revision ID: m15_archive_group_memberships
Revises: m14_add_currency
Create Date: 2026-09-05

"""

import sqlalchemy as sa
from alembic import op

revision = "m15_archive_group_memberships"
down_revision = "m14_add_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS because create_all may already have added the column on startup.
    # Nullable with no default, so every existing membership reads as not archived.
    op.get_bind().execute(sa.text("ALTER TABLE group_memberships ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE group_memberships DROP COLUMN IF EXISTS archived_at"))
