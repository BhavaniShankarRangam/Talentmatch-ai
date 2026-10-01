"""SQLAlchemy models. Every tenant-owned row carries tenant_id and every query filters on it."""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


def uid() -> str:
    return uuid.uuid4().hex


class Role:
    ADMIN = "admin"
    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    ALL = (ADMIN, RECRUITER, HIRING_MANAGER)


class AppStatus:
    RECEIVED = "received"
    PROCESSING = "processing"
    AWAITING_RUBRIC = "awaiting_rubric"
    SCORING = "scoring"
    SCORED = "scored"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    DUPLICATE = "duplicate"


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    allowed_email_domains: Mapped[list] = mapped_column(JSON, default=list)
    allow_resume_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class JobOpening(Base):
    __tablename__ = "job_openings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    active_rubric_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    description_versions: Mapped[list["JobDescriptionVersion"]] = relationship(
        back_populates="job", order_by="JobDescriptionVersion.version", cascade="all, delete-orphan"
    )


class JobDescriptionVersion(Base):
    __tablename__ = "job_description_versions"
    __table_args__ = (UniqueConstraint("job_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_openings.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="pasted")
    created_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[JobOpening] = relationship(back_populates="description_versions")


class RubricVersion(Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (UniqueConstraint("job_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_openings.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    job_description_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft | approved | superseded
    proposed_by: Mapped[str] = mapped_column(String(120))
    model_config_json: Mapped[dict] = mapped_column("model_config", JSON, default=dict)
    scoring_logic_version: Mapped[str] = mapped_column(String(64))
    approved_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    criteria: Mapped[list["RubricCriterion"]] = relationship(
        back_populates="rubric", order_by="RubricCriterion.position", cascade="all, delete-orphan"
    )


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    rubric_version_id: Mapped[str] = mapped_column(ForeignKey("rubric_versions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    # Each entry: "Label: alt1|alt2" or "alt1|alt2". Used as evidence hints.
    evidence_terms: Mapped[list] = mapped_column(JSON, default=list)

    rubric: Mapped[RubricVersion] = relationship(back_populates="criteria")


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    external_candidate_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "external_application_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_openings.id"), index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    external_application_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_system: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default=AppStatus.RECEIVED)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    flag_details: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_of_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    candidate: Mapped[Candidate | None] = relationship()
    job: Mapped[JobOpening] = relationship()
    document: Mapped["Document | None"] = relationship(
        back_populates="application", uselist=False, cascade="all, delete-orphan"
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="application", order_by="Evaluation.created_at", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|parsed|needs_review|failed
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segments: Mapped[list] = mapped_column(JSON, default=list)
    extracted_char_count: Mapped[int] = mapped_column(Integer, default=0)
    extraction_confidence: Mapped[str] = mapped_column(String(16), default="none")
    extraction_notes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped[Application] = relationship(back_populates="document")


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    rubric_version_id: Mapped[str] = mapped_column(ForeignKey("rubric_versions.id"))
    # Score stored as an integer in units of 1/10000 so filtering is exact on every database.
    score_e4: Mapped[int] = mapped_column(Integer, index=True)
    required_status: Mapped[str] = mapped_column(String(32))
    extraction_confidence: Mapped[str] = mapped_column(String(16))
    supported_terms: Mapped[list] = mapped_column(JSON, default=list)
    missing_terms: Mapped[list] = mapped_column(JSON, default=list)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    scoring_logic_version: Mapped[str] = mapped_column(String(64))
    model_config_json: Mapped[dict] = mapped_column("model_config", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped[Application] = relationship(back_populates="evaluations")
    assessments: Mapped[list["CriterionAssessment"]] = relationship(
        back_populates="evaluation", order_by="CriterionAssessment.position", cascade="all, delete-orphan"
    )


class CriterionAssessment(Base):
    __tablename__ = "criterion_assessments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), index=True)
    criterion_id: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    criterion_name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float] = mapped_column(Float)
    required: Mapped[bool] = mapped_column(Boolean)
    level: Mapped[str] = mapped_column(String(32))
    level_points: Mapped[float] = mapped_column(Float)
    contribution_e4: Mapped[int] = mapped_column(Integer)
    required_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    supported_points: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    ambiguities: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")

    evaluation: Mapped[Evaluation] = relationship(back_populates="assessments")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EmailSend(Base):
    __tablename__ = "email_sends"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_openings.id"))
    sender_id: Mapped[str] = mapped_column(String(32))
    sender_email: Mapped[str] = mapped_column(String(320))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    to_recipients: Mapped[list] = mapped_column(JSON, default=list)
    cc_recipients: Mapped[list] = mapped_column(JSON, default=list)
    external_recipients: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    rendered_text: Mapped[str] = mapped_column(Text)
    include_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    score_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    application_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|sending|accepted|failed
    delivery_status: Mapped[str] = mapped_column(String(32), default="unknown")  # unknown|delivered|bounced
    provider: Mapped[str] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MockOutboxMessage(Base):
    __tablename__ = "mock_outbox"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email_send_id: Mapped[str] = mapped_column(String(32), index=True)
    from_addr: Mapped[str] = mapped_column(String(320))
    to_recipients: Mapped[list] = mapped_column(JSON, default=list)
    cc_recipients: Mapped[list] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class IngestedMessage(Base):
    """One row per mailbox message seen, whatever the outcome, so re-syncs are idempotent and
    recruiters can see why a message did or did not become an application."""
    __tablename__ = "ingested_messages"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "record_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    record_key: Mapped[str] = mapped_column(String(200))
    message_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # imported | duplicate_message | no_resume_attachment | unmapped_job | rejected_file
    outcome: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    application_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationConfig(Base):
    __tablename__ = "integration_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "kind"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), default="not_configured")
    # Non-secret settings only. Credentials live in server-side secrets, never in this table.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
