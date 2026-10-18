"""Hash-chained audit log: seq, prev_hash, hash; backfill; block UPDATE.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

"""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENESIS = "0" * 64


def _hash(row: sa.Row, seq: int, prev: str) -> str:
    # Frozen copy of app.services.audit.compute_hash (hash version v1).
    payload = {
        "v": "v1",
        "id": str(row.id),
        "org_id": str(row.org_id) if row.org_id else None,
        "seq": seq,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "action": row.action,
        "object_type": row.object_type,
        "object_id": str(row.object_id) if row.object_id else None,
        "meta": row.metadata or {},
        "created_at": row.created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "prev_hash": prev,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_events", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("hash", sa.String(64), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, org_id, actor_id, action, object_type, object_id, metadata, created_at "
            "FROM audit_events ORDER BY org_id NULLS FIRST, created_at, id"
        )
    ).fetchall()
    state: dict[object, tuple[int, str]] = {}
    for row in rows:
        seq, prev = state.get(row.org_id, (0, GENESIS))
        seq += 1
        h = _hash(row, seq, prev)
        conn.execute(
            sa.text("UPDATE audit_events SET seq = :s, prev_hash = :p, hash = :h WHERE id = :id"),
            {"s": seq, "p": prev, "h": h, "id": row.id},
        )
        state[row.org_id] = (seq, h)

    for col in ("seq", "prev_hash", "hash"):
        op.alter_column("audit_events", col, nullable=False)
    op.create_unique_constraint(
        "uq_audit_events_org_seq",
        "audit_events",
        ["org_id", "seq"],
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(op.f("fk_audit_events_actor_id_users"), "audit_events", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_audit_events_actor_id_users"), "audit_events", "users", ["actor_id"], ["id"]
    )
    op.execute(
        """
        CREATE FUNCTION audit_events_no_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_no_update();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_no_update ON audit_events")
    op.execute("DROP FUNCTION audit_events_no_update()")
    op.drop_constraint(op.f("fk_audit_events_actor_id_users"), "audit_events", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_audit_events_actor_id_users"),
        "audit_events",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("uq_audit_events_org_seq", "audit_events", type_="unique")
    op.drop_column("audit_events", "hash")
    op.drop_column("audit_events", "prev_hash")
    op.drop_column("audit_events", "seq")
