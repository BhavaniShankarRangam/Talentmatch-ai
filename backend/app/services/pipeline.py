"""Resume ingestion -> parsing -> (redaction, injection screening) -> assessment -> scoring."""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import utcnow
from app.files import validate_upload
from app.llm.base import LEVELS, CriterionResult, CriterionSpec, LLMProvider
from app.llm.factory import get_llm_provider
from app.models import (
    Application,
    AppStatus,
    Candidate,
    CriterionAssessment,
    Document,
    Evaluation,
    JobOpening,
    RubricVersion,
    Task,
    User,
)
from app.parsing import Segment, parse_document
from app.safety import redact_segments, screen_segments
from app.scoring import (
    SCORING_LOGIC_VERSION,
    LEVEL_POINTS,
    compute_score,
    required_status_for,
    summarize_required,
    to_e4,
)
from app.services.tasks import PermanentTaskError, enqueue, register
from app.storage import get_storage

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'\-]+(?: [A-Z][a-zA-Z'\-]+){1,3}$")


@dataclass
class IngestResult:
    application: Application
    created: bool
    duplicate: bool


def ingest_document(
    db: Session,
    *,
    tenant_id: str,
    job: JobOpening,
    filename: str,
    data: bytes,
    source_system: str,
    user: User | None = None,
    submitted_at: datetime | None = None,
    external_application_id: str | None = None,
    external_candidate_id: str | None = None,
    candidate_email: str | None = None,
) -> IngestResult:
    """Validate, store privately, create the application and queue processing.
    Raises files.UploadRejected for invalid files (caller reports it per file)."""
    assert job.tenant_id == tenant_id
    settings = get_settings()

    if external_application_id:
        existing = db.scalar(
            select(Application).where(
                Application.tenant_id == tenant_id,
                Application.source_system == source_system,
                Application.external_application_id == external_application_id,
            )
        )
        if existing:
            return IngestResult(existing, created=False, duplicate=True)

    vf = validate_upload(filename, data, settings.max_upload_bytes)
    sha = hashlib.sha256(data).hexdigest()

    original = db.scalar(
        select(Application)
        .join(Document, Document.application_id == Application.id)
        .where(
            Application.tenant_id == tenant_id,
            Application.job_id == job.id,
            Document.sha256 == sha,
            Application.status != AppStatus.DUPLICATE,
        )
        .limit(1)
    )

    key = get_storage().save(tenant_id, data, vf.ext)
    app = Application(
        tenant_id=tenant_id,
        job_id=job.id,
        source_system=source_system,
        external_application_id=external_application_id,
        submitted_at=submitted_at or utcnow(),
        status=AppStatus.RECEIVED,
        flags=[],
        flag_details=[],
    )
    if external_candidate_id or candidate_email:
        cand = _find_or_create_candidate(db, tenant_id, external_candidate_id=external_candidate_id,
                                         email=candidate_email)
        app.candidate_id = cand.id
    db.add(app)
    db.flush()
    db.add(
        Document(
            tenant_id=tenant_id,
            application_id=app.id,
            original_filename=vf.filename,
            content_type=vf.content_type,
            size_bytes=len(data),
            sha256=sha,
            storage_key=key,
            parse_status="skipped_duplicate" if original is not None else "pending",
        )
    )
    if original is not None:
        app.status = AppStatus.DUPLICATE
        app.duplicate_of_id = original.id
        app.candidate_id = app.candidate_id or original.candidate_id
        app.status_detail = "Identical file already submitted for this job; not scored separately."
    else:
        enqueue(db, tenant_id, "process_application", {"application_id": app.id})
    audit.record(
        db, tenant_id=tenant_id, user=user, action="application.ingested",
        entity_type="application", entity_id=app.id,
        details={"job_id": job.id, "source": source_system, "file_type": vf.ext,
                 "size_bytes": len(data), "duplicate_of": app.duplicate_of_id},
    )
    return IngestResult(app, created=True, duplicate=original is not None)


def _find_or_create_candidate(
    db: Session, tenant_id: str, *, email: str | None = None, external_candidate_id: str | None = None,
    full_name: str | None = None,
) -> Candidate:
    cand = None
    if external_candidate_id:
        cand = db.scalar(select(Candidate).where(Candidate.tenant_id == tenant_id,
                                                 Candidate.external_candidate_id == external_candidate_id))
    if cand is None and email:
        cand = db.scalar(select(Candidate).where(Candidate.tenant_id == tenant_id, Candidate.email == email))
    if cand is None:
        cand = Candidate(tenant_id=tenant_id, email=email, full_name=full_name,
                         external_candidate_id=external_candidate_id)
        db.add(cand)
        db.flush()
    return cand


def _identify(segments: list[Segment]) -> tuple[str | None, str | None]:
    header = [s.text for s in segments if s.section == "header"][:6]
    name = next((t for t in header if _NAME_RE.match(t)), None)
    email = None
    for t in header + [s.text for s in segments[:15]]:
        m = _EMAIL_RE.search(t)
        if m:
            email = m.group(0).lower()
            break
    return name, email


