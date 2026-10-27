# Status: implemented vs mocked vs remaining

**TalentMatch AI is not production-ready.** Milestone 1 is a working local demo. Real integrations,
security hardening, scoring validation and operational behavior have not been validated.

## Implemented and tested (milestone 1)

| Area | What works | Evidence |
|---|---|---|
| Sign-in & roles | Local email/password, JWT, admin / recruiter / hiring-manager permissions | `tests/test_security.py` |
| Tenant isolation | Tenant filter on every query, 404 across tenants, tenant-checked tasks and storage (incl. `../` traversal) | `test_tenant_cannot_see_*`, `test_storage_rejects_cross_tenant_keys` |
| Jobs | Create, edit, paste/upload JD, JD versioning | `test_rubric_and_filtering.py` |
| Rubric workflow | Propose → edit draft → approve; weights must total exactly 100; approved versions immutable; new version → rescoring with history kept; protected-characteristic/prestige criteria rejected | `test_rubric_*`, `test_approved_rubric_is_immutable_*` |
| Manual upload | PDF/DOCX, extension + magic-byte + size + zip-bomb checks, per-file rejection messages | `test_invalid_files_rejected_per_file`, `test_oversized_file_rejected` |
| Parsing | PDF (pypdf) and DOCX (python-docx) into page/section/line segments; extraction confidence | `test_ingestion.py` |
| Manual review routing | Corrupt, encrypted, scanned/image-only or near-empty documents → `needs_manual_review`, no score | `test_unreadable_and_scanned_*` |
| Duplicates | Identical file → `duplicate` linked to original; same candidate with different file → `possible_duplicate` flag; connector re-sync is idempotent | `test_duplicate_*`, `test_mock_ats_sync_*` |
| Background work & retries | DB task queue, atomic claim, exponential backoff, permanent vs transient failures, failure hooks | `test_mock_ats_sync_with_retry_*` |
| Scoring | Deterministic Decimal weighted levels, exact integer storage, inclusive range bounds | `test_scoring.py` |
| Explainability | Per-criterion weight, level, verified evidence quotes with page/section, missing/ambiguous info, contribution; breakdown sums to total | `test_explainable_breakdown_sums_to_total` |
| Required criteria | supported / needs clarification / not supported, separate filter | `test_required_status_filter_and_sorting` |
| Prompt-injection handling | Detection, exclusion from model input (incl. wrapped lines), flag + excerpt for review, prompt data-block isolation, output grounding (fabricated quotes discarded, invalid levels rejected) | `test_injected_*`, `test_ungrounded_*`, `test_prompt_builder_*` |
| Fairness controls | Header/personal sections excluded; identifiers and protected-characteristic terms redacted; same evidence with different name/age scores identically | `test_redaction_*`, `test_mock_scoring_ignores_names_*` |
| Results UI/API | Inclusive range filter, required-status filter, search, sort, pagination, CSV export (formula-safe), precision-safe score display | `test_range_filter_*`, `test_csv_export_*` |
| Shortlist email | Recipient validation, external-domain warning + explicit confirmation, attachment policy, preview, idempotent send, retry-safe worker, acceptance ≠ delivery | `test_email_and_chat.py` |
| Chat assistant | Show / filter / explain / compare / prepare-draft over tenant-scoped read-only tools; refuses to send or edit rubrics; never invents candidates | `test_chat_*` |
| Audit | Logins, job/rubric/application events, document downloads, exports, sends, settings, retention, chat usage; no resume text | `test_audit_log_never_contains_resume_text` |
| Recruitment mailbox intake | `.eml` import + read-only IMAP sync; resume selection (skips cover letters); job routing by requisition ref / unique title; Message-ID + UID dedupe across sources; internal forwards don't become the candidate; per-message outcome log | `tests/test_mailbox.py` (IMAP against a **simulated** server only) |
| Retention | Tenant retention period, admin-run purge, per-application deletion with file removal | API + UI (not covered by an automated test yet) |

The full test suite (66 tests) passes locally. The frontend type-checks and builds. The full milestone flow was
run against live API + Vite servers through the dev proxy. The UI has **not** been tested in an automated browser.

## Mocked (clearly labelled in API and UI)

