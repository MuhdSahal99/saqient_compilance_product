"""review dataset inputs (engine deterministic-1.1.0)

Reviews can take dataset versions and a rule pack version as inputs, with or
without a document. Check results gain a result hash and metadata, and two
data-check outcomes are added.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18 14:18:16.456766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OUTCOMES_OLD = (
    'match_found', 'no_match_found', 'needs_human_review', 'processing_error', 'not_applicable'
)
_OUTCOMES_NEW = (*_OUTCOMES_OLD, 'exceptions_found', 'no_exceptions')
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def _outcomes(values: tuple[str, ...]) -> None:
    allowed = ', '.join(repr(v) for v in values)
    for table, column in (('check_results', 'outcome'), ('findings', 'automated_outcome')):
        name = op.f(f'ck_{table}_check_outcome')
        op.drop_constraint(name, table, type_='check')
        op.create_check_constraint(name, table, f'{column} IN ({allowed})')


def upgrade() -> None:
    op.create_table('review_datasets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('trial_balance', 'general_ledger', 'sales_register', 'purchase_register', 'bank_statement', name='review_dataset_kind', native_enum=False, create_constraint=False, length=40), nullable=False),
    sa.Column('dataset_version_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("kind IN ('trial_balance', 'general_ledger', 'sales_register', 'purchase_register', 'bank_statement')", name=op.f('ck_review_datasets_review_dataset_kind')),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], name=op.f('fk_review_datasets_dataset_version_id_dataset_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_review_datasets_org_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], name=op.f('fk_review_datasets_review_id_reviews'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_datasets')),
    sa.UniqueConstraint('review_id', 'kind', name=op.f('uq_review_datasets_review_id'))
    )
    op.create_index(op.f('ix_review_datasets_org_id'), 'review_datasets', ['org_id'], unique=False)
    op.create_index(op.f('ix_review_datasets_review_id'), 'review_datasets', ['review_id'], unique=False)
    op.add_column('check_results', sa.Column('meta', _JSON, nullable=False, server_default='{}'))
    op.alter_column('check_results', 'meta', server_default=None)
    op.add_column('check_results', sa.Column('result_hash', sa.String(length=64), nullable=True))
    op.add_column('review_runs', sa.Column('inputs_snapshot', _JSON, nullable=False, server_default='{}'))
    op.alter_column('review_runs', 'inputs_snapshot', server_default=None)
    op.alter_column('review_runs', 'document_version_id', existing_type=sa.UUID(), nullable=True)
    op.add_column('reviews', sa.Column('rule_pack_version_id', sa.UUID(), nullable=True))
    op.add_column('reviews', sa.Column('as_of_date', sa.Date(), nullable=True))
    op.alter_column('reviews', 'document_version_id', existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(op.f('fk_reviews_rule_pack_version_id_rule_pack_versions'), 'reviews', 'rule_pack_versions', ['rule_pack_version_id'], ['id'], ondelete='RESTRICT')
    _outcomes(_OUTCOMES_NEW)


def downgrade() -> None:
    # Reviews that used datasets or data checks cannot be represented before 0007:
    # remove them (runs, results, findings and reports cascade).
    op.execute(
        "DELETE FROM reviews WHERE document_version_id IS NULL"
        " OR id IN (SELECT review_id FROM review_datasets)"
        " OR id IN (SELECT r.review_id FROM review_runs r JOIN check_results c ON c.run_id = r.id"
        "  WHERE c.outcome IN ('exceptions_found', 'no_exceptions'))"
    )
    _outcomes(_OUTCOMES_OLD)
    op.drop_constraint(op.f('fk_reviews_rule_pack_version_id_rule_pack_versions'), 'reviews', type_='foreignkey')
    op.alter_column('reviews', 'document_version_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('reviews', 'as_of_date')
    op.drop_column('reviews', 'rule_pack_version_id')
    op.alter_column('review_runs', 'document_version_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('review_runs', 'inputs_snapshot')
    op.drop_column('check_results', 'result_hash')
    op.drop_column('check_results', 'meta')
    op.drop_index(op.f('ix_review_datasets_review_id'), table_name='review_datasets')
    op.drop_index(op.f('ix_review_datasets_org_id'), table_name='review_datasets')
    op.drop_table('review_datasets')
