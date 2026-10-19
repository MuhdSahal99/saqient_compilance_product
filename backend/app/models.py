"""ORM models. Every tenant-owned table carries a non-null ``org_id``."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
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
    # Audit client contact: reaches only the request portal (/api/portal/*).
    CLIENT = "client"


class VersionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChecklistKind(str, enum.Enum):
    SYNTHETIC_DEMO = "synthetic_demo"
    INTERNAL_POLICY = "internal_policy"
    EXTERNAL_REGULATORY = "external_regulatory"
    AUDIT_PROGRAMME = "audit_programme"


class ChecklistState(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SourceVerification(str, enum.Enum):
    SYNTHETIC = "synthetic"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class RuleVerification(str, enum.Enum):
    DRAFT = "draft"
    VERIFIED = "verified"


class RuleValueType(str, enum.Enum):
    DECIMAL = "decimal"
    INTEGER = "integer"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    # Structured parameters (lists, tables). Shape checked per rule-key family
    # (services/rule_schemas.py); size capped.
    JSON = "json"


class DatasetKind(str, enum.Enum):
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    SALES_REGISTER = "sales_register"
    PURCHASE_REGISTER = "purchase_register"
    BANK_STATEMENT = "bank_statement"
    CUSTOMER_MASTER = "customer_master"
    SUPPLIER_MASTER = "supplier_master"
    VAT_RETURN = "vat_return"
    EINVOICE_REJECTIONS = "einvoice_rejections"
    WHT_PAYMENTS = "wht_payments"
    USER_ROLES = "user_roles"
    AP_PAYMENTS = "ap_payments"
    EMPLOYEE_MASTER = "employee_master"
    THREE_WAY_MATCH = "three_way_match"
    EXPENSE_CLAIMS = "expense_claims"
    FIXED_ASSETS = "fixed_assets"


class TaxType(str, enum.Enum):
    VAT = "vat"
    CORPORATE_TAX = "corporate_tax"
    ZAKAT = "zakat"
    WHT = "wht"


class WorkpaperKind(str, enum.Enum):
    CORPORATE_TAX = "corporate_tax"
    SBR_TEST = "sbr_test"
    QFZP_TEST = "qfzp_test"
    PILLAR_TWO = "pillar_two"
    ZAKAT = "zakat"
    # Audit workpapers (Phase D) belong to an engagement.
    LEAD_SCHEDULE = "lead_schedule"
    MATERIALITY = "materiality"
    FS_DRAFT = "fs_draft"
    # Entity workpapers (Phase F3).
    LEASE_IFRS16 = "lease_ifrs16"


AUDIT_WORKPAPER_KINDS = frozenset(
    {WorkpaperKind.LEAD_SCHEDULE, WorkpaperKind.MATERIALITY, WorkpaperKind.FS_DRAFT}
)


class WorkpaperStatus(str, enum.Enum):
    DRAFT = "draft"
    SIGNED_OFF = "signed_off"


class LineSource(str, enum.Enum):
    MANUAL = "manual"
    COMPUTED = "computed"


class RelatedPartyRelation(str, enum.Enum):
    PARENT = "parent"
    SUBSIDIARY = "subsidiary"
    SISTER = "sister"
    PERMANENT_ESTABLISHMENT = "permanent_establishment"
    CONNECTED_PERSON = "connected_person"
    OTHER = "other"


class RPTransactionType(str, enum.Enum):
    GOODS = "goods"
    SERVICES = "services"
    ROYALTIES = "royalties"
    FINANCING = "financing"
    GUARANTEE = "guarantee"
    COST_SHARING = "cost_sharing"
    ASSET_TRANSFER = "asset_transfer"
    OTHER = "other"


class TPMethod(str, enum.Enum):
    CUP = "cup"
    RESALE_PRICE = "resale_price"
    COST_PLUS = "cost_plus"
    TNMM = "tnmm"
    PROFIT_SPLIT = "profit_split"
    OTHER = "other"
    NOT_SET = "not_set"


class LossEntryKind(str, enum.Enum):
    INCURRED = "incurred"
    USED = "used"
    TRANSFERRED_IN = "transferred_in"
    TRANSFERRED_OUT = "transferred_out"
    FORFEITED = "forfeited"


class EngagementKind(str, enum.Enum):
    EXTERNAL_AUDIT = "external_audit"
    INTERNAL_AUDIT = "internal_audit"


class EngagementPhase(str, enum.Enum):
    PLANNING = "planning"
    FIELDWORK = "fieldwork"
    COMPLETION = "completion"
    REPORTING = "reporting"


class EngagementStatus(str, enum.Enum):
    """The current phase, or closed. Moves forward one step; a step back needs a reason."""

    PLANNING = "planning"
    FIELDWORK = "fieldwork"
    COMPLETION = "completion"
    REPORTING = "reporting"
    CLOSED = "closed"


class FsSection(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class Assertion(str, enum.Enum):
    EXISTENCE = "existence"
    OCCURRENCE = "occurrence"
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    VALUATION = "valuation"
    CUT_OFF = "cut_off"
    CLASSIFICATION = "classification"
    RIGHTS_OBLIGATIONS = "rights_obligations"
    PRESENTATION = "presentation"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProcedureStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class SamplingMethod(str, enum.Enum):
    MONETARY_UNIT = "monetary_unit"
    RANDOM = "random"
    STRATIFIED = "stratified"


class SampleItemResult(str, enum.Enum):
    NOT_TESTED = "not_tested"
    NO_EXCEPTION = "no_exception"
    EXCEPTION = "exception"


class ConfirmationType(str, enum.Enum):
    BANK = "bank"
    RECEIVABLE = "receivable"
    PAYABLE = "payable"
    LEGAL = "legal"
    OTHER = "other"


class ConfirmationStatus(str, enum.Enum):
    PLANNED = "planned"
    SENT = "sent"
    RESPONDED = "responded"
    NO_RESPONSE = "no_response"
    CLOSED = "closed"


class AdjustmentStatus(str, enum.Enum):
    PROPOSED = "proposed"
    RECORDED = "recorded"  # booked by the client
    PASSED = "passed"  # not booked; on the summary of unadjusted differences


class PbcStatus(str, enum.Enum):
    REQUESTED = "requested"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EngagementRole(str, enum.Enum):
    PARTNER = "partner"
    MANAGER = "manager"
    SENIOR = "senior"
    STAFF = "staff"


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskSource(str, enum.Enum):
    TAX_OBLIGATION = "tax_obligation"
    MANUAL = "manual"
    CLOSE_CHECKLIST = "close_checklist"
    CONTROL_REMEDIATION = "control_remediation"


class MonitorCadence(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class MonitorRunStatus(str, enum.Enum):
    REVIEW_CREATED = "review_created"
    NO_FILES = "no_files"
    FAILED = "failed"


class PeriodFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    CUSTOM = "custom"


class TaxPeriodStatus(str, enum.Enum):
    OPEN = "open"
    FILED = "filed"


class VatTreatment(str, enum.Enum):
    """Generic VAT treatments an ERP tax code maps to. Box membership comes from rule packs."""

    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    ZERO_RATED_EXPORT = "zero_rated_export"
    EXEMPT = "exempt"
    OUT_OF_SCOPE = "out_of_scope"
    REVERSE_CHARGE = "reverse_charge"
    IMPORT = "import"


class TaxAccountRole(str, enum.Enum):
    OUTPUT_VAT = "output_vat"
    INPUT_VAT = "input_vat"
    REVERSE_CHARGE_OUTPUT = "reverse_charge_output"
    REVERSE_CHARGE_INPUT = "reverse_charge_input"


class DatasetStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    NEEDS_MAPPING = "needs_mapping"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


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
    # Data checks (engine deterministic-1.1.0).
    EXCEPTIONS_FOUND = "exceptions_found"
    NO_EXCEPTIONS = "no_exceptions"


class JobKind(str, enum.Enum):
    EXTRACT = "extract"
    REVIEW_RUN = "review_run"
    AI_SUGGEST = "ai_suggest"
    DATASET_PARSE = "dataset_parse"
    DATASET_BUILD = "dataset_build"
    CONNECTOR_SYNC = "connector_sync"


class AIAssessment(str, enum.Enum):
    """What the model said about one requirement. Never a reviewer decision."""

    ADDRESSED = "addressed"
    NOT_ADDRESSED = "not_addressed"
    UNCLEAR = "unclear"
    INVALID_OUTPUT = "invalid_output"


class AISuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


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
    # Phase F4: an org admin's explicit opt-in before any document text goes to a model.
    ai_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    ai_opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class Invitation(Base):
    """An emailed, single-use invitation to join an organisation with a role."""

    __tablename__ = "invitations"
    __table_args__ = (
        # One open invitation per email per organisation.
        Index(
            "uq_invitations_org_email_open",
            "org_id",
            "email",
            unique=True,
            postgresql_where="accepted_at IS NULL AND revoked_at IS NULL",
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(_enum(Role, "invitation_role"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(lazy="joined")
    invited_by: Mapped[User | None] = relationship(foreign_keys=[invited_by_id], lazy="joined")


class PasswordResetToken(Base):
    """Single-use, short-lived. Account-level (not tenant data), like users."""

    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationKind(str, enum.Enum):
    INVITATION = "invitation"
    TASK_DUE_REMINDER = "task_due_reminder"


class NotificationStatus(str, enum.Enum):
    SENT = "sent"
    FAILED = "failed"
    DISABLED = "disabled"


class NotificationLog(Base):
    """Outgoing org notifications. Bodies are not stored (they can hold links)."""

    __tablename__ = "notification_log"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    kind: Mapped[NotificationKind] = mapped_column(_enum(NotificationKind, "notification_kind"))
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    recipient_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Reminders: one per finding, due date and day, so retries cannot send twice.
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus, "notification_status")
    )
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- entities


class TaxGroup(Base):
    """A VAT/tax group that several legal entities of one organisation belong to."""

    __tablename__ = "tax_groups"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))
    # Encrypted (app/crypto.py); only the last four characters are kept in clear.
    trn_encrypted: Mapped[str | None] = mapped_column(Text)
    trn_last4: Mapped[str | None] = mapped_column(String(4))
    created_at: Mapped[datetime] = _created()


class LegalEntity(Base):
    __tablename__ = "legal_entities"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    trn_encrypted: Mapped[str | None] = mapped_column(Text)
    trn_last4: Mapped[str | None] = mapped_column(String(4))
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer)
    fiscal_year_end_day: Mapped[int] = mapped_column(Integer)
    functional_currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    timezone: Mapped[str] = mapped_column(String(64))  # IANA, e.g. Asia/Dubai
    tax_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_groups.id", ondelete="RESTRICT"), index=True
    )
    is_free_zone: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # E-invoicing go-live banding: a user-entered revenue figure and its basis year.
    size_basis_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    size_basis_currency: Mapped[str | None] = mapped_column(String(3))
    size_basis_year: Mapped[int | None] = mapped_column(Integer)
    # A go-live date notified to this taxpayer directly, overriding the pack's waves.
    einvoice_go_live_override: Mapped[date | None] = mapped_column(Date)
    einvoice_go_live_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tax_group: Mapped[TaxGroup | None] = relationship(lazy="joined")


class TaxPeriod(Base):
    """An explicit tax period of one entity (VAT now; corporate tax, zakat, WHT later)."""

    __tablename__ = "tax_periods"
    __table_args__ = (UniqueConstraint("entity_id", "tax_type", "period_start"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    tax_type: Mapped[TaxType] = mapped_column(_enum(TaxType, "tax_type"))
    frequency: Mapped[PeriodFrequency] = mapped_column(_enum(PeriodFrequency, "period_frequency"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[TaxPeriodStatus] = mapped_column(
        _enum(TaxPeriodStatus, "tax_period_status"), default=TaxPeriodStatus.OPEN
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")


class EntityTaxCode(Base):
    """How one ERP tax code of an entity is treated for VAT (client configuration)."""

    __tablename__ = "entity_tax_codes"
    __table_args__ = (UniqueConstraint("entity_id", "register", "tax_code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    register: Mapped[DatasetKind] = mapped_column(_enum(DatasetKind, "tax_code_register"))
    tax_code: Mapped[str] = mapped_column(String(40))
    treatment: Mapped[VatTreatment] = mapped_column(_enum(VatTreatment, "vat_treatment"))
    # Purchases: whether input VAT on this code is claimed as recoverable.
    recoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(300), default="")


class EntityTaxAccount(Base):
    """A GL account that holds VAT for an entity, by role."""

    __tablename__ = "entity_tax_accounts"
    __table_args__ = (UniqueConstraint("entity_id", "role", "account_code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[TaxAccountRole] = mapped_column(_enum(TaxAccountRole, "tax_account_role"))
    account_code: Mapped[str] = mapped_column(String(60))


# ---------------------------------------------------------------- rule packs


class RulePack(Base):
    """Versioned tax/regulatory parameters, held as data rather than code."""

    __tablename__ = "rule_packs"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200))
    jurisdiction: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()

    versions: Mapped[list[RulePackVersion]] = relationship(
        back_populates="rule_pack", order_by="RulePackVersion.version_number"
    )


class RulePackVersion(Base):
    __tablename__ = "rule_pack_versions"
    __table_args__ = (UniqueConstraint("rule_pack_id", "version_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rule_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_packs.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[ChecklistState] = mapped_column(
        _enum(ChecklistState, "rule_pack_state"), default=ChecklistState.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    rule_pack: Mapped[RulePack] = relationship(back_populates="versions", lazy="joined")
    rules: Mapped[list[Rule]] = relationship(
        back_populates="version", order_by="[Rule.rule_key, Rule.effective_from]"
    )
    files: Mapped[list[RulePackFile]] = relationship(
        back_populates="version", order_by="RulePackFile.file_key"
    )


class Rule(Base):
    """One parameter, valid for a date range. Values are strings parsed by type (no floats)."""

    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("rule_pack_version_id", "rule_key", "effective_from"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="CASCADE"), index=True
    )
    rule_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    value_type: Mapped[RuleValueType] = mapped_column(_enum(RuleValueType, "rule_value_type"))
    value: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(40), default="")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_note: Mapped[str] = mapped_column(Text, default="")
    # Open questions about the rule; a rule with a TODO stays draft.
    todo: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[RuleVerification] = mapped_column(
        _enum(RuleVerification, "rule_verification"), default=RuleVerification.DRAFT
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    version: Mapped[RulePackVersion] = relationship(back_populates="rules")
    verified_by: Mapped[User | None] = relationship(lazy="joined")


class RulePackFile(Base):
    """A file a rule pack version relies on (e.g. an XSD bundle), hashed and immutable.

    Like a rule, a file is draft until an org admin verifies it against its source.
    Files are copied by reference (same storage key) into new draft versions.
    """

    __tablename__ = "rule_pack_files"
    __table_args__ = (UniqueConstraint("rule_pack_version_id", "file_key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="CASCADE"), index=True
    )
    file_key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))  # "xsd_bundle"
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(255))
    entry_point: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_note: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[RuleVerification] = mapped_column(
        _enum(RuleVerification, "rule_file_verification"), default=RuleVerification.DRAFT
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    version: Mapped[RulePackVersion] = relationship(back_populates="files")


# ---------------------------------------------------------------- datasets


class Dataset(Base):
    """A logical finance dataset (e.g. FY2025 general ledger) for one legal entity."""

    __tablename__ = "datasets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[DatasetKind] = mapped_column(_enum(DatasetKind, "dataset_kind"))
    name: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", order_by="DatasetVersion.version_number"
    )


class DatasetVersion(Base):
    """One imported file: raw bytes hashed and stored, canonical Parquet once mapped."""

    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    raw_sha256: Mapped[str] = mapped_column(String(64), index=True)
    raw_storage_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[DatasetStatus] = mapped_column(
        _enum(DatasetStatus, "dataset_status"), default=DatasetStatus.PENDING
    )
    failure_message: Mapped[str | None] = mapped_column(Text)
    source_columns: Mapped[list[str]] = mapped_column(JSONType, default=list)
    source_row_count: Mapped[int | None] = mapped_column(Integer)
    # Proposed (by header names) until confirmed by a user.
    column_mapping: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    parse_options: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    mapping_confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    mapping_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parquet_storage_key: Mapped[str | None] = mapped_column(String(200))
    parquet_sha256: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int | None] = mapped_column(Integer)
    derived_fields: Mapped[list[str]] = mapped_column(JSONType, default=list)
    totals: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[Dataset] = relationship(back_populates="versions", lazy="joined")


# ---------------------------------------------------------------- e-invoices


class EInvoiceBatch(Base):
    """A set of e-invoice XML files uploaded together for one entity."""

    __tablename__ = "einvoice_batches"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(255))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")


class EInvoiceFile(Base):
    """One stored e-invoice XML. Header fields are read for listing and matching only."""

    __tablename__ = "einvoice_files"
    __table_args__ = (UniqueConstraint("entity_id", "sha256"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("einvoice_batches.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    # Detected from the document (pint_ae | zatca | unknown); a label, not a validation result.
    profile: Mapped[str] = mapped_column(String(20), default="unknown")
    document_type: Mapped[str] = mapped_column(String(20), default="")  # Invoice | CreditNote
    invoice_number: Mapped[str | None] = mapped_column(String(200), index=True)
    invoice_uuid: Mapped[str | None] = mapped_column(String(100), index=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    type_code: Mapped[str | None] = mapped_column(String(20))
    icv: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    payable_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    parse_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ReviewEInvoice(Base):
    """An e-invoice file a review validates."""

    __tablename__ = "review_einvoices"
    __table_args__ = (UniqueConstraint("review_id", "file_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("einvoice_files.id", ondelete="RESTRICT"), index=True
    )

    file: Mapped[EInvoiceFile] = relationship(lazy="joined")


class EInvoiceMonitor(Base):
    """A schedule that validates a reproducible sample of an entity's new e-invoices."""

    __tablename__ = "einvoice_monitors"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_versions.id", ondelete="RESTRICT")
    )
    rule_pack_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    sample_size: Mapped[int] = mapped_column(Integer)
    cadence: Mapped[MonitorCadence] = mapped_column(_enum(MonitorCadence, "monitor_cadence"))
    # Random per monitor; recorded with each run so the sample can be re-drawn.
    seed: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Files uploaded up to this time have been offered to a sample.
    covered_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    checklist_version: Mapped[ChecklistVersion] = relationship(lazy="joined")


