"""Add invitations, join links, and stub-member support

Revision ID: m9_invitations_and_stubs
Revises: m8_drop_shares_constraint
Create Date: 2026-05-24

"""

import sqlalchemy as sa
from alembic import op

revision = "m9_invitations_and_stubs"
down_revision = "m8_drop_shares_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Collapse duplicate telephone values before adding the unique index.
    # Keep the row with the most recent last_wpp_chat_datetime (then lowest id); null out duplicates.
    conn.execute(
        sa.text(
            """
            UPDATE members
            SET telephone = NULL
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY telephone
                               ORDER BY last_wpp_chat_datetime DESC NULLS LAST, id ASC
                           ) AS rn
                    FROM members
                    WHERE telephone IS NOT NULL
                ) ranked
                WHERE rn > 1
            )
        """
        )
    )

    # Allow NULL on email and telephone — idempotent: only drop NOT NULL if the column is currently NOT NULL.
    conn.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'members' AND column_name = 'email' AND is_nullable = 'NO'
                ) THEN
                    ALTER TABLE members ALTER COLUMN email DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'members' AND column_name = 'telephone' AND is_nullable = 'NO'
                ) THEN
                    ALTER TABLE members ALTER COLUMN telephone DROP NOT NULL;
                END IF;
            END $$;
        """
        )
    )

    # Track when a phone number was verified via WhatsApp roundtrip — idempotent.
    conn.execute(sa.text("ALTER TABLE members ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMPTZ NULL"))

    # Backfill: members who have chatted have already proven phone ownership.
    conn.execute(
        sa.text(
            "UPDATE members SET phone_verified_at = last_wpp_chat_datetime"
            " WHERE last_wpp_chat_datetime IS NOT NULL AND phone_verified_at IS NULL"
        )
    )

    # Partial unique index: no two members may share the same telephone (when not NULL) — idempotent.
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_member_telephone
            ON members (telephone) WHERE telephone IS NOT NULL
        """
        )
    )

    # Group invitations table — idempotent.
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS group_invitations (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                inviter_id INTEGER NOT NULL REFERENCES members(id),
                invitee_member_id INTEGER REFERENCES members(id),
                channel VARCHAR(10) NOT NULL,
                target VARCHAR(255),
                token VARCHAR(64) NOT NULL UNIQUE,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                expires_at TIMESTAMP NOT NULL,
                accepted_at TIMESTAMP,
                accepted_by_member_id INTEGER REFERENCES members(id)
            )
        """
        )
    )
    conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_group_invitations_token ON group_invitations (token)"))
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_group_invitations_group_status" " ON group_invitations (group_id, status)"
        )
    )

    # Shareable group join links table — idempotent.
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS group_join_links (
                group_id INTEGER PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                created_by_member_id INTEGER NOT NULL REFERENCES members(id)
            )
        """
        )
    )
    conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_group_join_links_token ON group_join_links (token)"))


def downgrade() -> None:
    op.drop_index("ix_group_join_links_token", table_name="group_join_links")
    op.drop_table("group_join_links")
    op.drop_index("ix_group_invitations_group_status", table_name="group_invitations")
    op.drop_index("ix_group_invitations_token", table_name="group_invitations")
    op.drop_table("group_invitations")
    op.drop_index("uq_member_telephone", table_name="members")
    op.drop_column("members", "phone_verified_at")
    op.alter_column("members", "telephone", existing_type=sa.String(20), nullable=False)
    op.alter_column("members", "email", existing_type=sa.String(255), nullable=False)
