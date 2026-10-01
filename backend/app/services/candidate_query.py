"""Tenant-scoped candidate results query used by the API, CSV export and chatbot tools."""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Application, Candidate, Document, Evaluation, JobOpening
from app.scoring import from_e4, range_bounds_e4, to_decimal

REQUIRED_FILTERS = {"all_supported", "needs_clarification", "not_supported", "none_required"}
SORTS = {"score", "name", "submitted_at"}


@dataclass
class CandidateFilter:
    min_score: float | None = None
    max_score: float | None = None
    required_status: str | None = None
    search: str | None = None
    status: str | None = None
    sort: str = "score"
    order: str = "desc"
    page: int = 1
    page_size: int = 25


def validate_filter(f: CandidateFilter) -> None:
    errors = []
    for label, v in (("Minimum score", f.min_score), ("Maximum score", f.max_score)):
        if v is not None and not (0 <= to_decimal(v) <= 100):
            errors.append(f"{label} must be between 0 and 100.")
    if f.min_score is not None and f.max_score is not None and to_decimal(f.min_score) > to_decimal(f.max_score):
        errors.append("Minimum score cannot be greater than maximum score.")
    if f.required_status and f.required_status not in REQUIRED_FILTERS:
        errors.append(f"Unknown required-criteria status {f.required_status!r}.")
    if f.sort not in SORTS or f.order not in ("asc", "desc"):
        errors.append("Invalid sort.")
    if f.page < 1 or not (1 <= f.page_size <= 200):
        errors.append("Invalid pagination.")
    if errors:
        raise HTTPException(422, {"message": "Invalid filter", "errors": errors})


def query_candidates(db: Session, tenant_id: str, job: JobOpening, f: CandidateFilter, paginate: bool = True):
    validate_filter(f)
    assert job.tenant_id == tenant_id
    q = (
        select(Application, Evaluation)
        .outerjoin(Evaluation, and_(Evaluation.application_id == Application.id, Evaluation.is_current.is_(True),
                                    Evaluation.tenant_id == tenant_id))
        .outerjoin(Candidate, Candidate.id == Application.candidate_id)
        .where(Application.tenant_id == tenant_id, Application.job_id == job.id)
    )
    if f.min_score is not None or f.max_score is not None:
        lo, hi = range_bounds_e4(f.min_score if f.min_score is not None else 0,
                                 f.max_score if f.max_score is not None else 100)
        # Inclusive on the exact (unrounded) stored score. Unscored applications are excluded.
        q = q.where(Evaluation.score_e4 >= lo, Evaluation.score_e4 <= hi)
    if f.required_status:
        q = q.where(Evaluation.required_status == f.required_status)
    if f.status:
        q = q.where(Application.status == f.status)
    if f.search:
        term = f"%{f.search.strip().lower()}%"
        q = q.where(or_(func.lower(Candidate.full_name).like(term), func.lower(Candidate.email).like(term),
                        Application.id.in_(select(Document.application_id).where(
                            Document.tenant_id == tenant_id, func.lower(Document.original_filename).like(term)))))

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    desc = f.order == "desc"
    if f.sort == "score":
        key = Evaluation.score_e4.desc() if desc else Evaluation.score_e4.asc()
        q = q.order_by(Evaluation.score_e4.is_(None), key, Application.submitted_at.asc())
    elif f.sort == "name":
        q = q.order_by(Candidate.full_name.desc() if desc else Candidate.full_name.asc())
    else:
        q = q.order_by(Application.submitted_at.desc() if desc else Application.submitted_at.asc())
    q = q.options(selectinload(Application.candidate), selectinload(Application.document))
    if paginate:
        q = q.offset((f.page - 1) * f.page_size).limit(f.page_size)
    rows = db.execute(q).all()
    return rows, total


def candidate_row(app: Application, ev: Evaluation | None, job: JobOpening) -> dict:
    doc = app.document
    return {
        "application_id": app.id,
        "candidate_name": (app.candidate.full_name if app.candidate else None) or "(name not detected)",
        "candidate_email": app.candidate.email if app.candidate else None,
        "job_id": job.id,
        "job_title": job.title,
        "score": from_e4(ev.score_e4) if ev else None,
        "score_exact": f"{ev.score_e4 / 10000:.4f}" if ev else None,
        "required_status": ev.required_status if ev else None,
        "supported_skills": ev.supported_terms if ev else [],
        "missing_or_unclear": ev.missing_terms if ev else [],
        "extraction_confidence": doc.extraction_confidence if doc else None,
        "status": app.status,
        "status_detail": app.status_detail,
        "flags": app.flags or [],
        "is_mock": ev.is_mock if ev else None,
        "source_system": app.source_system,
        "submitted_at": app.submitted_at.isoformat() + "Z",
        "document_id": doc.id if doc else None,
        "document_filename": doc.original_filename if doc else None,
    }
