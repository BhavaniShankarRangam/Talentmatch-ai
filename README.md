# TalentMatch AI

An enterprise recruitment assistant. It collects resumes for a job opening, extracts evidence, compares each
resume against a **recruiter-approved rubric**, and calculates an **explainable alignment score from 0 to 100**.
Recruiters filter by an inclusive score range, select candidates, and preview and send a shortlist email.
The score measures alignment with the rubric. It is **not a hiring probability**. The system never rejects
candidates or makes hiring decisions.

> **Status: milestone 1, a local demo. Not production-ready.**
> Extraction and scoring use a deterministic **mock keyword matcher** (not AI), email goes to a **mock outbox**,
> and the ATS is a **mock connector**. All of these are labelled MOCK in the UI and API. All demo people are
> synthetic. See [docs/STATUS.md](docs/STATUS.md) for what is implemented, what is mocked and what remains.

- Architecture, diagrams, database schema and repository layout: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- API reference: [docs/API.md](docs/API.md) (plus live OpenAPI docs at http://127.0.0.1:8000/docs)
- Implemented vs mocked vs remaining, and open integration questions: [docs/STATUS.md](docs/STATUS.md)

## Prerequisites (Windows 11)

| Tool | Version | Check in the VS Code terminal |
|---|---|---|
| Python | 3.11 or 3.12 | `python --version` |
| Node.js | 20 or newer | `node --version` |
| Git | any | `git --version` |

Docker is **not** required for the demo; it uses SQLite.

## Setup (first time)

Open the `talentmatch-ai` folder in VS Code, then open a terminal with **Terminal → New Terminal** (PowerShell).

```powershell
# 1) Backend: virtual environment + dependencies
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) Seed synthetic demo data (tenants, users, the sample AI Engineer job, demo resume files)
.\.venv\Scripts\python.exe -m app.seed

# 3) Frontend dependencies
cd ..\frontend
npm install
cd ..
```

Optional: `Copy-Item .env.example .env` to override settings. The defaults work without a `.env` file.

> These commands call `.\.venv\Scripts\python.exe` directly, so you don't need to activate the virtual
> environment (activation can be blocked by PowerShell's execution policy). If `npm` is blocked with
> "running scripts is disabled", use `npm.cmd install` and `npm.cmd run dev` instead.

## Run

You need two terminals. Use the **+** button in the VS Code terminal panel to open the second one.

**Terminal 1: API and background worker**
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2: web app**
```powershell
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173** and sign in with a synthetic demo account (password `TalentMatch-Demo-2026!`):

| Account | Role |
|---|---|
| `recruiter@acme.example` | Recruiter: full workflow |
| `admin@acme.example` | Administrator: also settings, retention, audit history |
| `manager@acme.example` | Hiring manager: read-only, can view resumes, cannot send |
| `admin@globex.example` | A **different tenant**: use it to confirm Acme data is invisible |

Alternatively, run **Terminal → Run Task… → "Run TalentMatch (API + Web)"**.

## Demo walkthrough (milestone 1 flow)

1. **Job openings**: the seeded *AI Engineer* job already has a pasted description. You can also create a new job.
2. **Description & rubric**: click *Propose criteria from description* (labelled a MOCK proposal). Review the
   criteria, weights (they must total 100%), required flags and evidence terms. Then click **Approve rubric**.
3. **Resume ingestion**: upload every file in `backend\demo_data\resumes` (select them all in the file picker).
   The background worker processes them within a few seconds:

   | File | What it shows | Expected result |
   |---|---|---|
   | `01_strong_alex_morgan.pdf` | strong alignment | **100.00**, all required criteria supported |
   | `02_near_boundary_taylor_chen.docx` | near the boundary | **98.75** |
   | `03_just_below_jamie_patel.pdf` | just below 98 | **97.50**, a required criterion needs clarification |
   | `04_missing_required_riley_brooks.docx` | missing required evidence | **95.00**, required status *not supported* (no certification found) |
   | `05_partial_casey_nguyen.pdf` | partial alignment | **47.50** |
   | `06_injection_morgan_lee.pdf` | malicious embedded instructions | **7.50**, flagged; the injected text is excluded and the score is unaffected |
   | `07_duplicate_alex_morgan_copy.pdf` | duplicate submission | *duplicate*, linked to the original, not scored |
   | `08_unreadable_corrupt.pdf` | unreadable document | *needs manual review*, no score |
   | `09_scanned_image_only.pdf` | scanned PDF (no text layer) | *needs manual review*, no score (OCR not enabled) |

   Optionally click **Sync mock ATS**. One record succeeds, one fails once and then succeeds on retry, and one
   fails permanently because its file is missing.
4. **Candidate results**: enter Min `98`, Max `100`, then click **Apply Filter**. Only Alex (100.00) and Taylor
   (98.75) appear. Jamie (97.50) is excluded because filtering uses the exact score. Try `99` to `99.9`: the
   result is empty, and no one is added to fill it.
5. Open a candidate to see each criterion's weight, assessment level, verified evidence with page and section,
   missing or ambiguous information, and contribution. Extraction confidence is shown separately from the score.
6. Tick the shortlist checkboxes and click **Shortlist →**. Enter recipients (for example
   `hiring.lead@acme.example`), click **Preview email**, review it, then click **Send Shortlist**. An address
   outside `acme.example` requires an explicit confirmation first. The message appears in the **Mock outbox**
   on the same page, with status "accepted by mock provider, delivery not confirmed".
7. Open the **Assistant** (bottom right) and try *"Filter candidates between 98 and 100"*, *"Explain why Riley
   Brooks received this score"*, or select two candidates and ask *"Compare these two candidates"*.
8. Sign in as `admin@acme.example` to see **Audit history** and **Integrations & settings**.

Shortcut: `.\.venv\Scripts\python.exe -m app.seed --full` approves the rubric and ingests all demo resumes for you.
`--reset` wipes the local database and stored documents first.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

There are 66 tests covering: recruitment-mailbox intake (.eml import, read-only IMAP against a simulated server), score calculation and weight validation, inclusive range boundaries, missing evidence
and parsing failures, duplicates and connector retries, tenant isolation, unauthorized document access, roles,
email recipient validation, external-recipient confirmation, duplicate-send prevention, prompt-injection handling
and output grounding, redaction, chat-assistant guardrails, and CSV export.

Frontend type check: `cd frontend; npm run typecheck`.

## Configuration

Settings are read from environment variables or a `.env` file (see [.env.example](.env.example)). Important ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite at `backend/data/talentmatch.db` | Use `postgresql+psycopg://…` for PostgreSQL |
| `STORAGE_DIR` | `backend/data/documents` | Private resume storage |
| `JWT_SECRET` | dev placeholder | **Must** be set when `APP_ENV` is not `development` (startup fails otherwise) |
| `TASK_MODE` | `thread` | `thread` runs the worker inside the API; `worker` means you run `python -m app.worker` |
| `LLM_PROVIDER` / `EMAIL_PROVIDER` | `mock` | Only `mock` is implemented in milestone 1 |
| `MAX_UPLOAD_MB` | `10` | Per-file upload limit |

### PostgreSQL with Docker Compose (untested)

`docker-compose.yml` defines PostgreSQL, the API, a separate worker and the web app. Docker was not available on
the machine this milestone was built on, so this path **has not been run**. Use the SQLite instructions above for
the demo. To try it: install Docker Desktop, then run `docker compose up --build`, then
`docker compose exec api python -m app.seed`.

## Troubleshooting

- **Port already in use**: change `--port 8000` (and `VITE_API_PROXY`) or stop the other process.
- **Blank results after upload**: processing runs in the background. The ingestion page refreshes on its own
  while files are processing.
- **Code changes don't show up / new endpoints return 404 after `--reload`**: on Windows an old server process
  can keep answering on port 8000. Stop the API (Ctrl+C), check Task Manager for leftover `python.exe`
  processes, and start it again.
- **Start over**: stop the API, then run `.\.venv\Scripts\python.exe -m app.seed --reset`.
