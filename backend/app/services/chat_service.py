"""Recruiter assistant.

Demo mode uses a deterministic intent router (NOT an LLM) over the same tenant-scoped tools a
real LLM tool-calling loop would use. The tools are read-only: there is no tool that changes a
rubric or sends email. Everything returned comes from the database; nothing is invented.
"""
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import Application, Candidate, Evaluation, JobOpening, User
from app.scoring import from_e4
from app.services.candidate_query import CandidateFilter, candidate_row, query_candidates

MODE = "mock-intent-router"


# ---- tools (all tenant scoped) ---------------------------------------------------------------

def tool_find_job(db: Session, user: User, text: str | None, job_id: str | None) -> JobOpening | None:
    jobs = db.scalars(select(JobOpening).where(JobOpening.tenant_id == user.tenant_id)).all()
    if text:
        t = text.lower()
        best, best_score = None, 0.0
        for j in jobs:
            title = j.title.lower()
            score = 1.0 if title in t or t in title else SequenceMatcher(None, title, t).ratio()
            if score > best_score:
                best, best_score = j, score
        if best is not None and best_score >= 0.6:
            return best
    if job_id:
        return next((j for j in jobs if j.id == job_id), None)
    return None


def tool_filter(db: Session, user: User, job: JobOpening, lo: float | None, hi: float | None, limit: int = 10):
    rows, total = query_candidates(db, user.tenant_id, job, CandidateFilter(min_score=lo, max_score=hi, page_size=limit))
    return [candidate_row(a, ev, job) for a, ev in rows], total


def tool_get_application(db: Session, user: User, application_id: str) -> tuple[Application, Evaluation | None] | None:
    app = db.get(Application, application_id)
    if app is None or app.tenant_id != user.tenant_id:
        return None
    ev = db.scalar(select(Evaluation).where(Evaluation.application_id == app.id, Evaluation.is_current.is_(True)))
    return app, ev


def tool_find_application_by_name(db: Session, user: User, job: JobOpening | None, text: str) -> list[Application]:
    q = select(Application).join(Candidate, Candidate.id == Application.candidate_id).where(
        Application.tenant_id == user.tenant_id)
    if job:
        q = q.where(Application.job_id == job.id)
    t = text.lower()
    return [a for a in db.scalars(q).all() if a.candidate and a.candidate.full_name
            and (a.candidate.full_name.lower() in t or a.candidate.full_name.split()[0].lower() in t.split())]


# ---- intent router ---------------------------------------------------------------------------

def _reply(text: str, **kw) -> dict:
    return {"reply": text, "mode": MODE, "data": kw.get("data"), "actions": kw.get("actions", [])}


def _explain(app: Application, ev: Evaluation | None) -> str:
    name = app.candidate.full_name if app.candidate else "This candidate"
    if ev is None:
        return f"{name} has no score yet (status: {app.status}). {app.status_detail or ''}".strip()
    lines = [f"{name}: alignment score {ev.score_e4 / 10000:.4f} / 100 against the approved rubric"
             f"{' (DEMO MOCK scoring, not AI evaluation)' if ev.is_mock else ''}.",
             f"Required criteria: {ev.required_status.replace('_', ' ')}."]
    for a in ev.assessments:
        lines.append(f"- {a.criterion_name} (weight {a.weight:g}%): level '{a.level}' -> "
                     f"{a.contribution_e4 / 10000:.2f} points.")
        if a.evidence:
            e = a.evidence[0]
            loc = f"page {e['page']}" if e.get("page") else "document"
            lines.append(f"    Evidence ({loc}, {e.get('section')}): \"{e['quote'][:140]}\"")
        if a.missing:
            lines.append(f"    Not found in resume: {', '.join(a.missing)} (may still exist; verify with candidate).")
    if app.flags:
        lines.append(f"Flags for recruiter review: {', '.join(app.flags)}.")
    return "\n".join(lines)