class EInvoiceMonitorRun(Base):
    """One monitor run: the window, the population, the sample drawn and its review."""

    __tablename__ = "einvoice_monitor_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("einvoice_monitors.id", ondelete="CASCADE"), index=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL")
    )
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    population: Mapped[int] = mapped_column(Integer, default=0)
    sampled: Mapped[int] = mapped_column(Integer, default=0)
    seed: Mapped[str] = mapped_column(String(64))
    sample_method: Mapped[str] = mapped_column(String(300))
    status: Mapped[MonitorRunStatus] = mapped_column(_enum(MonitorRunStatus, "monitor_run_status"))
    message: Mapped[str] = mapped_column(String(500), default="")
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Task(Base):
    """A to-do with an owner and due date that is not a finding (ADR 0009).

    ``source_kind`` + ``source_id`` say what created it (a tax obligation now; PBC
    requests and close checklist items later).
    """

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_org_owner_status", "org_id", "owner_id", "status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    source_kind: Mapped[TaskSource] = mapped_column(_enum(TaskSource, "task_source"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), default=TaskStatus.OPEN
    )
    completion_note: Mapped[str] = mapped_column(Text, default="")
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity | None] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="joined")


class TaxObligation(Base):
    """A filing or e-invoicing deadline of one entity, generated from a rule pack."""

    __tablename__ = "tax_obligations"
    __table_args__ = (UniqueConstraint("entity_id", "obligation_key", "period_start"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    tax_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_periods.id", ondelete="SET NULL")
    )
    # The obligation id from the pack (e.g. vat_return) or einvoicing:<milestone>.
    obligation_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(300))
    tax_type: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    # How the due date was derived, with the rule used, so a reviewer can reproduce it.
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rule_key: Mapped[str] = mapped_column(String(120))
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    formula: Mapped[str] = mapped_column(String(300))
    rule_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    task: Mapped[Task | None] = relationship(lazy="joined")


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
    # Read from a page image by OCR; recognition can be wrong.
    is_ocr: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ocr_confidence: Mapped[int | None] = mapped_column(Integer)  # mean word confidence 0-100


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
    # A review needs a document, datasets (review_datasets), or both; the service checks.
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_versions.id", ondelete="RESTRICT")
    )
    rule_pack_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    # Date rule values are resolved for; defaults to the datasets' period end.
    as_of_date: Mapped[date | None] = mapped_column(Date)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    tax_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_periods.id", ondelete="RESTRICT"), index=True
    )
    # An audit programme or journal entry review run for an engagement (Phase D).
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="RESTRICT"), index=True
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

    document_version: Mapped[DocumentVersion | None] = relationship(lazy="joined")
    checklist_version: Mapped[ChecklistVersion] = relationship(lazy="joined")
    entity: Mapped[LegalEntity | None] = relationship(lazy="joined")
    tax_period: Mapped[TaxPeriod | None] = relationship(lazy="joined")
    runs: Mapped[list[ReviewRun]] = relationship(
        back_populates="review", order_by="ReviewRun.created_at"
    )
    datasets: Mapped[list[ReviewDataset]] = relationship(
        back_populates="review", order_by="ReviewDataset.kind", cascade="all, delete-orphan"
    )


