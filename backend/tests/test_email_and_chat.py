from app.services.email_service import external_recipients, parse_recipients
from tests.conftest import drain, new_key


def _body(scored_job, ids, **kw):
    b = {"job_id": scored_job["job_id"], "application_ids": ids, "to": "hiring.lead@acme.example",
         "cc": "", "subject": "Shortlist", "message": "Please review.", "include_attachments": False,
         "score_min": 98, "score_max": 100}
    b.update(kw)
    return b


def _top_ids(scored_job):
    return [scored_job["ids"]["01_strong_alex_morgan.pdf"], scored_job["ids"]["02_near_boundary_taylor_chen.docx"]]


def test_parse_recipients():
    valid, invalid = parse_recipients("a@acme.example, B@Acme.Example; not-an-email\nc@other.example a@acme.example")
    assert valid == ["a@acme.example", "b@acme.example", "c@other.example"]
    assert invalid == ["not-an-email"]
    assert external_recipients(valid, ["acme.example"]) == ["c@other.example"]


def test_preview_validation(client, scored_job):
    h = scored_job["recruiter"]
    p = client.post("/api/shortlists/preview", json=_body(scored_job, [], to="bad@@x"), headers=h).json()
    assert not p["valid"]
    assert any("Invalid email" in e for e in p["errors"]) and any("Select at least one" in e for e in p["errors"])
    p = client.post("/api/shortlists/preview", json=_body(scored_job, _top_ids(scored_job)), headers=h).json()
    assert p["valid"] and p["candidate_count"] == 2 and p["delivery_mode"] == "secure_links"
    assert "98.7500" in p["rendered_text"] and "/applications/" in p["rendered_text"]
    assert any("MOCK" in w for w in p["warnings"])


def test_send_requires_valid_recipient_and_candidates(client, scored_job):
    h = scored_job["recruiter"]
    r = client.post("/api/shortlists/send", json=_body(scored_job, _top_ids(scored_job), to=""),
                    headers={**h, "Idempotency-Key": new_key()})
    assert r.status_code == 422
    r = client.post("/api/shortlists/send", json=_body(scored_job, []), headers={**h, "Idempotency-Key": new_key()})
    assert r.status_code == 422


def test_external_recipients_require_confirmation(client, scored_job):
    h = scored_job["recruiter"]
    body = _body(scored_job, _top_ids(scored_job), to="agency@outside.example")
    p = client.post("/api/shortlists/preview", json=body, headers=h).json()
    assert p["requires_external_confirmation"] and p["external_recipients"] == ["agency@outside.example"]
    r = client.post("/api/shortlists/send", json=body, headers={**h, "Idempotency-Key": new_key()})
    assert r.status_code == 409
    body["confirm_external_recipients"] = True
    r = client.post("/api/shortlists/send", json=body, headers={**h, "Idempotency-Key": new_key()})
    assert r.status_code == 200


def test_duplicate_send_prevented_by_idempotency_key(client, scored_job):
    h = scored_job["recruiter"]
    key = new_key()
    body = _body(scored_job, _top_ids(scored_job))
    first = client.post("/api/shortlists/send", json=body, headers={**h, "Idempotency-Key": key}).json()
    second = client.post("/api/shortlists/send", json=body, headers={**h, "Idempotency-Key": key}).json()
    assert first["send"]["id"] == second["send"]["id"] and second["duplicate_request"] is True
    drain(respect_schedule=False)
    drain(respect_schedule=False)
    outbox = client.get("/api/outbox", headers=h).json()
    assert len(outbox) == 1 and outbox[0]["to"] == ["hiring.lead@acme.example"]
    s = client.get(f"/api/shortlists/sends/{first['send']['id']}", headers=h).json()
    assert s["status"] == "accepted" and s["delivery_status"] == "unknown"
    assert "not confirmed" in s["status_note"]
    # same key, different content -> conflict, not a silent second send
    changed = _body(scored_job, _top_ids(scored_job), subject="Different")
    assert client.post("/api/shortlists/send", json=changed, headers={**h, "Idempotency-Key": key}).status_code == 409
    assert client.post("/api/shortlists/send", json=body, headers=h).status_code == 422  # missing key header


