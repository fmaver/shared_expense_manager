"""add groups schema

Revision ID: m6_add_groups_schema
Revises: m5_rename_compras
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = 'm6_add_groups_schema'
down_revision = 'm5_rename_compras'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('group_type', sa.String(20), nullable=False, server_default='regular'),
        sa.Column('owner_member_id', sa.Integer(), sa.ForeignKey('members.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        'group_memberships',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('member_id', sa.Integer(), sa.ForeignKey('members.id', ondelete='CASCADE'), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('group_id', 'member_id', name='uq_group_member'),
    )
    op.add_column('expenses', sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=True))
    op.add_column('monthly_shares', sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('monthly_shares', 'group_id')
    op.drop_column('expenses', 'group_id')
    op.drop_table('group_memberships')
    op.drop_table('groups')
