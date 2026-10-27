"""Recruitment-mailbox intake (synthetic Initech tenant): .eml import and read-only IMAP sync."""
import imaplib

import pytest

from tests import mailbox_fixtures as mf
from app.ingestion.email_intake import parse_email, pick_resume
from tests.conftest import drain, login, make_tenant, propose_and_approve


@pytest.fixture
def ini(client):
    t = make_tenant("initech", domains=[mf.TENANT_DOMAIN])
    t["admin"] = login(client, t["users"]["admin"])
    t["recruiter"] = login(client, t["users"]["recruiter"])
    t["manager"] = login(client, t["users"]["hiring_manager"])
    t["jobs"] = {}
    for j in mf.JOBS:
        r = client.post("/api/jobs", json={"title": j["title"], "external_ref": j["external_ref"],
                                           "description": j["description"]}, headers=t["recruiter"])
        assert r.status_code == 201
        t["jobs"][j["external_ref"]] = r.json()["id"]
        propose_and_approve(client, t["recruiter"], r.json()["id"])
    return t


def _import(client, headers, emails: dict[str, bytes], job_id=None):
    data = {"job_id": job_id} if job_id else {}
    r = client.post("/api/integrations/mailbox/import-eml", headers=headers, data=data,
                    files=[("files", (n, raw, "message/rfc822")) for n, raw in emails.items()])
    assert r.status_code == 200, r.text
    drain(respect_schedule=False)
    return {x["filename"]: x for x in r.json()["results"]}


def test_parse_email_and_cover_letter_is_not_the_resume():
    p = parse_email(mf.demo_emails()["01_ssd_with_ref.eml"])
    assert p.sender_email == "jordan.avery@example.com" and "INI-SSD-01" in p.subject
    assert [a[0] for a in p.attachments] == ["Jordan_Avery_Resume.pdf", "Jordan_Avery_Cover_Letter.docx"]
    resume, _ = pick_resume(p.attachments)
    assert resume[0] == "Jordan_Avery_Resume.pdf"


def test_eml_import_routes_by_requisition_ref_and_reports_every_outcome(client, ini):
    res = _import(client, ini["recruiter"], mf.demo_emails())
    outcomes = {k: v["outcome"] for k, v in res.items()}
    assert outcomes == {
        "01_ssd_with_ref.eml": "imported",
        "02_ssd_ambiguous_title.eml": "unmapped_job",          # two open jobs share this title
        "03_pml_application.eml": "imported",
        "04_no_attachment.eml": "no_resume_attachment",
        "05_internal_forward.eml": "imported",
    }
    assert res["01_ssd_with_ref.eml"]["job_id"] == ini["jobs"]["INI-SSD-01"]
    assert res["05_internal_forward.eml"]["job_id"] == ini["jobs"]["INI-SSD-02"]
    assert "requisition ref" in res["02_ssd_ambiguous_title.eml"]["detail"]

    apps = client.get(f"/api/jobs/{ini['jobs']['INI-SSD-01']}/candidates", headers=ini["recruiter"]).json()["items"]
    assert len(apps) == 1 and apps[0]["source_system"] == "mailbox_eml" and apps[0]["status"] == "scored"
    assert apps[0]["document_filename"] == "Jordan_Avery_Resume.pdf"


def test_internal_forward_does_not_make_hr_the_candidate(client, ini):
    _import(client, ini["recruiter"], {"f.eml": mf.demo_emails()["05_internal_forward.eml"]})
    items = client.get(f"/api/jobs/{ini['jobs']['INI-SSD-02']}/candidates", headers=ini["recruiter"]).json()["items"]
    assert items[0]["candidate_email"] == "sam.ortega@example.com"   # from the resume, not the internal careers@ forward


def test_reimport_is_idempotent_across_sources(client, ini):
    emails = {"a.eml": mf.demo_emails()["03_pml_application.eml"]}
    _import(client, ini["recruiter"], emails)
    _import(client, ini["recruiter"], emails)
    job = ini["jobs"]["INI-PML-01"]
    assert client.get(f"/api/jobs/{job}/candidates", headers=ini["recruiter"]).json()["total"] == 1
    msgs = client.get("/api/integrations/mailbox/messages", headers=ini["recruiter"]).json()
    assert len(msgs) == 1