def handle_message(db: Session, user: User, message: str, context: dict) -> dict:
    msg = (message or "").strip()
    low = msg.lower()
    ctx_job_id = context.get("job_id")
    selected = [s for s in context.get("selected_application_ids", []) if isinstance(s, str)]
    audit.record(db, tenant_id=user.tenant_id, user=user, action="chat.query", entity_type="chat",
                 details={"intent_text_length": len(msg)})

    if not msg:
        return _reply("Ask me about applications, score filters, score explanations, comparisons or the shortlist email.")

    if re.search(r"\b(change|update|edit|modify|increase|decrease|set)\b.*\b(rubric|weight|criteri|score)", low):
        return _reply("I can't change rubrics or scores. Rubric changes must be made in the Rubric editor and "
                      "approved by a recruiter; approval creates a new version and rescoring keeps previous results.")

    if re.search(r"\b(send)\b", low) and "email" in low or "shortlist" in low and "send" in low:
        return _reply("I never send email. Open the Shortlist page, review the preview and click "
                      "\"Send Shortlist\" yourself.", actions=[{"type": "navigate", "to": "/shortlist"}])

    # Filter candidates between X and Y
    nums = re.findall(r"\d+(?:\.\d+)?", low)
    if re.search(r"\b(filter|between|range|score[sd]? (of|from|above|over))\b", low) and len(nums) >= 2:
        lo, hi = float(nums[0]), float(nums[1])
        job = tool_find_job(db, user, msg, ctx_job_id)
        if job is None:
            return _reply("Which job opening? Select a job first or name it, e.g. \"for the AI Engineer opening\".")
        if not (0 <= lo <= 100 and 0 <= hi <= 100) or lo > hi:
            return _reply("Scores must be between 0 and 100 and the minimum cannot exceed the maximum.")
        rows, total = tool_filter(db, user, job, lo, hi)
        if total == 0:
            text = (f"No candidates for {job.title} have an alignment score between {lo:g} and {hi:g} (inclusive). "
                    "I have not lowered the threshold or added other candidates.")
        else:
            text = f"{total} candidate(s) for {job.title} scored between {lo:g} and {hi:g} (inclusive):\n" + "\n".join(
                f"- {r['candidate_name']}: {r['score_exact']} (required: {r['required_status']})" for r in rows)
        return _reply(text, data={"candidates": rows, "total": total},
                      actions=[{"type": "set_filter", "job_id": job.id, "min_score": lo, "max_score": hi}])

    if re.search(r"\b(compare)\b", low):
        job = tool_find_job(db, user, None, ctx_job_id)
        apps = [a for a in tool_find_application_by_name(db, user, job, msg)][:2]
        if len(apps) < 2:
            loaded = [tool_get_application(db, user, s) for s in selected[:2]]
            apps = [x[0] for x in loaded if x]
        if len(apps) != 2:
            return _reply("Select exactly two candidates in the results table (or name them) and ask again.")
        parts = []
        evs = [tool_get_application(db, user, a.id)[1] for a in apps]
        names = [a.candidate.full_name if a.candidate else a.id for a in apps]
        if any(e is None for e in evs):
            return _reply("Both candidates must be scored before they can be compared.")
        if evs[0].rubric_version_id != evs[1].rubric_version_id:
            return _reply("These candidates were scored with different rubric versions; rescore before comparing.")
        parts.append(f"Comparison using the approved rubric{' (DEMO MOCK scoring)' if evs[0].is_mock else ''}:")
        parts.append(f"Total: {names[0]} {evs[0].score_e4 / 10000:.4f} vs {names[1]} {evs[1].score_e4 / 10000:.4f}")
        for a0, a1 in zip(evs[0].assessments, evs[1].assessments):
            parts.append(f"- {a0.criterion_name} ({a0.weight:g}%): {names[0]} '{a0.level}' "
                         f"({a0.contribution_e4 / 10000:.2f}) vs {names[1]} '{a1.level}' ({a1.contribution_e4 / 10000:.2f})")
        parts.append(f"Required criteria: {names[0]} {evs[0].required_status}; {names[1]} {evs[1].required_status}.")
        return _reply("\n".join(parts))

    if re.search(r"\b(explain|why)\b", low):
        job = tool_find_job(db, user, None, ctx_job_id)
        apps = tool_find_application_by_name(db, user, job, msg)
        if not apps and selected:
            got = tool_get_application(db, user, selected[0])
            apps = [got[0]] if got else []
        if not apps and context.get("application_id"):
            got = tool_get_application(db, user, context["application_id"])
            apps = [got[0]] if got else []
        if not apps:
            return _reply("I couldn't identify that candidate in your organization's applications. "
                          "Select a candidate or use their name exactly as shown in the results.")
        app, ev = tool_get_application(db, user, apps[0].id)
        return _reply(_explain(app, ev), actions=[{"type": "navigate", "to": f"/applications/{app.id}"}])

    if re.search(r"\b(email|draft|prepare)\b", low):
        if not selected:
            return _reply("Select candidates in the results table first; I'll then prefill the shortlist email draft. "
                          "Nothing is sent until you click \"Send Shortlist\".")
        return _reply(f"I've prepared a draft with {len(selected)} selected candidate(s). Review the recipients, "
                      "message and preview on the Shortlist page. Nothing has been sent.",
                      actions=[{"type": "navigate", "to": "/shortlist"},
                               {"type": "prefill_email", "subject": "Candidate shortlist for review",
                                "message": "Hello,\n\nPlease review the following shortlisted candidates."}])

    if re.search(r"\b(show|list|applications|candidates|opening)\b", low):
        job = tool_find_job(db, user, msg, None) or tool_find_job(db, user, None, ctx_job_id)
        if job is None:
            jobs = db.scalars(select(JobOpening).where(JobOpening.tenant_id == user.tenant_id)).all()
            return _reply("Which opening? Available: " + ", ".join(j.title for j in jobs) if jobs else "No job openings yet.")
        rows, total = tool_filter(db, user, job, None, None)
        text = f"{total} application(s) for {job.title}" + (":" if rows else ".")
        for r in rows:
            score = r["score_exact"] or "not scored"
            text += f"\n- {r['candidate_name']}: {score} ({r['status'].replace('_', ' ')})"
        return _reply(text, data={"candidates": rows, "total": total},
                      actions=[{"type": "navigate", "to": f"/jobs/{job.id}/results"}])

    return _reply("I can help with: \"Show applications for the AI Engineer opening\", \"Filter candidates between "
                  "98 and 100\", \"Explain why <name> received this score\", \"Compare these two candidates\", "
                  "\"Prepare an email with my selected shortlist\".")
