from tests.conftest import create_job, drain, propose_and_approve


def _scores(client, headers, job_id, **params):
    r = client.get(f"/api/jobs/{job_id}/candidates", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {i["candidate_name"]: i["score"] for i in r.json()["items"]}


def test_demo_scenarios_produce_expected_scores(client, scored_job):
    s = _scores(client, scored_job["recruiter"], scored_job["job_id"])
    assert s == {"Alex Morgan": 100.0, "Taylor Chen": 98.75, "Jamie Patel": 97.5, "Riley Brooks": 95.0,
                 "Casey Nguyen": 47.5, "Morgan Lee": 7.5}


def test_range_filter_is_inclusive_and_never_pads(client, scored_job):
    h, j = scored_job["recruiter"], scored_job["job_id"]
    assert set(_scores(client, h, j, min_score=98, max_score=100)) == {"Alex Morgan", "Taylor Chen"}
    # 97.5 sits exactly on both boundaries
    assert set(_scores(client, h, j, min_score=97.5, max_score=97.5)) == {"Jamie Patel"}
    assert set(_scores(client, h, j, min_score=97.51, max_score=98.75)) == {"Taylor Chen"}
    assert set(_scores(client, h, j, min_score=100, max_score=100)) == {"Alex Morgan"}
    # No qualifying candidate -> empty result, nobody added to fill it
    r = client.get(f"/api/jobs/{j}/candidates", params={"min_score": 99, "max_score": 99.99}, headers=h)
    assert r.json()["items"] == [] and r.json()["total"] == 0


def test_range_filter_validation(client, scored_job):
    h, j = scored_job["recruiter"], scored_job["job_id"]
    for params in ({"min_score": -1, "max_score": 50}, {"min_score": 0, "max_score": 100.01},
                   {"min_score": 90, "max_score": 80}):
        assert client.get(f"/api/jobs/{j}/candidates", params=params, headers=h).status_code == 422


def test_required_status_filter_and_sorting(client, scored_job):
    h, j = scored_job["recruiter"], scored_job["job_id"]
    r = client.get(f"/api/jobs/{j}/candidates", params={"required_status": "not_supported"}, headers=h).json()
    assert {i["candidate_name"] for i in r["items"]} == {"Riley Brooks", "Morgan Lee"}
    asc = client.get(f"/api/jobs/{j}/candidates", params={"order": "asc"}, headers=h).json()["items"]
    assert [i["score"] for i in asc] == sorted(i["score"] for i in asc)


def test_search_and_pagination(client, scored_job):
    h, j = scored_job["recruiter"], scored_job["job_id"]
    r = client.get(f"/api/jobs/{j}/candidates", params={"search": "taylor"}, headers=h).json()
    assert [i["candidate_name"] for i in r["items"]] == ["Taylor Chen"]
    p1 = client.get(f"/api/jobs/{j}/candidates", params={"page": 1, "page_size": 4}, headers=h).json()
    p2 = client.get(f"/api/jobs/{j}/candidates", params={"page": 2, "page_size": 4}, headers=h).json()
    assert p1["total"] == 6 and len(p1["items"]) == 4 and len(p2["items"]) == 2


def test_explainable_breakdown_sums_to_total(client, scored_job):
    h = scored_job["recruiter"]
    app_id = scored_job["ids"]["02_near_boundary_taylor_chen.docx"]
    d = client.get(f"/api/applications/{app_id}", headers=h).json()
    ev = d["current_evaluation"]
    assert ev["is_mock"] is True and ev["model_config"]["provider"] == "mock"
    assert round(sum(a["contribution"] for a in ev["assessments"]), 4) == ev["score"] == 98.75
    assert sum(a["weight"] for a in ev["assessments"]) == 100
    git = next(a for a in ev["assessments"] if a["criterion_name"].startswith("Version control"))
    assert git["level"] == "substantial" and "Automated testing" in git["missing"]
    for a in ev["assessments"]:
        for e in a["evidence"]:
            assert e["section"] and e["quote"]


def test_rubric_weights_must_total_100_before_approval(client, acme):
    h = acme["recruiter"]
    job_id = create_job(client, h)
    rid = client.post(f"/api/jobs/{job_id}/rubrics/propose", headers=h).json()["id"]
    crit = client.get(f"/api/rubrics/{rid}", headers=h).json()["criteria"]
    crit[0]["weight"] = crit[0]["weight"] - 5
    r = client.put(f"/api/rubrics/{rid}", json={"criteria": crit}, headers=h)
    assert r.status_code == 200 and r.json()["validation_errors"]
    assert client.post(f"/api/rubrics/{rid}/approve", headers=h).status_code == 422


def test_rubric_rejects_protected_characteristics_and_prestige(client, acme):
    h = acme["recruiter"]
    job_id = create_job(client, h)
    rid = client.post(f"/api/jobs/{job_id}/rubrics/propose", headers=h).json()["id"]
    crit = client.get(f"/api/rubrics/{rid}", headers=h).json()["criteria"]
    crit[0]["name"] = "Graduated from an Ivy League school"
    crit[1]["evidence_terms"] = ["young|digital native"]
    client.put(f"/api/rubrics/{rid}", json={"criteria": crit}, headers=h)
    r = client.post(f"/api/rubrics/{rid}/approve", headers=h)
    assert r.status_code == 422
    assert "ivy league" in str(r.json()) and "young" in str(r.json())


def test_approved_rubric_is_immutable_and_rescoring_preserves_history(client, scored_job):
    h, j = scored_job["recruiter"], scored_job["job_id"]
    active = client.get(f"/api/jobs/{j}", headers=h).json()["active_rubric"]["id"]
    rub = client.get(f"/api/rubrics/{active}", headers=h).json()
    assert client.put(f"/api/rubrics/{active}", json={"criteria": rub["criteria"]}, headers=h).status_code == 409

    draft = client.post(f"/api/rubrics/{active}/new-draft", headers=h).json()
    crit = draft["criteria"]
    # Make the certification optional and move its weight elsewhere
    cert = next(c for c in crit if c["name"].startswith("Current professional cloud"))
    cert["required"] = False
    assert client.put(f"/api/rubrics/{draft['id']}", json={"criteria": crit}, headers=h).status_code == 200
    assert client.post(f"/api/rubrics/{draft['id']}/approve", headers=h).status_code == 200
    drain(respect_schedule=False)

    assert client.get(f"/api/rubrics/{active}", headers=h).json()["status"] == "superseded"
    app_id = scored_job["ids"]["04_missing_required_riley_brooks.docx"]
    d = client.get(f"/api/applications/{app_id}", headers=h).json()
    assert len(d["evaluation_history"]) == 2
    assert [e["is_current"] for e in d["evaluation_history"]] == [True, False]
    assert d["current_evaluation"]["rubric_version"] == 2
    assert d["current_evaluation"]["required_status"] == "all_supported"   # was not_supported under v1
    assert d["evaluation_history"][1]["required_status"] == "not_supported"


def test_upload_before_rubric_waits_then_scores_on_approval(client, acme):
    from tests.conftest import resume, upload

    h = acme["recruiter"]
    job_id = create_job(client, h)
    res = upload(client, h, job_id, dict([resume("strong")]))
    d = client.get(f"/api/applications/{res[0]['application_id']}", headers=h).json()
    assert d["status"] == "awaiting_rubric" and d["current_evaluation"] is None
    propose_and_approve(client, h, job_id)
    drain(respect_schedule=False)
    d = client.get(f"/api/applications/{res[0]['application_id']}", headers=h).json()
    assert d["status"] == "scored" and d["current_evaluation"]["score"] == 100.0
