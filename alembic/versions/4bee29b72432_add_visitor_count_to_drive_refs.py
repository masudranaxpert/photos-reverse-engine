"""add visitor_count to drive_refs

Revision ID: 4bee29b72432
Revises: 
Create Date: 2026-09-11 17:34:49.219049

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bee29b72432'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c['name'] for c in inspector.get_columns('drive_refs')]

    with op.batch_alter_table('drive_refs', schema=None) as batch_op:
        if 'visitor_count' not in cols:
            batch_op.add_column(sa.Column('visitor_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.alter_column(
            'file_status',
            existing_type=sa.VARCHAR(length=50),
            nullable=False,
            existing_server_default=sa.text("'ok'")
        )

    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.INTEGER(),
               nullable=False,
               autoincrement=True)
        batch_op.alter_column('username',
               existing_type=sa.TEXT(),
               type_=sa.String(length=100),
               existing_nullable=False)
        batch_op.alter_column('password_hash',
               existing_type=sa.TEXT(),
               type_=sa.String(length=255),
               existing_nullable=False)
        batch_op.alter_column('is_active',
               existing_type=sa.INTEGER(),
               type_=sa.Boolean(),
               existing_nullable=False,
               existing_server_default=sa.text('1'))
        batch_op.alter_column('created_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))

    with op.batch_alter_table('download_cache', schema=None) as batch_op:
        batch_op.alter_column('media_key',
               existing_type=sa.TEXT(),
               type_=sa.String(length=100),
               nullable=False)
        batch_op.alter_column('dedup_key',
               existing_type=sa.TEXT(),
               type_=sa.String(length=100),
               existing_nullable=True)
        batch_op.alter_column('source',
               existing_type=sa.TEXT(),
               type_=sa.String(length=50),
               existing_nullable=False)
        batch_op.alter_column('expires_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               existing_nullable=False)
        batch_op.alter_column('created_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))

    with op.batch_alter_table('mobile_accounts', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.INTEGER(),
               nullable=False,
               autoincrement=True)
        batch_op.alter_column('email',
               existing_type=sa.TEXT(),
               type_=sa.String(length=150),
               existing_nullable=False)
        batch_op.alter_column('is_active',
               existing_type=sa.INTEGER(),
               type_=sa.Boolean(),
               existing_nullable=False,
               existing_server_default=sa.text('1'))
        batch_op.alter_column('created_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('updated_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))

    stream_cols = [c['name'] for c in inspector.get_columns('stream_cache')]
    if 'manifest' in stream_cols:
        with op.batch_alter_table('stream_cache', schema=None) as batch_op:
            batch_op.drop_column('manifest')

    with op.batch_alter_table('web_sessions', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.INTEGER(),
               nullable=False,
               autoincrement=True)
        batch_op.alter_column('session_id',
               existing_type=sa.TEXT(),
               type_=sa.String(length=50),
               existing_nullable=False)
        batch_op.alter_column('name',
               existing_type=sa.TEXT(),
               type_=sa.String(length=100),
               existing_nullable=False)
        batch_op.alter_column('account_email',
               existing_type=sa.TEXT(),
               type_=sa.String(length=150),
               existing_nullable=True)
        batch_op.alter_column('is_active',
               existing_type=sa.INTEGER(),
               type_=sa.Boolean(),
               existing_nullable=False,
               existing_server_default=sa.text('1'))
        batch_op.alter_column('created_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('updated_at',
               existing_type=sa.TIMESTAMP(),
               type_=sa.DateTime(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))


def downgrade() -> None:
    with op.batch_alter_table('drive_refs', schema=None) as batch_op:
        batch_op.drop_column('visitor_count')
