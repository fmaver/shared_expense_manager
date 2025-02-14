"""add notification preference to member

Revision ID: c1bd079de122
Revises:
Create Date: 2025-02-14 09:56:17.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from template.domain.models.enums import NotificationType

# revision identifiers, used by Alembic.
revision: str = "c1bd079de122"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create NotificationType enum in the database"""
    notification_type = sa.Enum(NotificationType, name="notificationtype")
    notification_type.create(op.get_bind(), checkfirst=True)

    # Add notification_preference column with default value
    op.add_column(
        "members",
        sa.Column(
            "notification_preference", notification_type, nullable=False, server_default=NotificationType.NONE.value
        ),
    )


def downgrade() -> None:
    """Remove notification_preference column"""
    op.drop_column("members", "notification_preference")

    # Remove NotificationType enum
    notification_type = sa.Enum(NotificationType, name="notificationtype")
    notification_type.drop(op.get_bind(), checkfirst=True)