| Component | Mock | Notes |
|---|---|---|
| LLM extraction & assessment | `MockLLMProvider` — deterministic keyword matching against rubric evidence terms | Every evaluation stores `is_mock: true`; UI shows MOCK badges and a demo banner. **Not AI evaluation.** |
| Rubric proposal | Mock vocabulary-based section parser | Labelled "mock proposal"; recruiter must review. |
| Chat assistant | Rule-based intent router (`mode: mock-intent-router`) | Same tools a real LLM tool-calling loop would use. |
| Email | `MockOutboxProvider` writes to the `mock_outbox` table | Nothing leaves the machine. |
| ATS | `MockATSAdapter` over JSON fixtures | Includes a transient failure (retried) and a missing file (permanent failure). |

## Not implemented — production work remaining

**Integrations (blocked on enterprise decisions, see questions below)**
- Real LLM provider adapter(s) using `app/llm/prompts.py`, structured output, timeouts, cost limits, data-processing agreement.
- ATS connector (API polling and/or signed webhooks), job/requisition mapping, candidate consent flags.
- Recruitment mailbox: test the IMAP connector against a real, authorized mailbox; Gmail API / Microsoft Graph with OAuth 2.0; DKIM/SPF sender verification; scheduled (not just manual) sync.
- CSV import of application records.
- Production email provider, bounce/delivery webhooks to set `delivery_status`.
- OCR for scanned resumes (currently routed to manual review).

**Security & compliance**
- Enterprise SSO (OIDC/SAML), MFA, session revocation, refresh tokens; user/role administration UI.
- Database row-level security (PostgreSQL RLS) as defence in depth for tenant isolation.
- Object storage with server-side encryption and per-tenant keys; malware scanning of uploads; sandboxed parsing.
- Secrets manager integration (Key Vault / Secrets Manager); key rotation.
- Rate limiting, CSRF review if moving to cookies, security headers, dependency scanning, penetration test.
- Legal review of retention, candidate data-subject requests (access/erasure), consent, regional data residency.
- Outbox retention (mock outbox bodies currently not purged by retention).

**Scoring validity**
- Evaluate real-LLM assessments against recruiter-labelled data; measure consistency (repeat runs), calibration
  of levels, and adverse-impact analysis across groups before any production use.
- Human review workflow for flagged applications; recruiter override with reason (audited).
- Better section detection for unusual layouts; multi-column PDFs.

**Operations**
- Alembic migrations, PostgreSQL in CI, the docker-compose stack has not been run.
- Dedicated queue (e.g. Redis/RQ, Celery, or cloud queue) if load requires; dead-letter handling UI.
- Structured logging with PII scrubbing, metrics, tracing, alerting; backups and restore drills.
- Frontend end-to-end tests (Playwright) and accessibility audit.

## Phased plan

| Phase | Scope | Exit criteria |
|---|---|---|
| **1 (this milestone)** | End-to-end demo on mocks: job → rubric approval → upload → parse → explainable score → range filter → shortlist preview → mock send; tenant isolation, roles, audit, tests | Demo runs locally; test suite green |
| 2 | Real LLM provider behind the existing interface; evaluation harness against recruiter-labelled resumes; consistency and adverse-impact checks; recruiter override with reason | Agreement and stability metrics reviewed and accepted by HR/legal |
| 3 | Enterprise SSO, PostgreSQL + Alembic + RLS, object storage with encryption, malware scanning, secrets manager, run docker-compose in CI | Security review passed |
| 4 | Chosen ATS connector (webhooks/polling), mailbox ingestion, CSV import, OCR for scanned resumes | Sandbox integration tests pass against the real provider |
| 5 | Production email provider with delivery webhooks, observability, backups, retention/DSR workflows, load testing, pilot with one recruiting team | Pilot sign-off; operational runbooks |

## Questions for the enterprise (needed before building real connectors)

1. **ATS**: Which system (e.g. Workday, Greenhouse, Lever, SAP SuccessFactors, iCIMS, other) and API edition? Do you have a sandbox tenant and API credentials? Webhooks available, or polling only? How are requisition IDs exposed?
2. **Mailbox**: Microsoft 365 or Google Workspace? Which mailbox, and may we use an app registration / service account with read-only, mailbox-scoped access?
3. **Email sending**: Microsoft Graph, Amazon SES, SendGrid, or an internal SMTP relay? Which sender identity and domains are approved?
4. **LLM**: Which provider and region are approved for candidate data (e.g. Azure OpenAI, Amazon Bedrock, Anthropic API, self-hosted)? Is zero-retention required?
5. **Identity**: Which IdP (Entra ID, Okta, Google) and protocol (OIDC or SAML)? How do groups map to admin/recruiter/hiring-manager?
6. **Policy**: Retention period, regions, whether resume attachments may ever be emailed, and which domains count as internal.
7. **Hosting**: Target cloud and whether a managed PostgreSQL and object store are available.