def test_assign_job_on_import_resolves_ambiguous_subject(client, ini):
    job = ini["jobs"]["INI-SSD-02"]
    res = _import(client, ini["recruiter"], {"b.eml": mf.demo_emails()["02_ssd_ambiguous_title.eml"]}, job_id=job)
    assert res["b.eml"]["outcome"] == "imported" and res["b.eml"]["job_id"] == job


def test_unmapped_message_can_be_resolved_by_reimporting_with_a_job(client, ini):
    raw = {"b.eml": mf.demo_emails()["02_ssd_ambiguous_title.eml"]}
    assert _import(client, ini["recruiter"], raw)["b.eml"]["outcome"] == "unmapped_job"
    job = ini["jobs"]["INI-SSD-02"]
    res = _import(client, ini["recruiter"], raw, job_id=job)["b.eml"]
    assert res["outcome"] == "imported" and res["job_id"] == job
    msgs = client.get("/api/integrations/mailbox/messages", headers=ini["recruiter"]).json()
    assert len(msgs) == 1 and msgs[0]["outcome"] == "imported"          # same record updated, not duplicated
    # an imported message is never re-imported, even with a different job
    again = _import(client, ini["recruiter"], raw, job_id=ini["jobs"]["INI-SSD-01"])["b.eml"]
    assert again["job_id"] == job
    assert client.get(f"/api/jobs/{ini['jobs']['INI-SSD-01']}/candidates", headers=ini["recruiter"]).json()["total"] == 0


def test_mailbox_import_is_tenant_scoped_and_role_checked(client, ini, acme):
    raw = {"a.eml": mf.demo_emails()["01_ssd_with_ref.eml"]}
    # another tenant cannot target Initech's job, and its import cannot match it either
    r = client.post("/api/integrations/mailbox/import-eml", headers=acme["recruiter"],
                    data={"job_id": ini["jobs"]["INI-SSD-01"]}, files=[("files", ("a.eml", raw["a.eml"]))])
    assert r.status_code == 404
    res = _import(client, acme["recruiter"], raw)
    assert res["a.eml"]["outcome"] == "unmapped_job"
    assert client.get("/api/integrations/mailbox/messages", headers=ini["recruiter"]).json() == []
    # hiring managers cannot import
    r = client.post("/api/integrations/mailbox/import-eml", headers=ini["manager"], files=[("files", ("a.eml", raw["a.eml"]))])
    assert r.status_code == 403


def test_non_eml_and_oversized_rejected(client, ini, monkeypatch):
    from app.config import get_settings

    res = _import(client, ini["recruiter"], {"resume.pdf": b"%PDF-1.4"})
    assert res["resume.pdf"]["outcome"] == "rejected_message"
    monkeypatch.setattr(get_settings(), "max_email_mb", 0)
    res = _import(client, ini["recruiter"], {"big.eml": mf.demo_emails()["01_ssd_with_ref.eml"]})
    assert res["big.eml"]["outcome"] == "rejected_message"


# ---- IMAP -------------------------------------------------------------------------------------

