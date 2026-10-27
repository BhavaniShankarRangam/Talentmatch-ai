# TalentMatch AI — API reference (Milestone 1)

Base path: `/api`. Interactive OpenAPI docs: http://127.0.0.1:8000/docs when the API is running.

All endpoints except `POST /auth/login` and `GET /health` require `Authorization: Bearer <token>`.
Every resource is scoped to the caller's tenant; IDs from another tenant return **404**.
Permission failures return **403**. Validation failures return **422** with `{"detail": {"message", "errors": [...]}}`.

Roles: **A** = admin, **R** = recruiter, **H** = hiring manager.

## Auth
| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/auth/login` | — | `{email, password}` → `{access_token, user}` |
| GET | `/auth/me` | A R H | current user, tenant, permissions |
| GET | `/health` | — | `{status, demo_mode, llm_provider, email_provider, mock_services}` |

## Jobs, descriptions, rubrics
| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/jobs` | A R H | list with application counts and active rubric |
| POST | `/jobs` | A R | `{title, department?, location?, external_ref?, description?}` |
| GET / PATCH | `/jobs/{id}` | A R H / A R | patch title, status, etc. |
| PUT | `/jobs/{id}/description` | A R | `{text}` → creates a new JD version |
| POST | `/jobs/{id}/description/upload` | A R | multipart `file` (PDF/DOCX/TXT) → new JD version |
| GET | `/jobs/{id}/description/versions` | A R H | all versions |
| GET | `/jobs/{id}/rubrics` | A R H | all rubric versions (newest first) |
| POST | `/jobs/{id}/rubrics/propose` | A R | provider proposes criteria → **draft** (not used for scoring) |
| GET | `/rubrics/{id}` | A R H | includes `weight_total`, `validation_errors` |
| PUT | `/rubrics/{id}` | A R | replace criteria of a **draft**; approved → 409 |
| POST | `/rubrics/{id}/approve` | A R | validates (weights = 100, terms present, no protected/prestige criteria), supersedes previous, queues (re)scoring |
| POST | `/rubrics/{id}/new-draft` | A R | copy into a new editable version |
| POST | `/rubrics/validate-weights` | A R H | dry-run validation |

Criterion shape: `{name, category, description, weight, required, evidence_terms: ["Label: alt1|alt2", ...]}`.
Categories: `skills, experience, responsibilities, projects, qualifications, general, other`.

## Applications & candidates
| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/jobs/{id}/applications/upload` | A R | multipart `files` (≤50, PDF/DOCX, ≤10 MB each). Per-file result `{accepted, error?, duplicate?, application_id}` |
| GET | `/jobs/{id}/ingestion` | A R H | processing status of every application + connector tasks |
| GET | `/jobs/{id}/candidates` | A R H | query: `min_score, max_score` (inclusive, exact; both 0–100, min ≤ max), `required_status` (`all_supported`/`needs_clarification`/`not_supported`/`none_required`), `search`, `status`, `sort=score\|name\|submitted_at`, `order`, `page`, `page_size` (≤200). Range filters exclude unscored applications. |
| GET | `/jobs/{id}/candidates/export.csv` | A R H | same filters, all rows, formula-injection safe |
| GET | `/applications/{id}` | A R H | full detail: document/parse info, flags, current evaluation with per-criterion breakdown, evaluation history |
| POST | `/applications/{id}/reprocess` | A R | re-parse and re-score |
| POST | `/jobs/{id}/rescore` | A R | rescore all scored applications with the active rubric |
| DELETE | `/applications/{id}` | A | deletes application, document file and evaluations (audited) |
| GET | `/documents/{id}/download` | A R H | original file; `Cache-Control: private, no-store`; audited |

Candidate row fields: `candidate_name, job_title, score, score_exact ("98.7500"), required_status, supported_skills, missing_or_unclear, extraction_confidence, status, flags, is_mock, document_id, ...`

## Shortlist & email
| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/shortlists/preview` | A R | body below → `{valid, errors, warnings, requires_external_confirmation, to, cc, candidates, rendered_text, delivery_mode, ...}` |
| POST | `/shortlists/send` | A R | same body + header **`Idempotency-Key`** (8–100 chars). Same key + same content → original send (`duplicate_request: true`); same key + different content → 409; external recipients without `confirm_external_recipients: true` → 409 |
| GET | `/shortlists/sends` / `/shortlists/sends/{id}` | A R | status `queued → sending → accepted / failed`; `delivery_status` stays `unknown` (acceptance ≠ delivery) |
| GET | `/outbox` | A R | MOCK outbox messages |

Body: `{job_id, application_ids[], to, cc?, subject, message, include_attachments, score_min?, score_max?, confirm_external_recipients?}` (`to`/`cc` accept a string separated by commas/semicolons/whitespace, or an array).

## Integrations, settings, audit, chat
| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/integrations` | A R | catalogue with honest implementation status + runtime providers |
| POST | `/integrations/mock-ats/sync` | A R | MOCK ATS: queues one retryable ingest task per new record |
| POST | `/integrations/mailbox/import-eml` | A R | multipart `files` (≤100 `.eml`, ≤`MAX_EMAIL_MB` each), optional form field `job_id`. Per message: `outcome` = `imported` / `duplicate_message` / `no_resume_attachment` / `unmapped_job` / `rejected_file` / `rejected_message` |
| GET | `/integrations/mailbox/messages` | A R | processed mailbox messages (any source) with outcome, routed job and application links |
| GET | `/integrations/imap` | A R | IMAP config (non-secret), status, last result, `password_configured_on_server`, `tested_against_real_mailbox: false` |
| PUT | `/integrations/imap` | A | `{enabled, host, port, username, folder, since_days}`. The password is never accepted here (server env `MAILBOX_IMAP_PASSWORD`). |
| POST | `/integrations/imap/sync` | A R | queues a read-only sync; 409 if not enabled or the server secret is missing |
| GET / PUT | `/settings/tenant` | A R / A | allowed email domains, resume attachment policy, retention days (30–3650) |
| POST | `/admin/retention/run` | A | delete applications older than retention period |
| GET | `/audit` | A | `page, page_size, action` (prefix filter) |
| POST | `/chat` | A R H | `{message, context: {job_id?, application_id?, selected_application_ids?}}` → `{reply, mode: "mock-intent-router", data, actions}`. Actions are UI hints only (`navigate`, `set_filter`, `prefill_email`); the assistant has no send or rubric-edit tools. |
