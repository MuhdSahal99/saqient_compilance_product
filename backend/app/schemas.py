from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import (
    AIAssessment,
    AISuggestionStatus,
    ChecklistKind,
    ChecklistState,
    CheckOutcome,
    DatasetKind,
    DatasetStatus,
    FindingStatus,
    JobStatus,
    MonitorCadence,
    MonitorRunStatus,
    PeriodFrequency,
    ReviewStatus,
    Role,
    RuleValueType,
    RuleVerification,
    Severity,
    SourceVerification,
    TaxAccountRole,
    TaxPeriodStatus,
    TaxType,
    VatTreatment,
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


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=256)


class InvitationIn(BaseModel):
    email: EmailStr
    role: Role


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime
    is_expired: bool
    last_sent_at: datetime | None
    last_delivery: str | None = None  # sent | failed | disabled


class InvitationLookupIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InvitationLookupOut(BaseModel):
    organization_name: str
    email: str
    role: Role
    has_account: bool
    expires_at: datetime


class InvitationAcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)


class MemberRoleIn(BaseModel):
    role: Role


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
    malware_scan_enabled: bool = False
    ocr_enabled: bool = False


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: Role
    membership_id: uuid.UUID | None = None
    joined_at: datetime | None = None


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
    is_ocr: bool = False
    ocr_confidence: int | None = None


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
    checklist_version_id: uuid.UUID
    document_version_id: uuid.UUID | None = None
    dataset_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    rule_pack_version_id: uuid.UUID | None = None
    as_of_date: date | None = None
    entity_id: uuid.UUID | None = Field(
        default=None, description="The legal entity under review (needed for VAT checks)."
    )
    tax_period_id: uuid.UUID | None = Field(
        default=None, description="Tax period of the entity; sets the period for cut-off checks."
    )
    einvoice_batch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    einvoice_file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _has_input(self) -> ReviewCreateIn:
        if (
            self.document_version_id is None
            and not self.dataset_version_ids
            and not self.einvoice_batch_ids
            and not self.einvoice_file_ids
            and self.entity_id is None
            and self.tax_period_id is None
        ):
            raise ValueError("choose a document, datasets, e-invoices or an entity")
        if len(set(self.dataset_version_ids)) != len(self.dataset_version_ids):
            raise ValueError("dataset versions must be distinct")
        return self


class ReviewDatasetOut(BaseModel):
    kind: DatasetKind
    dataset_id: uuid.UUID
    dataset_name: str
    dataset_version_id: uuid.UUID
    version_number: int
    row_count: int | None


class ReviewRunOut(ORM):
    id: uuid.UUID
    engine_version: str
    engine_mode: str
    warnings: list[str]
    inputs_snapshot: dict[str, Any] = {}
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
    document_id: uuid.UUID | None
    document_title: str | None
    document_version_id: uuid.UUID | None
    document_version_number: int | None
    datasets: list[ReviewDatasetOut] = []
    rule_pack_version_id: uuid.UUID | None = None
    rule_pack_name: str | None = None
    rule_pack_version_number: int | None = None
    as_of_date: date | None = None
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    tax_period_id: uuid.UUID | None = None
    tax_period_start: date | None = None
    tax_period_end: date | None = None
    einvoice_count: int = 0
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
    meta: dict[str, Any] = {}
    result_hash: str | None = None


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
    finding_key: str = Field(
        default="", description="Set when one requirement raised several findings."
    )
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
    ai_suggestion_id: uuid.UUID | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
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
    seq: int
    hash: str


class AuditVerificationOut(BaseModel):
    ok: bool = Field(description="True when every event in the chain matches its hash.")
    checked: int = Field(description="Events checked, oldest first, up to the first break.")
    head_seq: int | None = Field(description="Position of the last event checked.")
    head_hash: str | None = Field(
        description="Hash of the last event checked. Keep it outside the system to detect "
        "later removal of the newest events."
    )
    first_broken_seq: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------- AI suggestions


