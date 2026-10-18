"""mark source blocks read by OCR

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18 14:42:23.307183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('source_blocks', sa.Column('is_ocr', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('source_blocks', sa.Column('ocr_confidence', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('source_blocks', 'ocr_confidence')
    op.drop_column('source_blocks', 'is_ocr')