def _load_app(db: Session, task: Task) -> Application:
    app = db.get(Application, task.payload.get("application_id"))
    if app is None or app.tenant_id != task.tenant_id:
        raise PermanentTaskError("Application not found for this tenant")
    return app


def _on_processing_failure(db: Session, task: Task, error: str) -> None:
    app = db.get(Application, task.payload.get("application_id"))
    if app is not None and app.tenant_id == task.tenant_id:
        app.status = AppStatus.NEEDS_MANUAL_REVIEW
        app.status_detail = f"Processing failed after {task.attempts} attempt(s): {error}. Routed to manual review."


@register("process_application", on_failure=_on_processing_failure)
def handle_process(db: Session, task: Task) -> None:
    app = _load_app(db, task)
    doc = app.document
    if doc is None:
        raise PermanentTaskError("Application has no document")
    app.status = AppStatus.PROCESSING
    data = get_storage().read(app.tenant_id, doc.storage_key)
    result = parse_document(data, "." + doc.original_filename.rsplit(".", 1)[-1].lower(),
                            get_settings().max_pdf_pages)
    doc.parse_status = result.status
    doc.parse_error = result.error
    doc.page_count = result.page_count
    doc.segments = [s.to_dict() for s in result.segments]
    doc.extracted_char_count = result.char_count
    doc.extraction_confidence = result.confidence
    doc.extraction_notes = result.notes

    name, email = _identify(result.segments)
    if app.candidate_id:
        cand = db.get(Candidate, app.candidate_id)
        cand.full_name = cand.full_name or name
        cand.email = cand.email or email
    elif name or email:
        cand = _find_or_create_candidate(db, app.tenant_id, email=email, full_name=name)
        app.candidate_id = cand.id
    if app.candidate_id:
        other = db.scalar(
            select(Application).where(
                Application.tenant_id == app.tenant_id, Application.job_id == app.job_id,
                Application.candidate_id == app.candidate_id, Application.id != app.id,
                Application.status != AppStatus.DUPLICATE,
            ).limit(1)
        )
        if other is not None:
            _add_flag(app, "possible_duplicate", {"type": "possible_duplicate", "other_application_id": other.id,
                                                  "detail": "Same candidate already applied to this job with a different file."})

    if result.status != "parsed":
        app.status = AppStatus.NEEDS_MANUAL_REVIEW
        app.status_detail = result.error or " ".join(result.notes) or "Insufficient text extracted."
        audit.record(db, tenant_id=app.tenant_id, action="application.needs_manual_review",
                     entity_type="application", entity_id=app.id, details={"parse_status": result.status})
        return
    if result.confidence == "low":
        _add_flag(app, "low_extraction_confidence", {"type": "low_extraction_confidence",
                                                     "detail": "Limited text extracted; verify evidence manually."})

    rubric = _active_rubric(db, app)
    if rubric is None:
        app.status = AppStatus.AWAITING_RUBRIC
        app.status_detail = "Parsed. Waiting for a recruiter-approved rubric before scoring."
        return
    score_application(db, app, rubric, get_llm_provider())


@register("score_application", on_failure=_on_processing_failure)
def handle_score(db: Session, task: Task) -> None:
    app = _load_app(db, task)
    rubric = db.get(RubricVersion, task.payload.get("rubric_version_id"))
    if rubric is None or rubric.tenant_id != app.tenant_id or rubric.job_id != app.job_id:
        raise PermanentTaskError("Rubric not found for this application")
    if rubric.status != "approved":
        return  # superseded before this task ran; the newer approval queued its own tasks
    if app.document is None or app.document.parse_status != "parsed":
        return
    score_application(db, app, rubric, get_llm_provider())


def _active_rubric(db: Session, app: Application) -> RubricVersion | None:
    job = db.get(JobOpening, app.job_id)
    if not job.active_rubric_version_id:
        return None
    r = db.get(RubricVersion, job.active_rubric_version_id)
    return r if r is not None and r.status == "approved" and r.tenant_id == app.tenant_id else None


