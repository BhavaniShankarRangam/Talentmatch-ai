from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import get_scoped_or_404, require
from app.files import UploadRejected, validate_upload
from app.llm.factory import get_llm_provider
from app.models import Application, JobDescriptionVersion, JobOpening, RubricVersion, User
from app.parsing import ParseError, extract_raw_text
from app.scoring import weight_errors
from app.services import rubric_service as rs

router = APIRouter(prefix="/api", tags=["jobs & rubrics"])


class JobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    department: str | None = None
    location: str | None = None
    external_ref: str | None = None
    description: str | None = None


class JobPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    department: str | None = None
    location: str | None = None
    status: str | None = Field(default=None, pattern="^(open|closed|draft)$")
    external_ref: str | None = None


class DescriptionIn(BaseModel):
    text: str


class CriterionIn(BaseModel):
    name: str
    category: str
    description: str = ""
    weight: float
    required: bool = False
    evidence_terms: list[str] = []


class RubricUpdateIn(BaseModel):
    criteria: list[CriterionIn]


def _dt(d):
    return d.isoformat() + "Z" if d else None


def job_out(db: Session, job: JobOpening) -> dict:
    jd = rs.latest_description(db, job)
    counts = dict(db.execute(select(Application.status, func.count()).where(
        Application.tenant_id == job.tenant_id, Application.job_id == job.id).group_by(Application.status)).all())
    active = db.get(RubricVersion, job.active_rubric_version_id) if job.active_rubric_version_id else None
    return {
        "id": job.id, "title": job.title, "department": job.department, "location": job.location,
        "status": job.status, "external_ref": job.external_ref, "created_at": _dt(job.created_at),
        "description": {"version": jd.version, "text": jd.text, "id": jd.id, "created_at": _dt(jd.created_at)} if jd else None,
        "active_rubric": {"id": active.id, "version": active.version,
                          "job_description_version_id": active.job_description_version_id} if active else None,
        "description_changed_since_rubric": bool(active and jd and active.job_description_version_id != jd.id),
        "application_counts": counts,
        "application_total": sum(counts.values()),
    }


def rubric_out(r: RubricVersion) -> dict:
    criteria = [{"id": c.id, "position": c.position, "name": c.name, "category": c.category,
                 "description": c.description, "weight": c.weight, "required": c.required,
                 "evidence_terms": c.evidence_terms} for c in r.criteria]
    return {
        "id": r.id, "job_id": r.job_id, "version": r.version, "status": r.status,
        "job_description_version_id": r.job_description_version_id, "proposed_by": r.proposed_by,
        "model_config": r.model_config_json, "is_mock_proposal": bool(r.model_config_json.get("is_mock")),
        "scoring_logic_version": r.scoring_logic_version, "approved_by_id": r.approved_by_id,
        "approved_at": _dt(r.approved_at), "created_at": _dt(r.created_at), "criteria": criteria,
        "weight_total": round(sum(c.weight for c in r.criteria), 2),
        "validation_errors": rs.criteria_errors(rs.criteria_as_dicts(r)) if r.status == "draft" else [],
    }


@router.get("/jobs")
def list_jobs(user: User = Depends(require("jobs:read")), db: Session = Depends(get_db)):
    jobs = db.scalars(select(JobOpening).where(JobOpening.tenant_id == user.tenant_id)
                      .order_by(JobOpening.created_at.desc())).all()
    return [job_out(db, j) for j in jobs]


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, user: User = Depends(require("jobs:write")), db: Session = Depends(get_db)):
    job = JobOpening(tenant_id=user.tenant_id, title=body.title.strip(), department=body.department,
                     location=body.location, external_ref=body.external_ref, created_by_id=user.id)
    db.add(job)
    db.flush()
    audit.record(db, tenant_id=user.tenant_id, user=user, action="job.created", entity_type="job", entity_id=job.id,
                 details={"title": job.title})
    if body.description and body.description.strip():
        rs.add_description_version(db, job, body.description, user)
    db.commit()
    return job_out(db, job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(require("jobs:read")), db: Session = Depends(get_db)):
    return job_out(db, get_scoped_or_404(db, JobOpening, job_id, user.tenant_id))


