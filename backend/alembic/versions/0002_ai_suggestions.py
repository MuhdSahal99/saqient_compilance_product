"""AI suggestions: runs, per-requirement suggestions, and the finding link.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
_ASSESSMENTS = ("addressed", "not_addressed", "unclear", "invalid_output")
_STATUSES = ("pending", "accepted", "rejected")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_job_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_job_kind"), "jobs", _in("kind", ("extract", "review_run", "ai_suggest"))
    )

    op.create_table(
        "ai_suggestion_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("checklist_version_id", sa.UUID(), nullable=False),
        sa.Column("warnings", _JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_ai_suggestion_runs_job_id_jobs")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_ai_suggestion_runs_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_ai_suggestion_runs_requested_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_ai_suggestion_runs_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_suggestion_runs")),
    )
    op.create_index(op.f("ix_ai_suggestion_runs_org_id"), "ai_suggestion_runs", ["org_id"])
    op.create_index(op.f("ix_ai_suggestion_runs_review_id"), "ai_suggestion_runs", ["review_id"])

    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column(
            "assessment",
            sa.Enum(
                *_ASSESSMENTS,
                name="ai_assessment",
                native_enum=False,
                create_constraint=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", _JSON, nullable=False),
        sa.Column("rejected_citations", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *_STATUSES,
                name="ai_suggestion_status",
                native_enum=False,
                create_constraint=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("decided_by_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            _in("assessment", _ASSESSMENTS), name=op.f("ck_ai_suggestions_ai_assessment")
        ),
        sa.CheckConstraint(
            _in("status", _STATUSES), name=op.f("ck_ai_suggestions_ai_suggestion_status")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_ai_suggestions_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_ai_suggestions_finding_id_findings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_ai_suggestions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["requirements.id"],
            name=op.f("fk_ai_suggestions_requirement_id_requirements"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_ai_suggestions_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_suggestion_runs.id"],
            name=op.f("fk_ai_suggestions_run_id_ai_suggestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_suggestions")),
        sa.UniqueConstraint("run_id", "requirement_id", name=op.f("uq_ai_suggestions_run_id")),
    )
    op.create_index(op.f("ix_ai_suggestions_org_id"), "ai_suggestions", ["org_id"])
    op.create_index(op.f("ix_ai_suggestions_review_id"), "ai_suggestions", ["review_id"])
    op.create_index(op.f("ix_ai_suggestions_run_id"), "ai_suggestions", ["run_id"])

    op.add_column("findings", sa.Column("ai_suggestion_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_findings_ai_suggestion_id_ai_suggestions"),
        "findings",
        "ai_suggestions",
        ["ai_suggestion_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_findings_ai_suggestion_id_ai_suggestions"), "findings", type_="foreignkey"
    )
    op.drop_column("findings", "ai_suggestion_id")
    op.drop_table("ai_suggestions")
    op.drop_table("ai_suggestion_runs")
    op.execute("DELETE FROM jobs WHERE kind = 'ai_suggest'")
    op.drop_constraint(op.f("ck_jobs_job_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_job_kind"), "jobs", _in("kind", ("extract", "review_run"))
    )