def test_send_task_retry_never_sends_twice(client, scored_job):
    from app.db import new_session
    from app.models import Task
    from app.services.email_service import handle_send_email

    h = scored_job["recruiter"]
    sid = client.post("/api/shortlists/send", json=_body(scored_job, _top_ids(scored_job)),
                      headers={**h, "Idempotency-Key": new_key()}).json()["send"]["id"]
    drain(respect_schedule=False)
    db = new_session()
    task = db.query(Task).filter(Task.type == "send_email").one()
    handle_send_email(db, task)  # simulate a redelivered task
    db.commit()
    db.close()
    assert len(client.get("/api/outbox", headers=h).json()) == 1
    assert client.get(f"/api/shortlists/sends/{sid}", headers=h).json()["status"] == "accepted"


def test_attachments_blocked_unless_enterprise_allows(client, scored_job):
    h = scored_job["recruiter"]
    p = client.post("/api/shortlists/preview", json=_body(scored_job, _top_ids(scored_job), include_attachments=True),
                    headers=h).json()
    assert not p["valid"] and any("attachments are disabled" in e for e in p["errors"])
    client.put("/api/settings/tenant", json={"allow_resume_attachments": True}, headers=scored_job["admin"])
    p = client.post("/api/shortlists/preview", json=_body(scored_job, _top_ids(scored_job), include_attachments=True),
                    headers=h).json()
    assert p["valid"] and p["delivery_mode"] == "attachments"


def test_hiring_manager_cannot_send(client, scored_job):
    r = client.post("/api/shortlists/send", json=_body(scored_job, _top_ids(scored_job)),
                    headers={**scored_job["manager"], "Idempotency-Key": new_key()})
    assert r.status_code == 403


def test_out_of_range_selection_warns(client, scored_job):
    ids = [scored_job["ids"]["03_just_below_jamie_patel.pdf"]]
    p = client.post("/api/shortlists/preview", json=_body(scored_job, ids), headers=scored_job["recruiter"]).json()
    assert any("outside the active score range" in w for w in p["warnings"])


# ---- chatbot ------------------------------------------------------------------------------------

def _chat(client, h, message, **ctx):
    r = client.post("/api/chat", json={"message": message, "context": ctx}, headers=h)
    assert r.status_code == 200
    return r.json()


def test_chat_filter_uses_backend_and_exact_boundaries(client, scored_job):
    h = scored_job["recruiter"]
    r = _chat(client, h, "Filter candidates between 98 and 100", job_id=scored_job["job_id"])
    assert r["mode"] == "mock-intent-router"
    assert {c["candidate_name"] for c in r["data"]["candidates"]} == {"Alex Morgan", "Taylor Chen"}
    r = _chat(client, h, "Filter candidates between 99 and 99.5", job_id=scored_job["job_id"])
    assert r["data"]["total"] == 0 and "not lowered" in r["reply"]


def test_chat_show_explain_compare(client, scored_job):
    h = scored_job["recruiter"]
    r = _chat(client, h, "Show applications for the AI Engineer opening.")
    assert r["data"]["total"] == 6
    r = _chat(client, h, "Explain why Riley Brooks received this score", job_id=scored_job["job_id"])
    assert "95.0000" in r["reply"] and "not supported" in r["reply"]
    r = _chat(client, h, "Compare these two candidates", job_id=scored_job["job_id"],
              selected_application_ids=_top_ids(scored_job))
    assert "100.0000" in r["reply"] and "98.7500" in r["reply"]


def test_chat_never_invents_or_sends_or_changes_rubric(client, scored_job):
    h = scored_job["recruiter"]
    r = _chat(client, h, "Explain why Zelda Unknown received this score", job_id=scored_job["job_id"])
    assert "couldn't identify" in r["reply"]
    r = _chat(client, h, "Send the shortlist email now", selected_application_ids=_top_ids(scored_job))
    assert "never send" in r["reply"]
    r = _chat(client, h, "Increase the weight of skills to 50")
    assert "can't change" in r["reply"]
    r = _chat(client, h, "Prepare an email with my selected shortlist", selected_application_ids=_top_ids(scored_job))
    assert "Nothing has been sent" in r["reply"]
    assert client.get("/api/outbox", headers=h).json() == []


def test_csv_export_respects_filter_and_guards_formulas(client, scored_job):
    h = scored_job["recruiter"]
    r = client.get(f"/api/jobs/{scored_job['job_id']}/candidates/export.csv",
                   params={"min_score": 98, "max_score": 100}, headers=h)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 3 and "98.7500" in r.text and "97.5000" not in r.text
