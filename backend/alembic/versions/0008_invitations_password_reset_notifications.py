"""invitations, password reset tokens and the notification log

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18 14:31:12.270629

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('invitations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', sa.Enum('org_admin', 'reviewer', 'analyst', 'viewer', name='invitation_role', native_enum=False, create_constraint=False, length=40), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('invited_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_by_id', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('org_admin', 'reviewer', 'analyst', 'viewer')", name=op.f('ck_invitations_invitation_role')),
    sa.ForeignKeyConstraint(['accepted_by_id'], ['users.id'], name=op.f('fk_invitations_accepted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], name=op.f('fk_invitations_invited_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_invitations_org_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invitations_token_hash'))
    )
    op.create_index(op.f('ix_invitations_org_id'), 'invitations', ['org_id'], unique=False)
    op.create_index('uq_invitations_org_email_open', 'invitations', ['org_id', 'email'], unique=True, postgresql_where='accepted_at IS NULL AND revoked_at IS NULL')
    op.create_table('notification_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('invitation', 'task_due_reminder', name='notification_kind', native_enum=False, create_constraint=False, length=40), nullable=False),
    sa.Column('recipient_user_id', sa.UUID(), nullable=True),
    sa.Column('recipient_email', sa.String(length=320), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('object_type', sa.String(length=40), nullable=False),
    sa.Column('object_id', sa.UUID(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('status', sa.Enum('sent', 'failed', 'disabled', name='notification_status', native_enum=False, create_constraint=False, length=40), nullable=False),
    sa.Column('error', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('invitation', 'task_due_reminder')", name=op.f('ck_notification_log_notification_kind')),
    sa.CheckConstraint("status IN ('sent', 'failed', 'disabled')", name=op.f('ck_notification_log_notification_status')),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_notification_log_org_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], name=op.f('fk_notification_log_recipient_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_log')),
    sa.UniqueConstraint('dedupe_key', name=op.f('uq_notification_log_dedupe_key'))
    )
    op.create_index(op.f('ix_notification_log_org_id'), 'notification_log', ['org_id'], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_tokens_token_hash'))
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_index(op.f('ix_notification_log_org_id'), table_name='notification_log')
    op.drop_table('notification_log')
    op.drop_index('uq_invitations_org_email_open', table_name='invitations', postgresql_where='accepted_at IS NULL AND revoked_at IS NULL')
    op.drop_index(op.f('ix_invitations_org_id'), table_name='invitations')
    op.drop_table('invitations')