class FakeIMAP:
    """Minimal IMAP server double. Records calls so tests can assert read-only behaviour."""
    messages: dict[bytes, bytes] = {}
    calls: list = []

    def __init__(self, host, port, timeout=None):
        FakeIMAP.calls.append(("connect", host, port))

    def login(self, user, password):
        if password != "app-password":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b""]

    def select(self, folder, readonly=False):
        FakeIMAP.calls.append(("select", folder, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def status(self, folder, what):
        return "OK", [b'"INBOX" (UIDVALIDITY 4242)']

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            FakeIMAP.calls.append(("search", args[-1]))
            return "OK", [b" ".join(self.messages)]
        if cmd == "FETCH":
            FakeIMAP.calls.append(("fetch", args[1]))
            raw = self.messages[args[0]]
            return "OK", [(b"1 (UID 1 BODY[] {%d}" % len(raw), raw), b")"]
        raise AssertionError(f"unexpected IMAP command {cmd}")

    def logout(self):
        return "BYE", [b""]


@pytest.fixture
def fake_imap(monkeypatch):
    from app.config import get_settings
    from app.ingestion import imap_mailbox

    emails = mf.demo_emails()
    FakeIMAP.messages = {b"101": emails["01_ssd_with_ref.eml"], b"102": emails["03_pml_application.eml"],
                         b"103": emails["04_no_attachment.eml"]}
    FakeIMAP.calls = []
    monkeypatch.setattr(imap_mailbox.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(get_settings(), "mailbox_imap_password", "app-password")
    return FakeIMAP


IMAP_CFG = {"enabled": True, "host": "imap.example.com", "port": 993, "username": mf.RECRUITMENT_MAILBOX,
            "folder": "INBOX", "since_days": 30}


def test_imap_sync_is_read_only_and_idempotent(client, ini, fake_imap):
    assert client.put("/api/integrations/imap", json=IMAP_CFG, headers=ini["recruiter"]).status_code == 403
    cfg = client.put("/api/integrations/imap", json=IMAP_CFG, headers=ini["admin"]).json()
    assert cfg["password_configured_on_server"] is True and cfg["tested_against_real_mailbox"] is False
    assert "password" not in str(cfg["settings"]).lower()

    assert client.post("/api/integrations/imap/sync", headers=ini["recruiter"]).json() == {"queued": True}
    drain(respect_schedule=False)
    assert ("select", '"INBOX"', True) in fake_imap.calls                    # EXAMINE / read-only
    assert all(c[1] == "(BODY.PEEK[])" for c in fake_imap.calls if c[0] == "fetch")  # never sets \\Seen
    status = client.get("/api/integrations/imap", headers=ini["recruiter"]).json()
    assert status["last_result"] == {"messages_seen": 3, "imported": 2, "no_resume_attachment": 1}

    client.post("/api/integrations/imap/sync", headers=ini["recruiter"])
    drain(respect_schedule=False)
    total = sum(client.get(f"/api/jobs/{j}/candidates", headers=ini["recruiter"]).json()["total"] for j in ini["jobs"].values())
    assert total == 2
    assert len(client.get("/api/integrations/mailbox/messages", headers=ini["recruiter"]).json()) == 3


def test_imap_same_message_already_imported_from_eml_is_not_duplicated(client, ini, fake_imap):
    _import(client, ini["recruiter"], {"a.eml": mf.demo_emails()["01_ssd_with_ref.eml"]})
    client.put("/api/integrations/imap", json=IMAP_CFG, headers=ini["admin"])
    client.post("/api/integrations/imap/sync", headers=ini["recruiter"])
    drain(respect_schedule=False)
    msgs = client.get("/api/integrations/mailbox/messages", headers=ini["recruiter"]).json()
    assert sorted(m["outcome"] for m in msgs) == ["duplicate_message", "imported", "imported", "no_resume_attachment"]
    assert client.get(f"/api/jobs/{ini['jobs']['INI-SSD-01']}/candidates", headers=ini["recruiter"]).json()["total"] == 1


def test_imap_bad_credentials_fail_permanently_without_retry(client, ini, fake_imap, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "mailbox_imap_password", "wrong")
    client.put("/api/integrations/imap", json=IMAP_CFG, headers=ini["admin"])
    client.post("/api/integrations/imap/sync", headers=ini["recruiter"])
    drain(respect_schedule=False)
    st = client.get("/api/integrations/imap", headers=ini["recruiter"]).json()
    assert st["status"] == "error" and "login was rejected" in st["last_result"]["error"]
    assert sum(1 for c in fake_imap.calls if c[0] == "connect") == 1


def test_imap_sync_refused_without_server_secret(client, ini, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "mailbox_imap_password", "")
    client.put("/api/integrations/imap", json=IMAP_CFG, headers=ini["admin"])
    r = client.post("/api/integrations/imap/sync", headers=ini["recruiter"])
    assert r.status_code == 409 and "MAILBOX_IMAP_PASSWORD" in r.json()["detail"]


def test_imap_config_rejects_injection_in_folder(client, ini):
    bad = {**IMAP_CFG, "folder": 'INBOX" (DELETE'}
    assert client.put("/api/integrations/imap", json=bad, headers=ini["admin"]).status_code == 422
