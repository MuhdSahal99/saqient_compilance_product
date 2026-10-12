"""ORM models. Every tenant-owned table carries a non-null ``org_id``."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint so adding values is a simple migration.
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=40,
        values_callable=lambda e: [m.value for m in e],
    )


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )


# ---------------------------------------------------------------- enums


class Role(str, enum.Enum):
    ORG_ADMIN = "org_admin"
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    VIEWER = "viewer"


class VersionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChecklistKind(str, enum.Enum):
    SYNTHETIC_DEMO = "synthetic_demo"
    INTERNAL_POLICY = "internal_policy"
    EXTERNAL_REGULATORY = "external_regulatory"


class ChecklistState(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SourceVerification(str, enum.Enum):
    SYNTHETIC = "synthetic"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CheckOutcome(str, enum.Enum):
    MATCH_FOUND = "match_found"
    NO_MATCH_FOUND = "no_match_found"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    PROCESSING_ERROR = "processing_error"
    NOT_APPLICABLE = "not_applicable"


class JobKind(str, enum.Enum):
    EXTRACT = "extract"
    REVIEW_RUN = "review_run"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    SIGNED_OFF = "signed_off"


class FindingStatus(str, enum.Enum):
    PROPOSED = "proposed"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    REMEDIATION_IN_PROGRESS = "remediation_in_progress"
    READY_FOR_REREVIEW = "ready_for_rereview"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"


# ---------------------------------------------------------------- identity


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_locale: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(_enum(Role, "role"))
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(lazy="joined")
    organization: Mapped[Organization] = relationship(lazy="joined")


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[uuid.UUID] = _org_fk()
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- documents


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    document_type: Mapped[str] = mapped_column(String(80), default="policy")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", order_by="DocumentVersion.version_number"
    )
    created_by: Mapped[User | None] = relationship(lazy="joined")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(10))  # pdf | docx | txt
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[VersionStatus] = mapped_column(
        _enum(VersionStatus, "version_status"), default=VersionStatus.PENDING
    )
    failure_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    block_count: Mapped[int] = mapped_column(Integer, default=0)
    extraction_warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")


class SourceBlock(Base):
    """A stable, citable unit of extracted text."""

    __tablename__ = "source_blocks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal"),
        Index("ix_source_blocks_version", "document_version_id"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str] = mapped_column(String(40))  # "p3.b2" (PDF) or "para-12" (DOCX/TXT)
    page_number: Mapped[int | None] = mapped_column(Integer)  # PDF only
    paragraph_number: Mapped[int | None] = mapped_column(Integer)  # DOCX/TXT only
    section_heading: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- checklists


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(300))
    publisher: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str | None] = mapped_column(String(1000))
    version_label: Mapped[str] = mapped_column(String(100), default="")
    verification_status: Mapped[SourceVerification] = mapped_column(
        _enum(SourceVerification, "source_verification"), default=SourceVerification.UNVERIFIED
    )
    excerpt: Mapped[str] = mapped_column(Text, default="")
    last_reviewed_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()


class Checklist(Base):
    __tablename__ = "checklists"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[ChecklistKind] = mapped_column(_enum(ChecklistKind, "checklist_kind"))
    created_at: Mapped[datetime] = _created()

    versions: Mapped[list[ChecklistVersion]] = relationship(
        back_populates="checklist", order_by="ChecklistVersion.version_number"
    )


class ChecklistVersion(Base):
    __tablename__ = "checklist_versions"
    __table_args__ = (UniqueConstraint("checklist_id", "version_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    checklist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklists.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[ChecklistState] = mapped_column(
        _enum(ChecklistState, "checklist_state"), default=ChecklistState.DRAFT
    )
    disclaimer: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    checklist: Mapped[Checklist] = relationship(back_populates="versions", lazy="joined")
    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="checklist_version", order_by="Requirement.ordinal"
    )


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("checklist_version_id", "code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_versions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    jurisdiction: Mapped[str | None] = mapped_column(String(100))
    document_type: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(100), default="general")
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    human_instructions: Mapped[str] = mapped_column(Text, default="")
    check_config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    source_reference: Mapped[str] = mapped_column(String(300), default="")
    effective_date: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(200), default="")

    checklist_version: Mapped[ChecklistVersion] = relationship(back_populates="requirements")
    source: Mapped[Source | None] = relationship(lazy="joined")


# ---------------------------------------------------------------- jobs, reviews


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, "job_kind"))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(300))
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"), default=ReviewStatus.DRAFT
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(lazy="joined")
    checklist_version: Mapped[ChecklistVersion] = relationship(lazy="joined")
    runs: Mapped[list[ReviewRun]] = relationship(
        back_populates="review", order_by="ReviewRun.created_at"
    )


class ReviewRun(Base):
    __tablename__ = "review_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    engine_version: Mapped[str] = mapped_column(String(40))
    engine_mode: Mapped[str] = mapped_column(String(40), default="deterministic")
    config_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    review: Mapped[Review] = relationship(back_populates="runs")
    job: Mapped[Job] = relationship(lazy="joined")
    results: Mapped[list[CheckResult]] = relationship(back_populates="run")


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (UniqueConstraint("run_id", "requirement_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_runs.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    outcome: Mapped[CheckOutcome] = mapped_column(_enum(CheckOutcome, "check_outcome"))
    needs_attention: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)

    run: Mapped[ReviewRun] = relationship(back_populates="results")
    requirement: Mapped[Requirement] = relationship(lazy="joined")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        # One automated finding per requirement per review: retries cannot duplicate.
        Index(
            "uq_findings_review_requirement",
            "review_id",
            "requirement_id",
            unique=True,
            postgresql_where="requirement_id IS NOT NULL",
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    check_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("check_results.id", ondelete="SET NULL")
    )
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    automated_outcome: Mapped[CheckOutcome | None] = mapped_column(
        _enum(CheckOutcome, "check_outcome")
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    status: Mapped[FindingStatus] = mapped_column(
        _enum(FindingStatus, "finding_status"), default=FindingStatus.PROPOSED
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_rationale: Mapped[str] = mapped_column(Text, default="")
    remediation_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    review: Mapped[Review] = relationship(lazy="joined")
    requirement: Mapped[Requirement | None] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    author: Mapped[User | None] = relationship(lazy="joined")


class ReportSnapshot(Base):
    """Immutable report content frozen at reviewer sign-off."""

    __tablename__ = "report_snapshots"
    __table_args__ = (UniqueConstraint("review_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_off_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditEvent(Base):
    """Application audit trail. Not tamper-proof."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = _created()

    actor: Mapped[User | None] = relationship(lazy="joined")