def _add_flag(app: Application, flag: str, detail: dict) -> None:
    if flag not in (app.flags or []):
        app.flags = [*(app.flags or []), flag]
    app.flag_details = [*(app.flag_details or []), detail]


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def ground_results(
    specs: list[CriterionSpec], raw: list[CriterionResult], segments: list[Segment]
) -> list[CriterionResult]:
    """Validate provider output: one result per criterion, known levels only, and every quote
    must appear verbatim in the (redacted, screened) text the provider was given. Page/section
    references come from the document, not from the model."""
    by_id = {r.criterion_id: r for r in raw}
    corpus = [(s, _norm(s.text)) for s in segments]
    grounded: list[CriterionResult] = []
    for spec in specs:
        r = by_id.get(spec.id)
        if r is None:
            grounded.append(CriterionResult(spec.id, "none", ambiguities=[
                "The assessment returned no result for this criterion; treated as no evidence. Needs manual review."]))
            continue
        level = r.level if r.level in LEVELS else None
        amb = list(r.ambiguities)
        if level is None:
            amb.append(f"Invalid assessment level {r.level!r} was discarded.")
            level = "none"
        kept = []
        for ev in r.evidence:
            q = _norm(ev.quote or "")
            seg = next((s for s, t in corpus if len(q) >= 3 and q in t), None)
            if seg is None:
                amb.append("Cited evidence could not be verified in the document and was discarded.")
                continue
            ev.page, ev.section, ev.segment_index = seg.page, seg.section, seg.index
            kept.append(ev)
        if level != "none" and not kept:
            amb.append(f"Level '{level}' was downgraded to 'none' because no verifiable evidence remained.")
            level = "none"
        grounded.append(CriterionResult(spec.id, level, kept, r.supported_points, r.missing, amb, r.rationale))
    return grounded


def score_application(db: Session, app: Application, rubric: RubricVersion, provider: LLMProvider) -> Evaluation:
    doc = app.document
    segments = [Segment.from_dict(s) for s in doc.segments]
    usable = [s for s in segments if s.section not in ("header", "personal")]

    clean, flagged = screen_segments(usable)
    app.flag_details = [d for d in (app.flag_details or []) if d.get("type") != "prompt_injection_suspected"]
    app.flags = [f for f in (app.flags or []) if f != "prompt_injection_suspected"]
    if flagged:
        app.flags = [*app.flags, "prompt_injection_suspected"]
        app.flag_details = [*app.flag_details, *flagged]

    names = [app.candidate.full_name] if app.candidate and app.candidate.full_name else []
    model_input = redact_segments(clean, names)

    criteria = list(rubric.criteria)
    specs = [CriterionSpec(c.id, c.name, c.category, c.description, c.required, list(c.evidence_terms))
             for c in criteria]
    results = ground_results(specs, provider.assess(specs, model_input), model_input)
    breakdown = compute_score([(c.weight, r.level) for c, r in zip(criteria, results)])

    for old in app.evaluations:
        old.is_current = False
    req_statuses = [required_status_for(r.level) for c, r in zip(criteria, results) if c.required]
    supported_terms, missing_terms = [], []
    for c, r in zip(criteria, results):
        if c.category == "skills":
            supported_terms.extend(r.supported_points)
        missing_terms.extend(r.missing)
    ev = Evaluation(
        tenant_id=app.tenant_id,
        application_id=app.id,
        rubric_version_id=rubric.id,
        score_e4=to_e4(breakdown.total),
        required_status=summarize_required(req_statuses),
        extraction_confidence=doc.extraction_confidence,
        supported_terms=supported_terms,
        missing_terms=missing_terms,
        is_mock=provider.is_mock,
        is_current=True,
        scoring_logic_version=SCORING_LOGIC_VERSION,
        model_config_json=provider.config(),
    )
    for i, (c, r, contrib) in enumerate(zip(criteria, results, breakdown.contributions)):
        ev.assessments.append(
            CriterionAssessment(
                criterion_id=c.id, position=i, criterion_name=c.name, category=c.category,
                weight=c.weight, required=c.required, level=r.level,
                level_points=float(LEVEL_POINTS[r.level]), contribution_e4=to_e4(contrib),
                required_status=required_status_for(r.level) if c.required else None,
                evidence=[{"quote": e.quote, "page": e.page, "section": e.section,
                           "segment_index": e.segment_index, "term": e.term} for e in r.evidence],
                supported_points=r.supported_points, missing=r.missing, ambiguities=r.ambiguities,
                rationale=r.rationale,
            )
        )
    app.evaluations.append(ev)
    app.status = AppStatus.SCORED
    app.status_detail = None
    audit.record(db, tenant_id=app.tenant_id, action="application.scored", entity_type="application",
                 entity_id=app.id, details={"rubric_version_id": rubric.id, "score_e4": ev.score_e4,
                                            "provider": provider.name, "is_mock": provider.is_mock})
    return ev


def queue_rescoring(db: Session, rubric: RubricVersion) -> int:
    apps = db.scalars(
        select(Application).where(
            Application.tenant_id == rubric.tenant_id,
            Application.job_id == rubric.job_id,
            Application.status.in_([AppStatus.SCORED, AppStatus.AWAITING_RUBRIC]),
        )
    ).all()
    for app in apps:
        app.status = AppStatus.SCORING
        enqueue(db, rubric.tenant_id, "score_application",
                {"application_id": app.id, "rubric_version_id": rubric.id})
    return len(apps)


def requeue_processing(db: Session, app: Application) -> None:
    app.status = AppStatus.RECEIVED
    app.status_detail = "Reprocessing requested."
    enqueue(db, app.tenant_id, "process_application", {"application_id": app.id})