class AISuggestionRunOut(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    is_mock: bool
    prompt_version: str
    warnings: list[str]
    created_at: datetime
    finished_at: datetime | None
    job: JobOut


class AISuggestionOut(BaseModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    requirement_code: str
    requirement_title: str
    severity: Severity
    assessment: AIAssessment
    summary: str
    evidence: list[dict[str, Any]]
    rejected_citations: int
    status: AISuggestionStatus
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str
    finding_id: uuid.UUID | None


class AISuggestionsOut(BaseModel):
    available: bool
    run: AISuggestionRunOut | None
    suggestions: list[AISuggestionOut]


class AIDecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------- legal entities

_COUNTRY = r"^[A-Z]{2}$"
_CURRENCY = r"^[A-Z]{3}$"
_TRN = r"^[A-Za-z0-9]{5,20}$"


class TaxGroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(pattern=_COUNTRY, description="ISO 3166-1 alpha-2 code.")
    trn: str | None = Field(default=None, pattern=_TRN, description="Group tax number.")


class TaxGroupPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    trn: str | None = Field(default=None, pattern=_TRN)


class TaxGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    country: str
    trn_masked: str | None = Field(description="Only the last four characters are shown.")
    entity_count: int = 0
    created_at: datetime


class LegalEntityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(pattern=_COUNTRY, description="ISO 3166-1 alpha-2 code.")
    trn: str | None = Field(
        default=None, pattern=_TRN, description="TRN / VAT number. Stored encrypted."
    )
    fiscal_year_end_month: int = Field(ge=1, le=12)
    fiscal_year_end_day: int = Field(ge=1, le=31)
    functional_currency: str = Field(pattern=_CURRENCY, description="ISO 4217 code.")
    timezone: str = Field(default="Asia/Dubai", max_length=64, description="IANA time zone.")
    tax_group_id: uuid.UUID | None = None
    is_free_zone: bool = False


class LegalEntityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    trn: str | None = Field(default=None, pattern=_TRN)
    clear_trn: bool = False
    fiscal_year_end_month: int | None = Field(default=None, ge=1, le=12)
    fiscal_year_end_day: int | None = Field(default=None, ge=1, le=31)
    functional_currency: str | None = Field(default=None, pattern=_CURRENCY)
    timezone: str | None = Field(default=None, max_length=64)
    tax_group_id: uuid.UUID | None = None
    clear_tax_group: bool = False
    is_free_zone: bool | None = None
    is_active: bool | None = None
    size_basis_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=20,
        decimal_places=4,
        description="Revenue figure used to place the entity in an e-invoicing wave.",
    )
    size_basis_currency: str | None = Field(default=None, pattern=_CURRENCY)
    size_basis_year: int | None = Field(default=None, ge=2000, le=2100)
    clear_size_basis: bool = False
    einvoice_go_live_override: date | None = Field(
        default=None, description="A go-live date notified to this taxpayer directly."
    )
    einvoice_go_live_note: str | None = Field(default=None, max_length=2000)
    clear_go_live_override: bool = False


class LegalEntityOut(BaseModel):
    id: uuid.UUID
    name: str
    country: str
    trn_masked: str | None = Field(description="Only the last four characters are shown.")
    fiscal_year_end_month: int
    fiscal_year_end_day: int
    functional_currency: str
    timezone: str
    tax_group_id: uuid.UUID | None
    tax_group_name: str | None
    is_free_zone: bool
    is_active: bool
    size_basis_amount: Decimal | None = None
    size_basis_currency: str | None = None
    size_basis_year: int | None = None
    einvoice_go_live_override: date | None = None
    einvoice_go_live_note: str = ""
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- tax setup


class TaxPeriodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_type: TaxType = TaxType.VAT
    frequency: PeriodFrequency
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _order(self) -> TaxPeriodIn:
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        if (self.period_end - self.period_start).days > 400:
            raise ValueError("a tax period cannot exceed about one year")
        return self


class TaxPeriodPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TaxPeriodStatus


class TaxPeriodOut(ORM):
    id: uuid.UUID
    entity_id: uuid.UUID
    tax_type: TaxType
    frequency: PeriodFrequency
    period_start: date
    period_end: date
    status: TaxPeriodStatus
    created_at: datetime


class TaxCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    register: Literal["sales_register", "purchase_register"]
    tax_code: str = Field(min_length=1, max_length=40)
    treatment: VatTreatment
    recoverable: bool = True
    description: str = Field(default="", max_length=300)


class TaxAccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: TaxAccountRole
    account_code: str = Field(min_length=1, max_length=60)


class VatSetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_codes: list[TaxCodeIn] = Field(default_factory=list, max_length=500)
    tax_accounts: list[TaxAccountIn] = Field(default_factory=list, max_length=100)


class TaxCodeOut(ORM):
    register: DatasetKind
    tax_code: str
    treatment: VatTreatment
    recoverable: bool
    description: str


class TaxAccountOut(ORM):
    role: TaxAccountRole
    account_code: str


class VatSetupOut(BaseModel):
    entity_id: uuid.UUID
    tax_codes: list[TaxCodeOut]
    tax_accounts: list[TaxAccountOut]


# ---------------------------------------------------------------- e-invoices


class EInvoiceFileOut(ORM):
    id: uuid.UUID
    batch_id: uuid.UUID
    entity_id: uuid.UUID
    filename: str
    size_bytes: int
    sha256: str
    profile: str
    document_type: str
    invoice_number: str | None
    invoice_uuid: str | None
    issue_date: date | None
    type_code: str | None
    icv: int | None
    currency: str | None
    payable_amount: Decimal | None
    tax_amount: Decimal | None
    parse_error: str | None
    created_at: datetime


class EInvoiceBatchOut(ORM):
    id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str = ""
    name: str
    original_filename: str
    raw_sha256: str
    file_count: int
    duplicate_count: int
    failed_count: int
    is_demo: bool
    created_at: datetime


class EInvoiceBatchDetailOut(EInvoiceBatchOut):
    files: list[EInvoiceFileOut] = []


# ---------------------------------------------------------------- rule packs

_RULE_KEY = r"^[a-z0-9]+(?:[._][a-z0-9]+)*$"


class RulePackCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    jurisdiction: str = Field(
        pattern=r"^[A-Z]{2}(-[A-Z0-9]{1,10})?$|^SYNTHETIC$",
        description="ISO 3166-1 alpha-2 (optionally with a subdivision), or SYNTHETIC.",
    )
    description: str = Field(default="", max_length=4000)


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_key: str = Field(min_length=1, max_length=120, pattern=_RULE_KEY)
    title: str = Field(min_length=1, max_length=300)
    value_type: RuleValueType
    value: str = Field(
        min_length=1,
        max_length=65536,
        description="Parsed by value_type. Scalars up to 200 characters; json up to 64 KB.",
    )
    unit: str = Field(default="", max_length=40)
    effective_from: date
    effective_to: date | None = None
    source_url: str | None = Field(
        default=None, max_length=500, pattern=r"^https://", description="Official source URL."
    )
    source_note: str = Field(default="", max_length=4000)
    todo: str = Field(default="", max_length=4000, description="Open question; keeps it draft.")

    @model_validator(mode="after")
    def _scalar_length(self) -> RuleIn:
        if self.value_type is not RuleValueType.JSON and len(self.value) > 200:
            raise ValueError("scalar rule values are limited to 200 characters")
        return self


class RulesReplaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[RuleIn] = Field(max_length=500)


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rule_key: str
    title: str
    value_type: RuleValueType
    value: str
    unit: str
    effective_from: date
    effective_to: date | None
    source_url: str | None
    source_note: str
    todo: str
    verification_status: RuleVerification
    verified_by_name: str | None = None
    verified_at: datetime | None


class RulePackVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rule_pack_id: uuid.UUID
    version_number: int
    state: ChecklistState
    published_at: datetime | None
    created_at: datetime
    rule_count: int = 0
    unverified_count: int = 0


class RulePackFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    file_key: str
    kind: str
    title: str
    filename: str
    entry_point: str
    size_bytes: int
    sha256: str
    source_url: str | None
    source_note: str
    verification_status: RuleVerification
    verified_at: datetime | None
    created_at: datetime


class RulePackVersionDetailOut(RulePackVersionOut):
    pack_name: str
    jurisdiction: str
    is_synthetic: bool
    rules: list[RuleOut]
    files: list[RulePackFileOut] = []


class RulePackOut(BaseModel):
    id: uuid.UUID
    name: str
    jurisdiction: str
    description: str
    is_synthetic: bool
    created_at: datetime
    versions: list[RulePackVersionOut]


# ---------------------------------------------------------------- datasets


class DatasetVersionOut(ORM):
    id: uuid.UUID
    version_number: int
    original_filename: str
    file_format: str
    size_bytes: int
    raw_sha256: str
    status: DatasetStatus
    failure_message: str | None
    source_columns: list[str]
    source_row_count: int | None
    column_mapping: dict[str, str] = Field(
        description="Proposed from header names until confirmed (mapping_confirmed_at set)."
    )
    parse_options: dict[str, str]
    mapping_confirmed_at: datetime | None
    parquet_sha256: str | None
    row_count: int | None
    derived_fields: list[str]
    totals: dict[str, str] = Field(description="Column sums as exact decimal strings.")
    errors: list[dict[str, Any]] = Field(description="First rejected values, by row id.")
    error_count: int
    created_at: datetime
    processed_at: datetime | None


class DatasetVersionDetailOut(DatasetVersionOut):
    dataset_id: uuid.UUID
    kind: DatasetKind
    preview: list[dict[str, Any]] = Field(description="First rows of the raw file, as text.")
    latest_job: JobOut | None = None


class DatasetOut(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str
    kind: DatasetKind
    name: str
    period_start: date | None
    period_end: date | None
    is_demo: bool
    created_at: datetime
    latest_version: DatasetVersionOut | None


class DatasetDetailOut(DatasetOut):
    versions: list[DatasetVersionOut]


class MappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, str] = Field(description="Canonical field -> source column header.")
    date_format: Literal["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"] = (
        "%Y-%m-%d"
    )
    decimal_separator: Literal[".", ","] = "."


class CanonicalFieldOut(BaseModel):
    name: str
    type: str
    required: bool


class DatasetKindOut(BaseModel):
    kind: DatasetKind
    fields: list[CanonicalFieldOut]
    require_any: list[list[str]]


class DatasetRowsOut(BaseModel):
    version_id: uuid.UUID
    columns: list[str]
    rows: list[dict[str, Any]] = Field(description="Amounts and dates as strings.")
    total: int


# ---------------------------------------------------------------- e-invoice monitors


class EInvoiceMonitorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    checklist_version_id: uuid.UUID
    rule_pack_version_id: uuid.UUID | None = None
    sample_size: int = Field(ge=1, le=500, description="Invoices validated per run.")
    cadence: MonitorCadence
    first_run_at: datetime | None = Field(
        default=None, description="Defaults to one cadence step from now."
    )


class EInvoiceMonitorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sample_size: int | None = Field(default=None, ge=1, le=500)
    is_active: bool | None = None


class EInvoiceMonitorOut(ORM):
    id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str = ""
    name: str
    checklist_version_id: uuid.UUID
    rule_pack_version_id: uuid.UUID | None
    sample_size: int
    cadence: MonitorCadence
    seed: str
    is_active: bool
    next_run_at: datetime
    last_run_at: datetime | None
    covered_until: datetime | None
    created_at: datetime


class EInvoiceMonitorRunOut(ORM):
    id: uuid.UUID
    monitor_id: uuid.UUID
    review_id: uuid.UUID | None
    window_start: datetime | None
    window_end: datetime
    population: int
    sampled: int
    seed: str
    sample_method: str
    status: MonitorRunStatus
    message: str
    created_at: datetime