@router.patch("/jobs/{job_id}")
def patch_job(job_id: str, body: JobPatch, user: User = Depends(require("jobs:write")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(job, k, v)
    audit.record(db, tenant_id=user.tenant_id, user=user, action="job.updated", entity_type="job", entity_id=job.id,
                 details={"fields": sorted(changes)})
    db.commit()
    return job_out(db, job)


@router.put("/jobs/{job_id}/description")
def put_description(job_id: str, body: DescriptionIn, user: User = Depends(require("jobs:write")),
                    db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    rs.add_description_version(db, job, body.text, user)
    db.commit()
    return job_out(db, job)


@router.post("/jobs/{job_id}/description/upload")
async def upload_description(job_id: str, file: UploadFile = File(...), user: User = Depends(require("jobs:write")),
                             db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    data = await file.read(get_settings().max_upload_bytes + 1)
    name = (file.filename or "").lower()
    if name.endswith(".txt"):
        if len(data) > get_settings().max_upload_bytes:
            raise HTTPException(400, "File too large.")
        text = data.decode("utf-8", errors="replace")
    else:
        try:
            vf = validate_upload(file.filename or "", data, get_settings().max_upload_bytes)
        except UploadRejected as e:
            raise HTTPException(400, str(e))
        try:
            text = extract_raw_text(data, vf.ext)
        except ParseError as e:
            raise HTTPException(422, str(e))
        if len(text.strip()) < 50:
            raise HTTPException(422, "Could not extract enough text from the job description file.")
    rs.add_description_version(db, job, text, user, source="uploaded")
    db.commit()
    return job_out(db, job)


@router.get("/jobs/{job_id}/description/versions")
def description_versions(job_id: str, user: User = Depends(require("jobs:read")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    vs = db.scalars(select(JobDescriptionVersion).where(JobDescriptionVersion.job_id == job.id,
                                                        JobDescriptionVersion.tenant_id == user.tenant_id)
                    .order_by(JobDescriptionVersion.version.desc())).all()
    return [{"id": v.id, "version": v.version, "text": v.text, "source": v.source, "created_at": _dt(v.created_at)}
            for v in vs]


@router.get("/jobs/{job_id}/rubrics")
def list_rubrics(job_id: str, user: User = Depends(require("jobs:read")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    rs_ = db.scalars(select(RubricVersion).where(RubricVersion.job_id == job.id,
                                                 RubricVersion.tenant_id == user.tenant_id)
                     .order_by(RubricVersion.version.desc())).all()
    return [rubric_out(r) for r in rs_]


@router.post("/jobs/{job_id}/rubrics/propose", status_code=201)
def propose(job_id: str, user: User = Depends(require("jobs:write")), db: Session = Depends(get_db)):
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id)
    r = rs.propose_rubric(db, job, user, get_llm_provider())
    db.commit()
    return rubric_out(r)


@router.get("/rubrics/{rubric_id}")
def get_rubric(rubric_id: str, user: User = Depends(require("jobs:read")), db: Session = Depends(get_db)):
    return rubric_out(get_scoped_or_404(db, RubricVersion, rubric_id, user.tenant_id))


@router.put("/rubrics/{rubric_id}")
def update_rubric(rubric_id: str, body: RubricUpdateIn, user: User = Depends(require("jobs:write")),
                  db: Session = Depends(get_db)):
    r = get_scoped_or_404(db, RubricVersion, rubric_id, user.tenant_id)
    rs.update_draft(db, r, [c.model_dump() for c in body.criteria], user)
    db.commit()
    db.refresh(r)
    return rubric_out(r)


@router.post("/rubrics/validate-weights")
def validate_weights_endpoint(body: RubricUpdateIn, user: User = Depends(require("jobs:read"))):
    return {"errors": rs.criteria_errors([c.model_dump() for c in body.criteria]),
            "weight_errors": weight_errors([c.weight for c in body.criteria])}


@router.post("/rubrics/{rubric_id}/approve")
def approve(rubric_id: str, user: User = Depends(require("rubric:approve")), db: Session = Depends(get_db)):
    r = get_scoped_or_404(db, RubricVersion, rubric_id, user.tenant_id)
    queued = rs.approve_rubric(db, r, user)
    db.commit()
    return {"rubric": rubric_out(r), "rescoring_queued": queued}


@router.post("/rubrics/{rubric_id}/new-draft", status_code=201)
def new_draft(rubric_id: str, user: User = Depends(require("jobs:write")), db: Session = Depends(get_db)):
    r = get_scoped_or_404(db, RubricVersion, rubric_id, user.tenant_id)
    d = rs.new_draft_from(db, r, user)
    db.commit()
    return rubric_out(d)
