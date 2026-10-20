"""add upload_progress channel

Revision ID: 7c1d2e4f9a10
Revises: 3e6f881832f9
Create Date: 2026-10-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1d2e4f9a10'
down_revision = '3e6f881832f9'
branch_labels = None
depends_on = None


def upgrade():
    # server_default fills rows queued before the column existed
    with op.batch_alter_table('upload_progress', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=50), nullable=False, server_default=''))

    with op.batch_alter_table('upload_progress', schema=None) as batch_op:
        batch_op.alter_column('channel', server_default=None)


def downgrade():
    with op.batch_alter_table('upload_progress', schema=None) as batch_op:
        batch_op.drop_column('channel')