class ReviewDataset(Base):
    """One dataset version per kind used as a review input."""

    __tablename__ = "review_datasets"
    __table_args__ = (UniqueConstraint("review_id", "kind"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[DatasetKind] = mapped_column(_enum(DatasetKind, "review_dataset_kind"))
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )

    review: Mapped[Review] = relationship(back_populates="datasets")
    dataset_version: Mapped[DatasetVersion] = relationship(lazy="joined")


class ReviewRun(Base):
    __tablename__ = "review_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    engine_version: Mapped[str] = mapped_column(String(40))
    engine_mode: Mapped[str] = mapped_column(String(40), default="deterministic")
    config_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # Dataset versions (with parquet hashes), rule pack version and as-of date used.
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
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
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # SHA-256 of the canonical result (outcome, message, evidence, meta): equal inputs,
    # equal hash. Null for results written before engine 1.1.0.
    result_hash: Mapped[str | None] = mapped_column(String(64))

    run: Mapped[ReviewRun] = relationship(back_populates="results")
    requirement: Mapped[Requirement] = relationship(lazy="joined")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        # One automated finding per requirement (and finding key) per review: retries
        # cannot duplicate. A check may raise several findings, one per key.
        Index(
            "uq_findings_review_requirement",
            "review_id",
            "requirement_id",
            "finding_key",
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
    # "" for one finding per requirement; otherwise e.g. the failed invoice rule id.
    finding_key: Mapped[str] = mapped_column(String(200), default="", server_default="")
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
    # Set when a reviewer accepted an AI suggestion; the finding is still a human decision.
    ai_suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_suggestions.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    review: Mapped[Review] = relationship(lazy="joined")
    requirement: Mapped[Requirement | None] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")
    ai_suggestion: Mapped[AISuggestion | None] = relationship(foreign_keys=[ai_suggestion_id])


class AISuggestionRun(Base):
    """One request to the AI provider for a review: which model, when, and how it went."""

    __tablename__ = "ai_suggestion_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(200), default="")
    prompt_version: Mapped[str] = mapped_column(String(40))
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    checklist_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(lazy="joined")


class AISuggestion(Base):
    """A model's suggestion about one requirement. Only a reviewer can turn it into a finding."""

    __tablename__ = "ai_suggestions"
    __table_args__ = (UniqueConstraint("run_id", "requirement_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_suggestion_runs.id", ondelete="CASCADE"), index=True
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    assessment: Mapped[AIAssessment] = mapped_column(_enum(AIAssessment, "ai_assessment"))
    summary: Mapped[str] = mapped_column(Text, default="")
    # Only citations that passed validation against stored block text.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    rejected_citations: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[AISuggestionStatus] = mapped_column(
        _enum(AISuggestionStatus, "ai_suggestion_status"), default=AISuggestionStatus.PENDING
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    run: Mapped[AISuggestionRun] = relationship(lazy="joined")
    requirement: Mapped[Requirement] = relationship(lazy="joined")
    decided_by: Mapped[User | None] = relationship(lazy="joined")


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


class TaxWorkpaper(Base):
    """A direct-tax workpaper: input lines a preparer enters, lines a formula computes."""

    __tablename__ = "tax_workpapers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[WorkpaperKind] = mapped_column(_enum(WorkpaperKind, "workpaper_kind"))
    title: Mapped[str] = mapped_column(String(300))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    # Rule keys hang off this prefix, e.g. 'ae.ct'.
    rules_prefix: Mapped[str] = mapped_column(String(80))
    # Audit workpapers: the engagement, and the preparer step before reviewer sign-off.
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="RESTRICT"), index=True
    )
    prepared_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prepared_by: Mapped[User | None] = relationship(foreign_keys=[prepared_by_id], lazy="joined")
    status: Mapped[WorkpaperStatus] = mapped_column(
        _enum(WorkpaperStatus, "workpaper_status"), default=WorkpaperStatus.DRAFT
    )
    calc_version: Mapped[str | None] = mapped_column(String(40))
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SHA-256 of inputs, rule snapshots and outputs of the latest computation.
    result_hash: Mapped[str | None] = mapped_column(String(64))
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    lines: Mapped[list[WorkpaperLine]] = relationship(
        back_populates="workpaper", order_by="WorkpaperLine.ordinal", cascade="all, delete-orphan"
    )


class WorkpaperLine(Base):
    __tablename__ = "workpaper_lines"
    __table_args__ = (UniqueConstraint("workpaper_id", "line_key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    workpaper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_workpapers.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[LineSource] = mapped_column(_enum(LineSource, "workpaper_line_source"))
    section: Mapped[str] = mapped_column(String(40))
    # Input lines: the formula's input name (e.g. 'accounting_profit'), unique per paper.
    line_key: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(60), default="")
    label: Mapped[str] = mapped_column(String(300))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    value: Mapped[str | None] = mapped_column(String(200))  # non-amount inputs (flags, dates)
    formula_id: Mapped[str | None] = mapped_column(String(80))
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    rule_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # References to stored evidence: document source blocks or dataset rows.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    workpaper: Mapped[TaxWorkpaper] = relationship(back_populates="lines")


class WorkpaperSnapshot(Base):
    """Immutable workpaper content frozen at reviewer sign-off (like report snapshots)."""

    __tablename__ = "workpaper_snapshots"
    __table_args__ = (UniqueConstraint("workpaper_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    workpaper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_workpapers.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_off_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class TaxLossEntry(Base):
    """One movement in an entity's tax loss register (amounts are always positive)."""

    __tablename__ = "tax_loss_entries"
    __table_args__ = (
        # A signed-off workpaper feeds the register at most once per movement kind.
        UniqueConstraint("workpaper_id", "kind"),
        Index("ix_tax_loss_entries_entity_period", "entity_id", "period_end"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT")
    )
    kind: Mapped[LossEntryKind] = mapped_column(_enum(LossEntryKind, "loss_entry_kind"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    workpaper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_workpapers.id", ondelete="RESTRICT"), index=True
    )
    counterparty_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT")
    )
    # Pairs the two sides of a transfer.
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    rule_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(foreign_keys=[entity_id], lazy="joined")
    counterparty: Mapped[LegalEntity | None] = relationship(
        foreign_keys=[counterparty_entity_id], lazy="joined"
    )


class TaxGroupMembership(Base):
    """Dated membership of an entity in a tax group, with the parent's ownership share."""

    __tablename__ = "tax_group_memberships"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    tax_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_groups.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Share held by the parent (0..1); the parent itself records 1.
    ownership_share: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    joined_on: Mapped[date] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(Date)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")


class RelatedParty(Base):
    """A related party or connected person of one entity (transfer pricing register)."""

    __tablename__ = "related_parties"
    __table_args__ = (UniqueConstraint("entity_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    relation: Mapped[RelatedPartyRelation] = mapped_column(
        _enum(RelatedPartyRelation, "related_party_relation")
    )
    jurisdiction: Mapped[str] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    note: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class RelatedPartyTransaction(Base):
    """One controlled transaction (or an annual total of one type) with a related party."""

    __tablename__ = "related_party_transactions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    related_party_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("related_parties.id", ondelete="RESTRICT"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    transaction_type: Mapped[RPTransactionType] = mapped_column(
        _enum(RPTransactionType, "rp_transaction_type")
    )
    direction: Mapped[str] = mapped_column(String(10))  # receipt | payment
    description: Mapped[str] = mapped_column(String(500), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[TPMethod] = mapped_column(_enum(TPMethod, "tp_method"), default=TPMethod.NOT_SET)
    # Optional arm's length range from a benchmarking study and the tested result.
    range_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    range_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tested_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    range_metric: Mapped[str] = mapped_column(String(80), default="")
    benchmark_document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    party: Mapped[RelatedParty] = relationship(lazy="joined")


# ---------------------------------------------------------------- audit engagements


class AuditEngagement(Base):
    """An external or internal audit of one entity and period (Phase D)."""

    __tablename__ = "audit_engagements"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[EngagementKind] = mapped_column(_enum(EngagementKind, "engagement_kind"))
    name: Mapped[str] = mapped_column(String(300))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[EngagementStatus] = mapped_column(
        _enum(EngagementStatus, "engagement_status"), default=EngagementStatus.PLANNING
    )
    # Trial balances for lead schedules (D2) and the audit rule pack (thresholds, rounding).
    cy_tb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="SET NULL")
    )
    py_tb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="SET NULL")
    )
    rule_pack_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rules_prefix: Mapped[str | None] = mapped_column(String(80))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    members: Mapped[list[EngagementMember]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan"
    )
    budgets: Mapped[list[EngagementBudget]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan"
    )


class EngagementMember(Base):
    __tablename__ = "engagement_members"
    __table_args__ = (UniqueConstraint("engagement_id", "user_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[EngagementRole] = mapped_column(_enum(EngagementRole, "engagement_role"))
    created_at: Mapped[datetime] = _created()

    engagement: Mapped[AuditEngagement] = relationship(back_populates="members")
    user: Mapped[User] = relationship(lazy="joined")


class EngagementBudget(Base):
    """Budgeted hours for one phase of an engagement."""

    __tablename__ = "engagement_budgets"
    __table_args__ = (UniqueConstraint("engagement_id", "phase"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[EngagementPhase] = mapped_column(_enum(EngagementPhase, "engagement_phase"))
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    engagement: Mapped[AuditEngagement] = relationship(back_populates="budgets")


class LeadSchedule(Base):
    """A financial statement lead schedule (e.g. 'A Cash and bank') of an engagement."""

    __tablename__ = "lead_schedules"
    __table_args__ = (UniqueConstraint("engagement_id", "code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))  # stored upper case
    name: Mapped[str] = mapped_column(String(200))
    section: Mapped[FsSection] = mapped_column(_enum(FsSection, "fs_section"))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class AccountMapping(Base):
    """Trial balance account → lead schedule, for one engagement."""

    __tablename__ = "account_mappings"
    __table_args__ = (UniqueConstraint("engagement_id", "account_code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    account_code: Mapped[str] = mapped_column(String(80))
    lead_schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_schedules.id", ondelete="RESTRICT"), index=True
    )


class AuditRisk(Base):
    """A risk of material misstatement for a financial statement area and assertions."""

    __tablename__ = "audit_risks"
    __table_args__ = (UniqueConstraint("engagement_id", "ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(20))  # e.g. R1
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    lead_code: Mapped[str | None] = mapped_column(String(20))  # FS area, if mapped
    assertions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    inherent_risk: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel, "risk_level"))
    significant: Mapped[bool] = mapped_column(Boolean, default=False)
    fraud: Mapped[bool] = mapped_column(Boolean, default=False)
    response: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class AuditProcedure(Base):
    """A planned audit procedure, optionally from an audit programme requirement."""

    __tablename__ = "audit_procedures"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT"), index=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL")
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[ProcedureStatus] = mapped_column(
        _enum(ProcedureStatus, "procedure_status"), default=ProcedureStatus.NOT_STARTED
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    requirement: Mapped[Requirement | None] = relationship(lazy="joined")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")


class RiskProcedure(Base):
    __tablename__ = "risk_procedures"
    __table_args__ = (UniqueConstraint("risk_id", "procedure_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    risk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_risks.id", ondelete="CASCADE"), index=True
    )
    procedure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_procedures.id", ondelete="CASCADE"), index=True
    )


class AuditSample(Base):
    """A reproducible sample of dataset rows: method, seed and population hash recorded."""

    __tablename__ = "audit_samples"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    method: Mapped[SamplingMethod] = mapped_column(_enum(SamplingMethod, "sampling_method"))
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    amount_column: Mapped[str] = mapped_column(String(60))
    seed: Mapped[str] = mapped_column(String(64))
    # Method parameters as entered: size, strata (upper, size), and for MUS interval/start.
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(40))
    population_count: Mapped[int] = mapped_column(Integer)
    population_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    population_sha256: Mapped[str] = mapped_column(String(64))
    risk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_risks.id", ondelete="SET NULL")
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    items: Mapped[list[AuditSampleItem]] = relationship(
        back_populates="sample", order_by="AuditSampleItem.row_id", cascade="all, delete-orphan"
    )


class AuditSampleItem(Base):
    __tablename__ = "audit_sample_items"
    __table_args__ = (UniqueConstraint("sample_id", "row_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    sample_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_samples.id", ondelete="CASCADE"), index=True
    )
    row_id: Mapped[int] = mapped_column(Integer)
    stratum: Mapped[int | None] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer, default=1)
    book_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))  # absolute value sampled
    audited_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    result: Mapped[SampleItemResult] = mapped_column(
        _enum(SampleItemResult, "sample_item_result"), default=SampleItemResult.NOT_TESTED
    )
    note: Mapped[str] = mapped_column(String(1000), default="")
    tested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sample: Mapped[AuditSample] = relationship(back_populates="items")


class AuditConfirmation(Base):
    """An external confirmation request (bank, receivable, payable, legal, other)."""

    __tablename__ = "audit_confirmations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[ConfirmationType] = mapped_column(_enum(ConfirmationType, "confirmation_type"))
    counterparty: Mapped[str] = mapped_column(String(200))
    # An internal reference; bank account numbers are not stored here.
    reference: Mapped[str] = mapped_column(String(100), default="")
    book_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[ConfirmationStatus] = mapped_column(
        _enum(ConfirmationStatus, "confirmation_status"), default=ConfirmationStatus.PLANNED
    )
    sent_on: Mapped[date | None] = mapped_column(Date)
    responded_on: Mapped[date | None] = mapped_column(Date)
    confirmed_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    response_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class AuditAdjustment(Base):
    """A proposed audit adjustment; recorded by the client or passed (unadjusted)."""

    __tablename__ = "audit_adjustments"
    __table_args__ = (UniqueConstraint("engagement_id", "ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[AdjustmentStatus] = mapped_column(
        _enum(AdjustmentStatus, "adjustment_status"), default=AdjustmentStatus.PROPOSED
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    lines: Mapped[list[AdjustmentLine]] = relationship(
        back_populates="adjustment", order_by="AdjustmentLine.ordinal", cascade="all, delete-orphan"
    )


class AdjustmentLine(Base):
    __tablename__ = "audit_adjustment_lines"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_adjustments.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    account_code: Mapped[str] = mapped_column(String(80))
    debit: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal(0))
    credit: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal(0))

    adjustment: Mapped[AuditAdjustment] = relationship(back_populates="lines")


class PbcRequest(Base):
    """A 'prepared by client' request; the assigned client user answers it in the portal."""

    __tablename__ = "pbc_requests"
    __table_args__ = (UniqueConstraint("engagement_id", "ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PbcStatus] = mapped_column(
        _enum(PbcStatus, "pbc_status"), default=PbcStatus.REQUESTED
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    client_note: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    files: Mapped[list[PbcFile]] = relationship(
        back_populates="request", order_by="PbcFile.created_at", cascade="all, delete-orphan"
    )


class PbcFile(Base):
    __tablename__ = "pbc_files"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pbc_requests.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT")
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    request: Mapped[PbcRequest] = relationship(back_populates="files")
    document: Mapped[Document] = relationship(lazy="joined")


class LetterPoint(Base):
    """A management letter point drawn from one confirmed finding of the engagement."""

    __tablename__ = "letter_points"
    __table_args__ = (UniqueConstraint("engagement_id", "finding_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    management_response: Mapped[str] = mapped_column(Text, default="")
    response_owner: Mapped[str] = mapped_column(String(200), default="")
    response_due: Mapped[date | None] = mapped_column(Date)

    finding: Mapped[Finding] = relationship(lazy="joined")


class LetterSnapshot(Base):
    """An issued management letter version (immutable; a database trigger rejects UPDATE)."""

    __tablename__ = "letter_snapshots"
    __table_args__ = (UniqueConstraint("engagement_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class TimeEntry(Base):
    """Hours one team member worked on one phase on one day."""

    __tablename__ = "engagement_time_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_engagements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    phase: Mapped[EngagementPhase] = mapped_column(_enum(EngagementPhase, "engagement_phase"))
    work_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(lazy="joined")


class AuditEvent(Base):
    """Append-only, hash-chained audit trail (one chain per organisation).

    See ``app/services/audit.py``. A database trigger rejects UPDATE.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
        UniqueConstraint(
            "org_id", "seq", name="uq_audit_events_org_seq", postgresql_nulls_not_distinct=True
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # No ON DELETE action: the actor is part of the hashed content, so users with
    # audit history are deactivated rather than deleted.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = _created()
    seq: Mapped[int] = mapped_column(BigInteger)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    actor: Mapped[User | None] = relationship(lazy="joined")


# ---------------------------------------------------------------- continuous assurance (Phase E)


class AssuranceStatus(str, enum.Enum):
    DRAFT = "draft"
    PREPARED = "prepared"
    SIGNED_OFF = "signed_off"


class AssuranceObject(str, enum.Enum):
    BANK_RECONCILIATION = "bank_reconciliation"
    ACCOUNT_RECONCILIATION = "account_reconciliation"
    INTERCOMPANY = "intercompany"
    FLUX = "flux"
    CERTIFICATION = "certification"


class SignOffMixin:
    """Prepare → independent sign-off → immutable snapshot (version n), as in Phase D."""

    status: Mapped[AssuranceStatus] = mapped_column(
        _enum(AssuranceStatus, "assurance_status"), default=AssuranceStatus.DRAFT
    )
    prepared_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0)
    reopen_reason: Mapped[str] = mapped_column(Text, default="")


class AssuranceSnapshot(Base):
    """A signed-off reconciliation, flux or certification (immutable; trigger rejects UPDATE)."""

    __tablename__ = "assurance_snapshots"
    __table_args__ = (UniqueConstraint("object_type", "object_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    object_type: Mapped[AssuranceObject] = mapped_column(_enum(AssuranceObject, "assurance_object"))
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    sha256: Mapped[str] = mapped_column(String(64))
    signed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class ReconMethod(str, enum.Enum):
    REFERENCE = "reference"
    AMOUNT_DATE = "amount_date"
    REFERENCE_GROUP = "reference_group"
    MANUAL = "manual"


class ReconSide(str, enum.Enum):
    BANK = "bank"
    BOOK = "book"


class BankReconciliation(SignOffMixin, Base):
    """A bank statement version matched against general ledger lines for one period."""

    __tablename__ = "bank_reconciliations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # A label only (e.g. "Operating account"); account numbers and IBANs are not stored.
    account_label: Mapped[str] = mapped_column(String(100))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    statement_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    ledger_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    gl_accounts: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rules_prefix: Mapped[str] = mapped_column(String(80))
    bank_closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    book_opening_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal(0))
    matcher_version: Mapped[str] = mapped_column(String(40), default="")
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    matches: Mapped[list[ReconMatch]] = relationship(
        back_populates="reconciliation",
        order_by="ReconMatch.created_at",
        cascade="all, delete-orphan",
    )


class ReconMatch(Base):
    __tablename__ = "recon_matches"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_reconciliations.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[ReconMethod] = mapped_column(_enum(ReconMethod, "recon_method"))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    reconciliation: Mapped[BankReconciliation] = relationship(back_populates="matches")
    lines: Mapped[list[ReconMatchLine]] = relationship(
        back_populates="match", order_by="ReconMatchLine.row_id", cascade="all, delete-orphan"
    )


class ReconMatchLine(Base):
    __tablename__ = "recon_match_lines"
    __table_args__ = (UniqueConstraint("reconciliation_id", "side", "row_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recon_matches.id", ondelete="CASCADE"), index=True
    )
    # Denormalised so a row can be matched only once per reconciliation (unique above).
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_reconciliations.id", ondelete="CASCADE")
    )
    side: Mapped[ReconSide] = mapped_column(_enum(ReconSide, "recon_side"))
    row_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))

    match: Mapped[ReconMatch] = relationship(back_populates="lines")


class AccountReconciliation(SignOffMixin, Base):
    """One balance-sheet account at one date: TB balance against supporting items."""

    __tablename__ = "account_reconciliations"
    __table_args__ = (UniqueConstraint("tb_version_id", "account_code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    tb_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    as_of: Mapped[date] = mapped_column(Date)
    account_code: Mapped[str] = mapped_column(String(80))
    account_name: Mapped[str] = mapped_column(String(300), default="")
    currency: Mapped[str] = mapped_column(String(3))
    tb_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    tb_row_ids: Mapped[list[int]] = mapped_column(JSONType, default=list)
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rules_prefix: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    items: Mapped[list[ReconSupportItem]] = relationship(
        back_populates="reconciliation",
        order_by="ReconSupportItem.ordinal",
        cascade="all, delete-orphan",
    )


class ReconSupportItem(Base):
    """A supporting balance (sub-ledger, schedule, statement) with optional evidence."""

    __tablename__ = "recon_support_items"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_reconciliations.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    note: Mapped[str] = mapped_column(Text, default="")

    reconciliation: Mapped[AccountReconciliation] = relationship(back_populates="items")


class IntercompanyReconciliation(SignOffMixin, Base):
    """Two entities' intercompany balances that should net to zero at one date."""

    __tablename__ = "intercompany_reconciliations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    entity_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    tb_a_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    accounts_a: Mapped[list[str]] = mapped_column(JSONType, default=list)
    entity_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    tb_b_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    accounts_b: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rules_prefix: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity_a: Mapped[LegalEntity] = relationship(foreign_keys=[entity_a_id], lazy="joined")
    entity_b: Mapped[LegalEntity] = relationship(foreign_keys=[entity_b_id], lazy="joined")


class ClosePeriodStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class ClosePeriod(Base):
    """A month-end (or other) close for one entity; its checklist items are tasks."""

    __tablename__ = "close_periods"
    __table_args__ = (UniqueConstraint("entity_id", "period_end"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[ClosePeriodStatus] = mapped_column(
        _enum(ClosePeriodStatus, "close_period_status"), default=ClosePeriodStatus.OPEN
    )
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    items: Mapped[list[CloseItem]] = relationship(
        back_populates="period", order_by="CloseItem.ordinal", cascade="all, delete-orphan"
    )


class CloseItem(Base):
    """One checklist step: due ``day_offset`` days after the period end (may be negative)."""

    __tablename__ = "close_items"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    close_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("close_periods.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    day_offset: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE")
    )

    period: Mapped[ClosePeriod] = relationship(back_populates="items")
    task: Mapped[Task] = relationship(lazy="joined")


class FluxReview(SignOffMixin, Base):
    """Current against prior trial balance per account, with explanations above threshold."""

    __tablename__ = "flux_reviews"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    cy_tb_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    py_tb_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    rule_pack_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="RESTRICT")
    )
    rules_prefix: Mapped[str] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    explanations: Mapped[list[FluxExplanation]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class FluxExplanation(Base):
    __tablename__ = "flux_explanations"
    __table_args__ = (UniqueConstraint("review_id", "account_code"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flux_reviews.id", ondelete="CASCADE"), index=True
    )
    account_code: Mapped[str] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text)
    explained_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    explained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    review: Mapped[FluxReview] = relationship(back_populates="explanations")


# ---------------------------------------------------------------- internal controls (E3)


class ControlNature(str, enum.Enum):
    PREVENTIVE = "preventive"
    DETECTIVE = "detective"


class ControlAutomation(str, enum.Enum):
    MANUAL = "manual"
    AUTOMATED = "automated"
    IT_DEPENDENT = "it_dependent"


class ControlFrequency(str, enum.Enum):
    MULTIPLE_DAILY = "multiple_daily"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    AD_HOC = "ad_hoc"


class ControlTestKind(str, enum.Enum):
    DESIGN = "design"
    OPERATING = "operating"


class ControlTestStatus(str, enum.Enum):
    PLANNED = "planned"
    COMPLETED = "completed"


class ControlConclusion(str, enum.Enum):
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"


class DeficiencyClass(str, enum.Enum):
    DEFICIENCY = "deficiency"
    SIGNIFICANT_DEFICIENCY = "significant_deficiency"
    MATERIAL_WEAKNESS = "material_weakness"


class DeficiencyStatus(str, enum.Enum):
    OPEN = "open"
    REMEDIATED = "remediated"


class ControlProcess(Base):
    __tablename__ = "control_processes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")
    risks: Mapped[list[ControlRisk]] = relationship(
        back_populates="process", order_by="ControlRisk.ref", cascade="all, delete-orphan"
    )
    controls: Mapped[list[Control]] = relationship(
        back_populates="process", order_by="Control.ref", cascade="all, delete-orphan"
    )


class ControlRisk(Base):
    __tablename__ = "control_risks"
    __table_args__ = (UniqueConstraint("process_id", "ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_processes.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    assertions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rating: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel, "risk_level"))

    process: Mapped[ControlProcess] = relationship(back_populates="risks")


class Control(Base):
    __tablename__ = "controls"
    __table_args__ = (UniqueConstraint("process_id", "ref"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_processes.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    key: Mapped[bool] = mapped_column(Boolean, default=False)
    nature: Mapped[ControlNature] = mapped_column(_enum(ControlNature, "control_nature"))
    automation: Mapped[ControlAutomation] = mapped_column(
        _enum(ControlAutomation, "control_automation")
    )
    frequency: Mapped[ControlFrequency] = mapped_column(
        _enum(ControlFrequency, "control_frequency")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    risk_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)

    process: Mapped[ControlProcess] = relationship(back_populates="controls")
    tests: Mapped[list[ControlTest]] = relationship(
        back_populates="control", order_by="ControlTest.created_at", cascade="all, delete-orphan"
    )


class ControlTest(Base):
    """A design or operating effectiveness test of one control, with evidence."""

    __tablename__ = "control_tests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("controls.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ControlTestKind] = mapped_column(_enum(ControlTestKind, "control_test_kind"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    procedure: Mapped[str] = mapped_column(Text, default="")
    # Entered by the tester; the product does not compute or recommend a sample size.
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    exceptions: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    status: Mapped[ControlTestStatus] = mapped_column(
        _enum(ControlTestStatus, "control_test_status"), default=ControlTestStatus.PLANNED
    )
    conclusion: Mapped[ControlConclusion | None] = mapped_column(
        _enum(ControlConclusion, "control_conclusion")
    )
    rationale: Mapped[str] = mapped_column(Text, default="")
    tester_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    control: Mapped[Control] = relationship(back_populates="tests")


class ControlDeficiency(Base):
    """A control gap. A person classifies it; the product never does."""

    __tablename__ = "control_deficiencies"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("controls.id", ondelete="CASCADE"), index=True
    )
    test_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_tests.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[DeficiencyClass | None] = mapped_column(
        _enum(DeficiencyClass, "deficiency_class")
    )
    rationale: Mapped[str] = mapped_column(Text, default="")
    classified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[DeficiencyStatus] = mapped_column(
        _enum(DeficiencyStatus, "deficiency_status"), default=DeficiencyStatus.OPEN
    )
    remediation_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    remediation_note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    control: Mapped[Control] = relationship(lazy="joined")


class ControlCertification(SignOffMixin, Base):
    """Management's certification for an entity and period, frozen at sign-off."""

    __tablename__ = "control_certifications"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    statement: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")


# ---------------------------------------------------------------- connectors (Phase E6)


class ConnectorProvider(str, enum.Enum):
    ZOHO_BOOKS = "zoho_books"
    ODOO = "odoo"


class ConnectorStatus(str, enum.Enum):
    PENDING = "pending"  # created; not yet authorised or tested
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectorSyncStatus(str, enum.Enum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    UNCHANGED = "unchanged"  # same content as the latest version; nothing new stored
    FAILED = "failed"


class Connector(Base):
    """A read-only link to an entity's accounting system. Secrets are encrypted at rest."""

    __tablename__ = "connectors"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[ConnectorProvider] = mapped_column(
        _enum(ConnectorProvider, "connector_provider")
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[ConnectorStatus] = mapped_column(
        _enum(ConnectorStatus, "connector_status"), default=ConnectorStatus.PENDING
    )
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Non-secret settings (Odoo base URL, database and user; Zoho organisation id).
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # crypto.encrypt_field of a JSON object (tokens or API key); never returned or logged.
    secret_enc: Mapped[str | None] = mapped_column(Text)
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    oauth_verifier_enc: Mapped[str | None] = mapped_column(Text)
    oauth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oauth_started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Dataset id per dataset kind, so each sync adds a version to the same dataset.
    datasets: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    entity: Mapped[LegalEntity] = relationship(lazy="joined")


class ConnectorSync(Base):
    """One pull of one dataset kind; succeeds with a new dataset version or none."""

    __tablename__ = "connector_syncs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[DatasetKind] = mapped_column(_enum(DatasetKind, "connector_sync_kind"))
    status: Mapped[ConnectorSyncStatus] = mapped_column(
        _enum(ConnectorSyncStatus, "connector_sync_status"), default=ConnectorSyncStatus.QUEUED
    )
    rows: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", ondelete="SET NULL")
    )
    message: Mapped[str] = mapped_column(Text, default="")
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- content packs (Phase F1)


class ContentPackInstall(Base):
    """One installation of a pack version into an organisation, as draft content."""

    __tablename__ = "content_pack_installs"
    __table_args__ = (UniqueConstraint("org_id", "pack_id", "pack_version"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    pack_id: Mapped[str] = mapped_column(String(60))
    pack_version: Mapped[str] = mapped_column(String(20))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    checklist_version_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rule_pack_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_pack_versions.id", ondelete="SET NULL")
    )
    installed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
