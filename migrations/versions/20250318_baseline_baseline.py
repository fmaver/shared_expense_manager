"""baseline

Revision ID: 20250318_baseline
Revises: 
Create Date: 2025-03-18 17:11:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250318_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tables based on current database state
    op.create_table(
        'members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('last_wpp_chat_datetime', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('member_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'monthly_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('member_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['member_id'], ['members.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('monthly_shares')
    op.drop_table('expenses')
    op.drop_table('members')
