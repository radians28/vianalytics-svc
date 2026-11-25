"""add custom_period

Revision ID: 3e6f881832f9
Revises: 006d5e137b8a
Create Date: 2026-10-05 15:33:56.919257

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e6f881832f9'
down_revision = '006d5e137b8a'
branch_labels = None
depends_on = None


SCHEMA = 'royal_canin'


def upgrade():
    # this revision runs before a1c4e7f20b01, which also creates the schema (IF NOT EXISTS)
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table('custom_period',
    sa.Column('period_key', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('period', sa.String(length=3), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.PrimaryKeyConstraint('period_key'),
    schema=SCHEMA
    )


def downgrade():
    op.drop_table('custom_period', schema=SCHEMA)
    # later revisions are already downgraded here, so the schema is empty (a1c4e7f20b01 left it for this table)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
