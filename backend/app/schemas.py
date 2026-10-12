from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    ChecklistKind,
    ChecklistState,
    CheckOutcome,
    FindingStatus,
    JobStatus,
    ReviewStatus,
    Role,
    Severity,
    SourceVerification,
    VersionStatus,
)

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------- auth


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class SwitchOrgIn(BaseModel):
    org_id: uuid.UUID


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    preferred_locale: str
    is_demo: bool


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    is_demo: bool


class MembershipOut(BaseModel):
    org: OrgOut
    role: Role


class MeOut(BaseModel):
    user: UserOut
    org: OrgOut
    role: Role
    memberships: list[MembershipOut]
    csrf_token: str
    demo_mode: bool
    ai_enabled: bool


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: Role


# ---------------------------------------------------------------- jobs


class JobOut(ORM):
    id: uuid.UUID
    kind: str
    status: JobStatus
    attempts: int
    max_attempts: int
    progress: int
    cancel_requested: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------------------------------------------------------------- documents


class DocumentVersionOut(ORM):
    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    original_filename: str
    file_format: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: VersionStatus
    failure_message: str | None
    page_count: int | None
    block_count: int
    extraction_warnings: list[str]
    created_at: datetime
    processed_at: datetime | None


class DocumentOut(ORM):
    id: uuid.UUID
    title: str
    description: str
    document_type: str
    tags: list[str]
    is_demo: bool
    created_at: datetime
    updated_at: datetime
    created_by_name: str | None = None
    latest_version: DocumentVersionOut | None = None
    version_count: int = 0


class DocumentDetailOut(DocumentOut):
    versions: list[DocumentVersionOut]
    latest_job: JobOut | None = None


class DocumentUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    document_type: str | None = Field(default=None, min_length=1, max_length=80)
    tags: list[str] | None = Field(default=None, max_length=20)


class SourceBlockOut(ORM):
    id: uuid.UUID
    ordinal: int
    ref: str
    page_number: int | None
    paragraph_number: int | None
    section_heading: str | None
    text: str


# ---------------------------------------------------------------- checklists


class SourceOut(ORM):
    id: uuid.UUID
    title: str
    publisher: str
    url: str | None
    version_label: str
    verification_status: SourceVerification
    excerpt: str
    last_reviewed_at: date | None


class RequirementIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    jurisdiction: str | None = Field(default=None, max_length=100)
    document_type: str | None = Field(default=None, max_length=80)
    category: str = Field(default="general", max_length=100)
    severity: Severity
    human_instructions: str = Field(default="", max_length=5000)
    check_config: dict[str, Any] = Field(default_factory=lambda: {"type": "manual"})
    source_id: uuid.UUID | None = None
    source_reference: str = Field(default="", max_length=300)
    effective_date: date | None = None
    owner: str = Field(default="", max_length=200)


class RequirementOut(ORM):
    id: uuid.UUID
    ordinal: int
    code: str
    title: str
    description: str
    jurisdiction: str | None
    document_type: str | None
    category: str
    severity: Severity
    human_instructions: str
    check_config: dict[str, Any]
    source_reference: str
    effective_date: date | None
    owner: str
    source: SourceOut | None


class ChecklistVersionOut(ORM):
    id: uuid.UUID
    checklist_id: uuid.UUID
    version_number: int
    state: ChecklistState
    disclaimer: str
    published_at: datetime | None
    created_at: datetime
    requirement_count: int = 0


class ChecklistVersionDetailOut(ChecklistVersionOut):
    checklist_name: str
    checklist_kind: ChecklistKind
    requirements: list[RequirementOut]


class ChecklistOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    kind: ChecklistKind
    created_at: datetime
    versions: list[ChecklistVersionOut] = []


class ChecklistCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    kind: ChecklistKind
    requirements: list[RequirementIn] = Field(default_factory=list, max_length=200)


class RequirementsReplaceIn(BaseModel):
    requirements: list[RequirementIn] = Field(max_length=200)


# ---------------------------------------------------------------- reviews


class ReviewCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    document_version_id: uuid.UUID
    checklist_version_id: uuid.UUID


class ReviewRunOut(ORM):
    id: uuid.UUID
    engine_version: str
    engine_mode: str
    warnings: list[str]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    job: JobOut


class ReviewOut(BaseModel):
    id: uuid.UUID
    title: str
    status: ReviewStatus
    is_demo: bool
    created_at: datetime
    signed_off_at: datetime | None
    signed_off_by_name: str | None
    document_id: uuid.UUID
    document_title: str
    document_version_id: uuid.UUID
    document_version_number: int
    checklist_id: uuid.UUID
    checklist_name: str
    checklist_version_id: uuid.UUID
    checklist_version_number: int
    checklist_kind: ChecklistKind
    finding_counts: dict[str, int] = {}
    latest_run: ReviewRunOut | None = None


class CheckResultOut(ORM):
    id: uuid.UUID
    requirement_id: uuid.UUID
    requirement_code: str
    requirement_title: str
    severity: Severity
    outcome: CheckOutcome
    needs_attention: bool
    message: str
    evidence: list[dict[str, Any]]


class ReopenIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


# ---------------------------------------------------------------- findings


class FindingOut(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    review_title: str
    review_status: ReviewStatus
    requirement_id: uuid.UUID | None
    requirement_code: str | None
    source_reference: str | None
    is_manual: bool
    title: str
    description: str
    severity: Severity
    automated_outcome: CheckOutcome | None
    evidence: list[dict[str, Any]]
    status: FindingStatus
    owner_id: uuid.UUID | None
    owner_name: str | None
    due_date: date | None
    is_overdue: bool
    decided_by_name: str | None
    decided_at: datetime | None
    decision_rationale: str
    remediation_notes: str
    created_at: datetime
    updated_at: datetime


class DecisionIn(BaseModel):
    decision: Literal["confirmed", "dismissed", "accepted_risk", "in_review"]
    rationale: str = Field(default="", max_length=5000)


class AssignmentIn(BaseModel):
    owner_id: uuid.UUID | None
    due_date: date | None = None


class RemediationIn(BaseModel):
    notes: str = Field(default="", max_length=10000)
    status: Literal["remediation_in_progress", "ready_for_rereview", "resolved"] | None = None


class ManualFindingIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    severity: Severity
    requirement_id: uuid.UUID | None = None
    block_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class BulkAssignIn(BaseModel):
    finding_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    owner_id: uuid.UUID
    due_date: date | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentOut(BaseModel):
    id: uuid.UUID
    author_name: str | None
    body: str
    created_at: datetime


# ---------------------------------------------------------------- reports, audit


class ReportOut(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    review_title: str
    version: int
    signed_off_at: datetime
    signed_off_by_name: str | None
    finding_count: int


class AuditEventOut(BaseModel):
    id: uuid.UUID
    actor_name: str | None
    action: str
    object_type: str
    object_id: uuid.UUID | None
    meta: dict[str, Any]
    created_at: datetime
