from app.demo.resumes import make_corrupt_pdf, make_image_only_pdf
from app.parsing import parse_document
from tests.conftest import create_job, drain, propose_and_approve, resume, upload


def _detail(client, h, app_id):
    return client.get(f"/api/applications/{app_id}", headers=h).json()


def test_unreadable_and_scanned_documents_go_to_manual_review_not_low_score(client, acme):
    h = acme["recruiter"]
    job_id = create_job(client, h)
    propose_and_approve(client, h, job_id)
    res = upload(client, h, job_id, {"corrupt.pdf": make_corrupt_pdf(), "scan.pdf": make_image_only_pdf()})
    for r in res:
        d = _detail(client, h, r["application_id"])
        assert d["status"] == "needs_manual_review"
        assert d["current_evaluation"] is None          # no misleading score
        assert d["document"]["parse_status"] in ("failed", "needs_review")
    # ...and they never appear in a score-range filter
    items = client.get(f"/api/jobs/{job_id}/candidates", params={"min_score": 0, "max_score": 100}, headers=h).json()
    assert items["total"] == 0
    # ...but recruiters still see every application
    assert client.get(f"/api/jobs/{job_id}/candidates", headers=h).json()["total"] == 2


def test_scanned_pdf_reports_ocr_note():
    r = parse_document(make_image_only_pdf(), ".pdf")
    assert r.status == "needs_review" and r.confidence == "none"
    assert any("OCR" in n for n in r.notes)


def test_invalid_files_rejected_per_file(client, acme):
    h = acme["recruiter"]
    job_id = create_job(client, h)
    name, data = resume("strong")
    res = upload(client, h, job_id, {
        "notes.txt": b"hello", "fake.pdf": b"MZ\x90\x00 not a pdf", "empty.docx": b"", name: data,
    })
    by = {r["filename"]: r for r in res}
    assert not by["notes.txt"]["accepted"] and "Unsupported" in by["notes.txt"]["error"]
    assert not by["fake.pdf"]["accepted"] and "not a PDF" in by["fake.pdf"]["error"]
    assert not by["empty.docx"]["accepted"]
    assert by[name]["accepted"]


def test_oversized_file_rejected(client, acme, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    h = acme["recruiter"]
    job_id = create_job(client, h)
    res = upload(client, h, job_id, {"big.pdf": b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)})
    assert not res[0]["accepted"] and "limit" in res[0]["error"]


def test_duplicate_file_is_linked_not_rescored(client, acme):
    h = acme["recruiter"]
    job_id = create_job(client, h)
    propose_and_approve(client, h, job_id)
    name, data = resume("strong")
    first = upload(client, h, job_id, {name: data})[0]
    second = upload(client, h, job_id, {"copy.pdf": data})[0]
    assert second["duplicate"] is True
    d = _detail(client, h, second["application_id"])
    assert d["status"] == "duplicate" and d["duplicate_of_id"] == first["application_id"]
    assert d["current_evaluation"] is None


def test_same_candidate_different_file_flagged_possible_duplicate(client, acme):
    from app.demo.resumes import RESUMES, render

    h = acme["recruiter"]
    job_id = create_job(client, h)
    propose_and_approve(client, h, job_id)
    _, fmt, lines = RESUMES["strong"]
    upload(client, h, job_id, {"a.pdf": render(fmt, lines)})
    res = upload(client, h, job_id, {"b.pdf": render(fmt, lines + ["Additional line"])})
    d = _detail(client, h, res[0]["application_id"])
    assert "possible_duplicate" in d["flags"] and d["status"] == "scored"


def test_mock_ats_sync_with_retry_permanent_failure_and_idempotency(client, acme):
    from app.seed import write_demo_files

    write_demo_files()
    h = acme["recruiter"]
    job_id = create_job(client, h)
    propose_and_approve(client, h, job_id)
    # connector must be enabled for the tenant
    assert client.post("/api/integrations/mock-ats/sync", headers=h).status_code == 409
    from app.db import new_session
    from app.models import IntegrationConfig

    db = new_session()
    db.add(IntegrationConfig(tenant_id=acme["tenant_id"], kind="mock_ats", name="Mock ATS", enabled=True))
    db.commit()
    db.close()

    r = client.post("/api/integrations/mock-ats/sync", headers=h).json()
    assert r == {"records_found": 3, "queued": 3, "skipped_existing": 0}
    drain(respect_schedule=False)
    status = client.get(f"/api/jobs/{job_id}/ingestion", headers=h).json()
    apps = {a["external_application_id"]: a for a in status["applications"]}
    assert set(apps) == {"MATS-APP-1001", "MATS-APP-1002"}          # 1002 succeeded on retry
    assert all(a["source_system"] == "mock_ats" for a in apps.values())
    failed = [t for t in status["connector_tasks"] if t["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["record_id"] == "MATS-APP-1003" and "missing" in failed[0]["last_error"]

    again = client.post("/api/integrations/mock-ats/sync", headers=h).json()
    assert again["skipped_existing"] == 2 and again["queued"] == 1      # only the failed one is retried
