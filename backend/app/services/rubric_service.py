"""Job description versions and rubric lifecycle: propose (AI/mock) -> edit draft -> approve.

Approved rubrics are immutable. Changing criteria means creating a new draft version; approving
it supersedes the previous version and rescoring creates new evaluations while old ones are kept.
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import utcnow
from app.llm.base import LLMProvider, parse_term
from app.models import JobDescriptionVersion, JobOpening, RubricCriterion, RubricVersion, User
from app.safety import prohibited_criterion_terms
from app.scoring import SCORING_LOGIC_VERSION, weight_errors
from app.services.pipeline import queue_rescoring

ALLOWED_CATEGORIES = {"skills", "experience", "responsibilities", "projects", "qualifications", "general", "other"}


def latest_description(db: Session, job: JobOpening) -> JobDescriptionVersion | None:
    return db.scalar(
        select(JobDescriptionVersion)
        .where(JobDescriptionVersion.job_id == job.id, JobDescriptionVersion.tenant_id == job.tenant_id)
        .order_by(JobDescriptionVersion.version.desc())
        .limit(1)
    )


def add_description_version(db: Session, job: JobOpening, text: str, user: User, source: str = "pasted") -> JobDescriptionVersion:
    text = text.strip()
    if not text:
        raise HTTPException(422, "Job description cannot be empty.")
    if len(text) > 50_000:
        raise HTTPException(422, "Job description is too long (50,000 characters max).")
    current = db.scalar(select(func.max(JobDescriptionVersion.version)).where(JobDescriptionVersion.job_id == job.id)) or 0
    v = JobDescriptionVersion(tenant_id=job.tenant_id, job_id=job.id, version=current + 1, text=text,
                              source=source, created_by_id=user.id)
    db.add(v)
    audit.record(db, tenant_id=job.tenant_id, user=user, action="job.description_versioned",
                 entity_type="job", entity_id=job.id, details={"version": v.version, "source": source})
    return v


def _next_rubric_version(db: Session, job_id: str) -> int:
    return (db.scalar(select(func.max(RubricVersion.version)).where(RubricVersion.job_id == job_id)) or 0) + 1


def propose_rubric(db: Session, job: JobOpening, user: User, provider: LLMProvider) -> RubricVersion:
    jd = latest_description(db, job)
    if jd is None:
        raise HTTPException(422, "Add a job description before proposing a rubric.")
    proposals = provider.propose_rubric(jd.text)
    rubric = RubricVersion(
        tenant_id=job.tenant_id, job_id=job.id, version=_next_rubric_version(db, job.id),
        job_description_version_id=jd.id, status="draft",
        proposed_by=f"{provider.name}:{provider.model}", model_config_json=provider.config(),
        scoring_logic_version=SCORING_LOGIC_VERSION, created_by_id=user.id,
    )
    for i, p in enumerate(proposals):
        rubric.criteria.append(RubricCriterion(
            position=i, name=p.name, category=p.category, description=p.description,
            weight=p.weight, required=p.required, evidence_terms=p.evidence_terms,
        ))
    db.add(rubric)
    audit.record(db, tenant_id=job.tenant_id, user=user, action="rubric.proposed", entity_type="rubric",
                 entity_id=rubric.id, details={"job_id": job.id, "version": rubric.version,
                                               "provider": provider.name, "is_mock": provider.is_mock})
    return rubric


def criteria_errors(criteria: list[dict]) -> list[str]:
    errors = weight_errors([c.get("weight") for c in criteria])
    for i, c in enumerate(criteria, start=1):
        if not (c.get("name") or "").strip():
            errors.append(f"Criterion {i}: name is required.")
        if c.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"Criterion {i}: unknown category {c.get('category')!r}.")
        terms = [t for t in (c.get("evidence_terms") or []) if t.strip()]
        if not terms or not all(parse_term(t)[1] for t in terms):
            errors.append(f"Criterion {i}: add at least one evidence term.")
        bad = prohibited_criterion_terms(c.get("name", ""), c.get("description", ""), *terms)
        if bad:
            errors.append(
                f"Criterion {i}: references protected characteristics or school prestige ({', '.join(bad)}). "
                "Use job-related evidence only."
            )
    return errors


def update_draft(db: Session, rubric: RubricVersion, criteria: list[dict], user: User) -> RubricVersion:
    if rubric.status != "draft":
        raise HTTPException(409, "Approved or superseded rubrics cannot be edited. Create a new draft version.")
    if not criteria:
        raise HTTPException(422, "A rubric needs at least one criterion.")
    rubric.criteria.clear()
    db.flush()
    for i, c in enumerate(criteria):
        rubric.criteria.append(RubricCriterion(
            position=i, name=c["name"].strip(), category=c["category"], description=c.get("description", ""),
            weight=float(c["weight"]), required=bool(c.get("required")),
            evidence_terms=[t.strip() for t in c.get("evidence_terms", []) if t.strip()],
        ))
    audit.record(db, tenant_id=rubric.tenant_id, user=user, action="rubric.edited", entity_type="rubric",
                 entity_id=rubric.id, details={"criteria_count": len(criteria)})
    return rubric


def criteria_as_dicts(rubric: RubricVersion) -> list[dict]:
    return [
        {"name": c.name, "category": c.category, "description": c.description, "weight": c.weight,
         "required": c.required, "evidence_terms": list(c.evidence_terms)}
        for c in rubric.criteria
    ]


def approve_rubric(db: Session, rubric: RubricVersion, user: User) -> int:
    if rubric.status != "draft":
        raise HTTPException(409, "Only draft rubrics can be approved.")
    errors = criteria_errors(criteria_as_dicts(rubric))
    if errors:
        raise HTTPException(422, {"message": "Rubric is not valid", "errors": errors})
    job = db.get(JobOpening, rubric.job_id)
    previous = db.scalars(select(RubricVersion).where(
        RubricVersion.job_id == job.id, RubricVersion.tenant_id == job.tenant_id, RubricVersion.status == "approved"
    )).all()
    for p in previous:
        p.status = "superseded"
    rubric.status = "approved"
    rubric.approved_by_id = user.id
    rubric.approved_at = utcnow()
    job.active_rubric_version_id = rubric.id
    db.flush()
    queued = queue_rescoring(db, rubric)
    audit.record(db, tenant_id=rubric.tenant_id, user=user, action="rubric.approved", entity_type="rubric",
                 entity_id=rubric.id, details={"job_id": job.id, "version": rubric.version,
                                               "superseded": [p.id for p in previous], "rescoring_queued": queued})
    return queued


def new_draft_from(db: Session, rubric: RubricVersion, user: User) -> RubricVersion:
    job = db.get(JobOpening, rubric.job_id)
    jd = latest_description(db, job)
    draft = RubricVersion(
        tenant_id=rubric.tenant_id, job_id=rubric.job_id, version=_next_rubric_version(db, rubric.job_id),
        job_description_version_id=jd.id if jd else rubric.job_description_version_id, status="draft",
        proposed_by=f"copy-of-v{rubric.version}", model_config_json=rubric.model_config_json,
        scoring_logic_version=SCORING_LOGIC_VERSION, created_by_id=user.id,
    )
    for c in rubric.criteria:
        draft.criteria.append(RubricCriterion(
            position=c.position, name=c.name, category=c.category, description=c.description,
            weight=c.weight, required=c.required, evidence_terms=list(c.evidence_terms),
        ))
    db.add(draft)
    audit.record(db, tenant_id=rubric.tenant_id, user=user, action="rubric.draft_created", entity_type="rubric",
                 entity_id=draft.id, details={"from_version": rubric.version, "version": draft.version})
    return draft
