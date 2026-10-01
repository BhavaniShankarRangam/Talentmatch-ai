import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import can, get_scoped_or_404, require
from app.files import UploadRejected
from app.models import Application, AppStatus, Document, Evaluation, JobOpening, RubricVersion, Task, User
from app.scoring import from_e4
from app.services.candidate_query import CandidateFilter, candidate_row, query_candidates
from app.services.pipeline import ingest_document, queue_rescoring, requeue_processing
from app.services.retention import delete_application

router = APIRouter(prefix="/api", tags=["applications"])

MAX_FILES_PER_UPLOAD = 50


def _dt(d):
    return d.isoformat() + "Z" if d else None


@router.post("/jobs/{job_id}/applications/upload")
async def upload_resumes(job_id: str, files: list[UploadFile] = File(...),
                         user: User = Depends(require("applications:upload")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time.")
    limit = get_settings().max_upload_bytes
    results = []
    for f in files:
        data = await f.read(limit + 1)  # never read more than the limit + 1 byte
        try:
            r = ingest_document(db, tenant_id=user.tenant_id, job=job, filename=f.filename or "", data=data,
                                source_system="manual_upload", user=user)
            db.commit()
            results.append({"filename": f.filename, "accepted": True, "application_id": r.application.id,
                            "duplicate": r.duplicate, "status": r.application.status})
        except UploadRejected as e:
            db.rollback()
            audit.record(db, tenant_id=user.tenant_id, user=user, action="application.upload_rejected",
                         entity_type="job", entity_id=job.id, details={"reason": str(e)})
            db.commit()
            results.append({"filename": f.filename, "accepted": False, "error": str(e)})
    return {"results": results}


@router.get("/jobs/{job_id}/ingestion")
def ingestion_status(job_id: str, user: User = Depends(require("applications:read")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    apps = db.scalars(select(Application).where(Application.tenant_id == user.tenant_id, Application.job_id == job.id)
                      .order_by(Application.created_at.desc())).all()
    failed = db.scalars(select(Task).where(Task.tenant_id == user.tenant_id, Task.status.in_(["failed", "queued", "running"]),
                                           Task.type == "connector_ingest").order_by(Task.created_at.desc()).limit(50)).all()
    return {
        "applications": [{
            "application_id": a.id,
            "candidate_name": a.candidate.full_name if a.candidate else None,
            "filename": a.document.original_filename if a.document else None,
            "source_system": a.source_system, "external_application_id": a.external_application_id,
            "submitted_at": _dt(a.submitted_at), "status": a.status, "status_detail": a.status_detail,
            "parse_status": a.document.parse_status if a.document else None,
            "extraction_confidence": a.document.extraction_confidence if a.document else None,
            "page_count": a.document.page_count if a.document else None,
            "duplicate_of_id": a.duplicate_of_id, "flags": a.flags or [],
        } for a in apps],
        "connector_tasks": [{"id": t.id, "status": t.status, "attempts": t.attempts, "max_attempts": t.max_attempts,
                             "record_id": t.payload.get("record_id"), "source": t.payload.get("kind"),
                             "last_error": t.last_error, "updated_at": _dt(t.updated_at)} for t in failed],
    }


def _filter(min_score, max_score, required_status, search, status, sort, order, page, page_size) -> CandidateFilter:
    return CandidateFilter(min_score=min_score, max_score=max_score, required_status=required_status or None,
                           search=search or None, status=status or None, sort=sort, order=order, page=page,
                           page_size=page_size)


@router.get("/jobs/{job_id}/candidates")
def list_candidates(
    job_id: str,
    min_score: float | None = Query(None), max_score: float | None = Query(None),
    required_status: str | None = None, search: str | None = None, status: str | None = None,
    sort: str = "score", order: str = "desc", page: int = 1, page_size: int = 25,
    user: User = Depends(require("applications:read")), db: Session = Depends(get_db),
):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    f = _filter(min_score, max_score, required_status, search, status, sort, order, page, page_size)
    rows, total = query_candidates(db, user.tenant_id, job, f)
    return {"items": [candidate_row(a, ev, job) for a, ev in rows], "total": total, "page": f.page,
            "page_size": f.page_size, "filter": {"min_score": min_score, "max_score": max_score,
                                                 "required_status": required_status}}


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # spreadsheet formula injection guard


@router.get("/jobs/{job_id}/candidates/export.csv")
def export_candidates(
    job_id: str,
    min_score: float | None = Query(None), max_score: float | None = Query(None),
    required_status: str | None = None, search: str | None = None, status: str | None = None,
    sort: str = "score", order: str = "desc",
    user: User = Depends(require("applications:read")), db: Session = Depends(get_db),
):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    f = _filter(min_score, max_score, required_status, search, status, sort, order, 1, 25)
    rows, _ = query_candidates(db, user.tenant_id, job, f, paginate=False)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["candidate_name", "job_opening", "alignment_score_exact", "required_criteria_status",
                "supported_skills", "missing_or_unclear", "processing_status", "flags", "mock_scoring",
                "source_system", "submitted_at", "application_id"])
    for a, ev in rows:
        r = candidate_row(a, ev, job)
        w.writerow([_csv_safe(x) for x in [
            r["candidate_name"], r["job_title"], r["score_exact"], r["required_status"],
            "; ".join(r["supported_skills"]), "; ".join(r["missing_or_unclear"]), r["status"],
            "; ".join(r["flags"]), r["is_mock"], r["source_system"], r["submitted_at"], r["application_id"]]])
    audit.record(db, tenant_id=user.tenant_id, user=user, action="candidates.exported", entity_type="job",
                 entity_id=job.id, details={"rows": len(rows), "min_score": min_score, "max_score": max_score})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="candidates-{job.id[:8]}.csv"'})


def assessment_out(a) -> dict:
    return {
        "criterion_id": a.criterion_id, "criterion_name": a.criterion_name, "category": a.category,
        "weight": a.weight, "required": a.required, "level": a.level, "level_points": a.level_points,
        "contribution": from_e4(a.contribution_e4), "contribution_exact": f"{a.contribution_e4 / 10000:.4f}",
        "required_status": a.required_status, "evidence": a.evidence, "supported_points": a.supported_points,
        "missing": a.missing, "ambiguities": a.ambiguities, "rationale": a.rationale,
    }


def evaluation_out(db: Session, ev: Evaluation, full: bool) -> dict:
    rubric = db.get(RubricVersion, ev.rubric_version_id)
    out = {
        "id": ev.id, "score": from_e4(ev.score_e4), "score_exact": f"{ev.score_e4 / 10000:.4f}",
        "required_status": ev.required_status, "extraction_confidence": ev.extraction_confidence,
        "is_mock": ev.is_mock, "is_current": ev.is_current, "rubric_version_id": ev.rubric_version_id,
        "rubric_version": rubric.version if rubric else None, "scoring_logic_version": ev.scoring_logic_version,
        "model_config": ev.model_config_json, "created_at": _dt(ev.created_at),
    }
    if full:
        out["assessments"] = [assessment_out(a) for a in ev.assessments]
    return out


@router.get("/applications/{application_id}")
def application_detail(application_id: str, user: User = Depends(require("applications:read")),
                       db: Session = Depends(get_db)):
    app = get_scoped_or_404(db, Application, application_id, user.tenant_id)
    job = db.get(JobOpening, app.job_id)
    current = next((e for e in app.evaluations if e.is_current), None)
    doc = app.document
    audit.record(db, tenant_id=user.tenant_id, user=user, action="application.viewed", entity_type="application",
                 entity_id=app.id)
    db.commit()
    return {
        "application_id": app.id, "job": {"id": job.id, "title": job.title},
        "candidate": {"id": app.candidate.id, "full_name": app.candidate.full_name, "email": app.candidate.email}
        if app.candidate else None,
        "source_system": app.source_system, "external_application_id": app.external_application_id,
        "submitted_at": _dt(app.submitted_at), "status": app.status, "status_detail": app.status_detail,
        "flags": app.flags or [], "flag_details": app.flag_details or [], "duplicate_of_id": app.duplicate_of_id,
        "document": {"id": doc.id, "filename": doc.original_filename, "content_type": doc.content_type,
                     "size_bytes": doc.size_bytes, "parse_status": doc.parse_status, "parse_error": doc.parse_error,
                     "page_count": doc.page_count, "extraction_confidence": doc.extraction_confidence,
                     "extraction_notes": doc.extraction_notes, "extracted_char_count": doc.extracted_char_count}
        if doc else None,
        "current_evaluation": evaluation_out(db, current, True) if current else None,
        "evaluation_history": [evaluation_out(db, e, False) for e in reversed(app.evaluations)],
        "can_reprocess": can(user, "applications:reprocess"), "can_delete": can(user, "data:delete"),
    }


@router.post("/applications/{application_id}/reprocess")
def reprocess(application_id: str, user: User = Depends(require("applications:reprocess")),
              db: Session = Depends(get_db)):
    app = get_scoped_or_404(db, Application, application_id, user.tenant_id)
    if app.status in (AppStatus.PROCESSING, AppStatus.SCORING):
        raise HTTPException(409, "Application is already being processed.")
    requeue_processing(db, app)
    audit.record(db, tenant_id=user.tenant_id, user=user, action="application.reprocess_requested",
                 entity_type="application", entity_id=app.id)
    db.commit()
    return {"status": app.status}


@router.post("/jobs/{job_id}/rescore")
def rescore(job_id: str, user: User = Depends(require("applications:reprocess")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    if not job.active_rubric_version_id:
        raise HTTPException(409, "Approve a rubric first.")
    n = queue_rescoring(db, db.get(RubricVersion, job.active_rubric_version_id))
    audit.record(db, tenant_id=user.tenant_id, user=user, action="job.rescore_requested", entity_type="job",
                 entity_id=job.id, details={"queued": n})
    db.commit()
    return {"queued": n}


@router.delete("/applications/{application_id}")
def delete_app(application_id: str, user: User = Depends(require("data:delete")), db: Session = Depends(get_db)):
    app = get_scoped_or_404(db, Application, application_id, user.tenant_id)
    delete_application(db, app, user, reason="manual deletion request")
    db.commit()
    return {"deleted": True}


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, user: User = Depends(require("documents:read")),
                      db: Session = Depends(get_db)):
    from app.storage import StorageAccessError, get_storage

    doc = get_scoped_or_404(db, Document, document_id, user.tenant_id)
    try:
        data = get_storage().read(user.tenant_id, doc.storage_key)
    except (StorageAccessError, FileNotFoundError):
        raise HTTPException(404, "Document not found")
    audit.record(db, tenant_id=user.tenant_id, user=user, action="document.downloaded", entity_type="document",
                 entity_id=doc.id, details={"application_id": doc.application_id})
    db.commit()
    return Response(content=data, media_type=doc.content_type, headers={
        "Content-Disposition": f'inline; filename="{doc.original_filename}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
