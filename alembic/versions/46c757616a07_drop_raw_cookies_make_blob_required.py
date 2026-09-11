"""drop_raw_cookies_make_blob_required

Revision ID: 46c757616a07
Revises: 4bee29b72432
Create Date: 2026-09-12 02:00:07.402729

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46c757616a07'
down_revision: Union[str, Sequence[str], None] = '4bee29b72432'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop raw_cookies column; session_blob becomes the sole source of truth (NOT NULL)."""
    with op.batch_alter_table('web_sessions', schema=None) as batch_op:
        batch_op.drop_column('raw_cookies')
        batch_op.alter_column('session_blob', existing_type=sa.BLOB(), nullable=False)


def downgrade() -> None:
    """Restore raw_cookies column (nullable for backwards compat)."""
    with op.batch_alter_table('web_sessions', schema=None) as batch_op:
        batch_op.alter_column('session_blob', existing_type=sa.BLOB(), nullable=True)
        batch_op.add_column(sa.Column('raw_cookies', sa.TEXT(), nullable=True))
