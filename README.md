# CampusLens

Campus complaint management and transparency. Students report problems with a
photo; operations staff get a deterministic, explainable priority score; the
public sees only sanitized, approved summaries.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite 8, hash routing, no router dependency |
| Backend | FastAPI, Python 3.12+, psycopg 3 |
| Database | Supabase Postgres, Row Level Security on every table |
| Auth | Supabase Auth, JWKS-verified bearer tokens |
| Storage | Private Supabase bucket `CLimage` |
| AI | Gemini, advisory and optional |

## How a request is authorised

1. Browser sends `Authorization: Bearer <access token>`.
2. Backend fetches the project's JWKS and verifies the signature
   (RS256/384/512 only - HMAC and `none` are rejected).
3. Backend opens a transaction and runs
   `SET LOCAL ROLE authenticated` plus `SET LOCAL request.jwt.claims`, so
   PostgreSQL evaluates the RLS policies exactly as it would for a browser
   client.
4. The role is read from the `profiles` table. **Never from the token.**

## Deterministic scoring

A complaint's score is five factors, confirmed by a human. AI never scores it.

| Factor | Range | Source |
|---|---|---|
| Urgency | 0-30 | admin-confirmed |
| Impact | 0-25 | admin-confirmed |
| Recurrence | 0-20 | system-computed (90-day window) |
| Age | 0-15 | system-computed (completed 24h periods) |
| Safety | 0-10 | admin-confirmed |

Bands: **Low 0-29 · Medium 30-54 · High 55-74 · Critical 75-100**

A confirmed High safety can never be banded Low; the numeric score is left
unchanged and the adjustment is shown in the breakdown.

`priority_score IS NULL` means **Unscored**. A stored `0` is a real score inside
the Low band - the two are never conflated.

## Project layout

```
backend/
  app/            config, auth, database, storage, scoring, ai, schemas, main
  routers/        complaints.py (all HTTP routes)
  migrations/     001-012, 014, 015 in order (013 lives in supabase/migrations/)
  tests/          pytest (113 tests)
frontend/
  src/            App, auth, api, pages/, components/, lib/
  tests/          vitest (42 tests)
supabase/         migration 013 (submission INSERT policies)
docs/             runbooks, deployment, demo
```

## File reference

### Repository root

| File | Why it exists | What it does |
|---|---|---|
| `README.md` | Single entry point for developers | This file: architecture, file inventory, dev commands. |
| `.gitignore` | Keep secrets and junk out of git | Ignores `.env`, `.env.local`, `venv/`, `node_modules/`, `dist/`, `__pycache__/`, test caches. |
| `null` | **Accidental artifact** | Stray stdout redirect from a PowerShell session; safe to delete. |

### `backend/` — configuration & tooling

| File | Why it exists | What it does |
|---|---|---|
| `.env` | Local-only secrets (git-ignored) | Real Supabase URL/keys, `DATABASE_URL`, `GEMINI_API_KEY` for local runs. |
| `.env.example` | Template so no one guesses variable names | Documents every backend env var with placeholders and warnings about which keys are server-only. |
| `requirements.txt` | Reproducible installs | Pinned FastAPI, uvicorn, psycopg 3, psycopg-pool, httpx, PyJWT/cryptography, python-multipart, etc. |
| `render.yaml` | One-click backend deployment | Render blueprint: web service runs uvicorn, secret vars marked `sync:false` so they are set in the dashboard, never in git. |
| `campuslens.db` | **Legacy artifact** | Old local SQLite database (24 KB) from the pre-Supabase architecture; unused by the current code. |
| `backfill_ai_suggestions.py` | One-off repair tool | Re-analyses complaints whose `ai_*` columns are NULL (the pre-014 write-back silently updated 0 rows) through the production `store_ai_suggestion()` path; supports `--dry-run`. |
| `backfill_unscored_scores.py` | One-off repair tool | Computes and persists a deterministic auto-score for complaints stuck at `priority_score IS NULL`, reusing `scoring.score_complaint` + `database.save_score`. |
| `final_check.py` | **Scratch diagnostic** | Prints AI config flags and the newest complaints' `ai_*` columns; used during debugging, not part of the app. |
| `dao_lines.txt`, `dblines.txt`, `query_lines.txt` | **Scratch notes** | Grep output captured while tracing SQL statement names (`enqueue_analysis_job`, `record_job_failure`, `analysis_jobs`); safe to delete. |

### `backend/app/` — application modules

| File | Why it exists | What it does |
|---|---|---|
| `__init__.py` | Package marker | Empty package declaration. |
| `main.py` | App factory | `create_app(settings)` builds the FastAPI app so tests inject fake DB/storage/AI settings; configures CORS, logging, lifespan (closes the DB pool), mounts the router, exposes `/api/health`. |
| `config.py` | Single source of truth for configuration | Loads settings from the process env with a local `.env` fallback; every secret field is `repr=False` so it can never leak into logs or tracebacks; defines CORS origins, bucket name, `AI_ENABLED` parsing. |
| `auth.py` | Trust nothing unverified | Verifies the bearer JWT against the project JWKS (RS256/384/512 only, HMAC/`none` rejected), caches JWKS 10 min, then reads the role from `profiles` — **never from the token** — and provides the `current_identity` / `current_admin` FastAPI dependencies. |
| `database.py` | All SQL in one place | Connection pool; `session()` opens a transaction with `SET LOCAL ROLE authenticated` + JWT claims so RLS is evaluated by Postgres itself; parameterised helpers for complaints, events, scores, jobs, approvals; `store_ai_suggestion()` (migration 014) and `store_auto_score()` (migration 015) DB functions; `PRIVATE_COMPLAINT_COLUMNS` defines exactly which columns any query may select (includes the seven `ai_*` fields). |
| `scoring.py` | Deterministic, auditable priority score | Pure-Python five-factor scorer (urgency 0-30, impact 0-25, recurrence 0-20, age 0-15, safety 0-10), band mapping (Low/Medium/High/Critical), the safety floor rule, and the submission-time estimate — imports nothing from FastAPI/psycopg/AI so it is unit-testable alone. AI values are deliberately absent: only `confirmed_*` inputs can move a score. |
| `storage.py` | Private image handling | Uploads complaint images to the private `CLimage` bucket at `<student_id>/<uuid>.<ext>` (matching migration 009's storage policies), mints short-lived signed URLs for entitled viewers only; the service-role key only ever travels in headers, never in URLs or logs. |
| `ai.py` | Optional, non-fatal AI analysis | Calls Gemini (`gemini-2.5-flash` by default) **after** the complaint row is committed; strict `parse_analysis()` rejects empty/partial replies; scrubs anything secret-like (JWT-shaped strings, URLs) out of the response; every failure path returns "no suggestion" instead of raising, so AI can never block a submission. |
| `schemas.py` | Leak-proof response models | Three deliberately separate Pydantic families: `StudentComplaintOut` (own complaint incl. `ai_*` suggestion + coarse `priority_band`, **no numeric score**), `AdminComplaintOut` (adds score, breakdown, confirmed inputs), `PublicComplaintOut` (sanitized feed); plus `SubmitOut`, `StatusUpdateIn`, `AnalysisConfirmIn`, `PublicApprovalIn`, `MeOut`, `HealthOut`, `AdminAnalyticsOut`. A field cannot leak by omission when the model has no such field. |

### `backend/app/routers/`

| File | Why it exists | What it does |
|---|---|---|
| `__init__.py` | Package marker | Empty package declaration. |
| `complaints.py` | The entire HTTP surface | Every route: student submit/list/get (`POST/GET /api/complaints`), admin list/get/status/analysis/analytics, public feed, health, publication approval. Key helpers: `_student_out()` / `_admin_out()` map DB rows onto the leak-proof schemas (the student mapper passes the seven `ai_*` fields through — without it My Complaints showed "Not started"); `_analysis_status()` derives `succeeded`/`null` from `ai_summary`/`ai_urgency` because `analysis_status` is **not** a DB column; `_student_band()` reduces the score to one of four labels; `_store_suggestion()` writes the AI suggestion and the auto-score in **two separate transactions** so a scoring error can't roll back the analysis; `_try_analyse()` runs AI synchronously after the row commits. All swallowed exceptions log `exc_info=True`. `build_router()` clones routes because FastAPI 0.142 forbids including one router twice. |

### `backend/migrations/` — SQL, applied in order via the Supabase SQL editor

| File | Why it exists | What it does |
|---|---|---|
| `001_profiles.sql` | Roles must live in the DB, not the JWT | Creates `profiles` (one row per authenticated user) with the `role` column used for authorisation, RLS enabled. |
| `002_campus_locations.sql` | Structured reference data | `campus_categories` + `campus_locations` — the canonical keys recurrence matching groups on (inactive until configured). |
| `003_complaints.sql` | The central table | `complaints` with two enforced rules in the column layout: AI suggestion columns (`ai_*`) vs admin `confirmed_*` inputs are physically separate, and `priority_score` starts NULL (Unscored ≠ 0). RLS: own rows for students, all rows for admins. |
| `004_complaint_scores.sql` | Score history (decision D9) | `complaint_scores` — an append-only row is written **only when an admin confirms**; the live score stays on `complaints`. |
| `005_analysis_jobs.sql` | AI reliability | `analysis_jobs` — the complaint row is written first, then the job, so a provider outage never loses a report; retries/attempts tracked here. |
| `006_events_notes.sql` | Auditability | `complaint_events` (append-only "who changed what, when") + `investigation_notes` (internal admin notes students never see). |
| `007_public.sql` | Privacy boundary | `public_complaints` — a separate, sanitised copy with **no reporter identity and no score**; the community portal only ever reads this table. |
| `008_triggers.sql` | Honest timestamps | `updated_at` maintenance trigger so the column can't silently go stale. |
| `009_storage_policies.sql` | Image access control | Storage policies on the private `CLimage` bucket: each path segment starts with the owner's user id; the bucket itself is created manually. |
| `010_seed_admin.sql` | First-admin bootstrap | Deliberately inserts nothing: defines a procedure for promoting the first admin — no self-service admin path exists. |
| `011_verify.sql` | Loud failure on a bad apply | Non-mutating inspection asserting 001-008 produced the expected schema; raises EXCEPTION on mismatch. |
| `012_auto_profile.sql` | Closes a signup gap | Trigger auto-creating the `profiles` row on signup (`profiles.id` references `auth.users`). |
| `014_ai_writeback.sql` | Fixes the silent AI write-back failure | `store_ai_suggestion()` — SECURITY DEFINER function writing only the seven `ai_*` columns; before it, the system identity's UPDATE matched no RLS policy and silently updated zero rows. |
| `015_auto_scoring.sql` | Scores without manual confirmation | `store_auto_score()` — SECURITY DEFINER function computing the deterministic score straight from the row's `ai_*` levels + age/recurrence; records a `system` audit event. |

### `supabase/migrations/`

| File | Why it exists | What it does |
|---|---|---|
| `013_submission_inserts.sql` | Three-row submission transaction | INSERT policies letting one submission atomically write `complaints` + `complaint_events` + `analysis_jobs`. (Lives here — numbered between 012 and 014 — so it stays in apply order alongside the backend migrations.) |

### `backend/tests/` — pytest, 113 tests, zero live services

| File | Why it exists | What it does |
|---|---|---|
| `__init__.py` | Package marker | Empty package declaration. |
| `conftest.py` | Shared fixtures | A complete in-memory fake of Postgres/Supabase/Storage/AI: JWT verified against a local RSA key + stubbed JWKS, `FakeStore` mirrors RLS visibility, statement-name routing reproduces each SQL helper. No test ever touches a real service. |
| `test_auth.py` | Credential handling | Missing/garbage/expired/forged tokens rejected; valid token for a user with no profile row → 403. |
| `test_isolation.py` | Student privacy | A student reads only their own rows (404, never 403); unscored rows persist NULL yet always show a deterministic band; regression tests pin that list/detail endpoints expose the stored `ai_*` analysis with `analysis_status: "succeeded"` and never the numeric score. |
| `test_scoring.py` | The scorer contract | Five-factor totals, nested/complete breakdowns, band boundaries. |
| `test_estimates.py` | Submission-time estimate (BCIP-1144) | Full 0-100 range, every band, age helper spec, structured recurrence, safety floor, LOW(0) fallback for unknown levels, determinism. |
| `test_admin_ops.py` | Admin behaviour | Status updates, scoring confirmations, analytics; pins that NULL is Unscored while a stored 0 is a real score counted inside its band. |

| `test_approval.py` | Public gate | A complaint is public only because an admin published it; student submissions never appear in the feed by themselves. |
| `test_public_feed.py` | Feed sanitisation | The unauthenticated endpoint exposes only approved rows — no reporter identity, score, free-text description or internal location code. |
| `test_storage.py` | Image safety | Upload type/size/ownership rules and signed-URL entitlement (only the owner sees their image). |
| `test_ai_failure.py` | AI is optional | Complaints are stored and deterministically scored whether AI is enabled, disabled, failing or completely absent; no AI column can move a score. |
| `test_ai_empty.py` | Empty AI replies fail honestly | A provider reply with zero usable fields must not be reported as success: `analysis_queued: false` and a failure recorded as kind `empty`. |
| `test_ai_writeback.py` | Migration 014 works | The `ai_*` write-back actually persists under the system identity (the original bug: UPDATE matched no RLS policy and touched zero rows silently). |
| `test_me.py` | Identity endpoint | `GET /api/me` for student, admin, missing token, invalid token and a valid token with no profiles row. |

### `frontend/` — configuration

| File | Why it exists | What it does |
|---|---|---|
| `index.html` | Vite entry document | Mounts `#root`, loads the app module, sets the page title/meta. |
| `package.json` | Dependency + script manifest | React 19, react-dom, lucide-react, @supabase/supabase-js; scripts: `dev`, `build`, `preview`, `test` (vitest). Dev deps: Vite 8, @vitejs/plugin-react, tailwindcss vite plugin, vitest, jsdom, @testing-library. |
| `package-lock.json` | Reproducible installs | Exact resolved dependency tree. |
| `vite.config.js` | Dev-server contract | React + Tailwind plugins; `strictPort` on 5173 because the backend CORS allow-list only contains localhost/127.0.0.1:5173 — silently moving to 5174 would break every request, so it fails loudly instead; build output `dist/`. |
| `vitest.config.js` | Test runner config | jsdom environment, global APIs, React plugin applied to test transforms so `.jsx` tests compile with the automatic JSX runtime like the app; includes `tests/**/*.test.{js,jsx}`. |
| `vercel.json` | Static-host deployment | SPA rewrite: every non-`/assets/` path → `index.html` (hash routing survives without it, but deep links and asset fallbacks behave). |
| `.env.example` | Public-env template | Documents the only three frontend vars: `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — with an explicit warning that server secrets must never use a `VITE_` prefix (Vite publishes them to every visitor). |
| `.env.local` | Local overrides (git-ignored) | Real local values for the three public vars. |
| `.gitignore` | Keeps build/secret junk out | `node_modules/`, `dist/`, `.env.local`. |
| `README.md` | Frontend-specific docs | Route map, API endpoint table, frontend conventions. |

### `frontend/src/` — application core

| File | Why it exists | What it does |
|---|---|---|
| `main.jsx` | React bootstrap | Renders `<App />` in StrictMode; forces scroll-to-top on reload so page headings aren't cut off by restored scroll offset. |
| `App.jsx` | Tiny hash router + shell | Defines the routes (`#/`, `#/community`, `#/signin`, `#/submit`, `#/mine`, `#/complaint/{id}`, `#/profile`, `#/dashboard`, `#/triage`) with visibility gates (public / signed-in / admin). The top-bar search is a real form: Enter routes the query to the page that can search it — admins to `#/triage?q=…`, students to `#/mine?q=…` (both backed by the backend `q` parameter). The admin sidebar highlights the active item by route. Hiding a link is presentation only — the backend authorises every request. |
| `api.js` | The one HTTP client | Every protected call carries `Authorization: Bearer <token>`; parses both error shapes the backend emits (`{"detail"}` and FastAPI 422 lists); fires the `onUnauthorized` hook on 401 (session expiry); uses absolute signed `image_url`s as-is. Contains the endpoint map matching `complaints.py`. |
| `auth.jsx` | Session state for the whole app | `AuthProvider` context: Supabase session lifecycle, sign-in/up/out with friendly error messages, and the role fetched from `GET /api/me` — never from the token, so a forged claim can't change the UI. |
| `constants.js` | Backend vocabularies mirrored | The exact status strings (`Reported`/`In Progress`/`Resolved`), sort options, limit options, band order, level choices and image limits the API accepts. UI never invents values; bands/scores always come from the API. |
| `styles.css` | Design tokens + component CSS | Tailwind import plus the custom utilities (`btn-gradient`, `card-lift`, `animate-fade-up`, `text-gradient`) used across pages. |
| `lib/supabase.js` | Browser Supabase client | Creates the client from the two PUBLIC `VITE_` values only; `authConfigured` flag lets the app run with sign-in disabled instead of crashing when unconfigured. The service-role key must never appear here. |

### `frontend/src/pages/` — one file per route

| File | Why it exists | What it does |
|---|---|---|
| `SignInPage.jsx` | Entry for accounts | Sign-in / sign-up forms calling Supabase Auth directly from the browser; the backend is only involved afterwards when tokens ride along API requests. No service-role key anywhere here. |
| `SubmitPage.jsx` | Reporting flow | Multipart form (photo + description + location) with client-side validation, image type/size limits mirrored from `constants.js`, live preview, and `ResultPanel` rendering the 201 response — including the synchronous AI analysis returned in the same response. |
| `MyComplaintsPage.jsx` | "My complaints" (`#/mine`) | Server-side `q` / `status` / `sort` filters over `GET /api/complaints` (own rows only); the global top-bar search pre-fills `q` via the `initialQuery` prop (`#/mine?q=…`). Each row links to the full detail page `#/complaint/{id}`, which shows the report, the AI analysis and the delete action. |
| `DashboardPage.jsx` | Admin portal, two views | `view="overview"` (`#/dashboard`): real KPI cards + priority/status distribution panels from `GET /api/admin/analytics/summary` and a **latest-complaints-only** queue (`sort=newest`, 6 rows, no filters) whose rows open the detail drawer; "All complaints" links to the triage workspace. `view="triage"` (`#/triage`): the full workspace — every complaint via `GET /api/admin/complaints` with band/category/q/open/status/sort/limit/offset server-side filters, pagination (limit+1 probe), CSV export, and the full-screen drawer (AI panel, status/score/publish/delete actions, audit trail, investigation notes). `initialQuery` pre-fills the search from the global top bar. |
| `CommunityPage.jsx` | Public feed (`#/community`) | Unauthenticated `GET /api/public/complaints` — no token sent; the backend reads `public_complaints`, which physically has no reporter identity or score. Search/filter over sanitized rows only. |

### `frontend/src/components/` — shared UI

| File | Why it exists | What it does |
|---|---|---|
| `ComplaintCard.jsx` | Admin complaint card | Expandable admin view: details list, signed photo with honest fallback ("Photo attached — couldn't load preview" instead of a misleading "No photo"), `StatusSelect`, priority badge/meter, `UnscoredNote` when `priority_score` is null, and publish/revoke-for-public actions. |
| `Priority.jsx` | Score presentation rules | `PriorityBadge`, `ScoreMeter`, `UnscoredNote`. The band shown is always exactly what the backend returned; a null score renders as "Unscored" — never guessed as Low, never a made-up number. |
| `Status.jsx` | Status rendering | `StatusBadge` + `StatusSelect`, restricted to the three exact backend strings so the UI can never send a value the API rejects. |
| `ResultPanel.jsx` | Post-submit feedback | The only place the 201 body is rendered: `AiFindings` shows category/summary/evidence/uncertainty/levels straight from the response — nothing inferred, nothing invented. |
| `SummaryPanel.jsx` | Analytics tiles | Stat tiles and band distribution for the admin dashboard, percentages computed from API totals only. |
| `ui.jsx` | Shared primitives | `Spinner`, `ErrorBanner` (with retry), `Notice`, `EmptyState`, `SkeletonRows` — consistent loading/empty/error states across all pages. |

### `frontend/tests/` — vitest, 42 tests

| File | Why it exists | What it does |
|---|---|---|
| `setup.js` | Shared fetch mock | `jsonResponse` / `formBody` helpers so tests exercise the real `api.js` (URL building, auth headers, error parsing, 401 handling) without any network. |
| `api.test.js` | Client plumbing | Authorization header attachment, query building, base-URL handling. |
| `api.behaviour.test.js` | Error-shape contract | 422 validation lists vs `{"detail"}` messages, the 401 unauthorized hook, and that list responses never contain `priority_score`. |
| `auth.test.jsx` | Role-driven UI | The Admin tab renders **only** when `GET /api/me` returns `role === 'admin'` — never inferred from the token. |
| `signin-routing.test.jsx` | Routing regression | Signed-out `#/signin` renders the auth form (not a blank page); sign-in buttons in the top bar and Community empty state reach it. |
| `submit-page.test.jsx` | Submission regression | The form submits with **no photo** attached (the backend accepts `image: Optional`), and renders the server-side AI analysis honestly — including the "AI analysis done, returned nothing" case. |
| `approval.test.js` | Publish gate contract | The client only reaches the public feed through an explicit admin approval call. |
| `privacy.test.js` | Privacy at source level | Guards that no student-facing component reads a numeric score, breakdown or admin-confirmed input — the backend doesn't send one, and the UI must not invent it. |

### `docs/` — operational documentation

| File | Why it exists | What it does |
|---|---|---|
| `MIGRATION_RUNBOOK.md` | Correct schema rollout | Apply 001-015 **one file at a time** in the Supabase SQL editor (never batched), with verification steps and the note that 011 runs after 008. |
| `ADMIN_PROMOTION.md` | First-admin bootstrap | The only supported way to become an admin (a manual dashboard procedure) — deliberately no self-service path; also covers demotion. |
| `DEPLOYMENT.md` | Going live | Vercel (frontend) + Render (backend) configuration, env vars for each, both pointing at one Supabase project. |
| `PRODUCTION_VERIFICATION.md` | Honest live testing | Fill-in checklist with PASS/FAIL/NOT TESTED/BLOCKED legend; explicitly forbids reporting a mocked pass as a live pass. |
| `SCRATCH_VERIFICATION.md` | Manual E2E checklist | Step-by-step verification against a **disposable scratch** Supabase project — a plan, not a report. |
| `DEMO.md` | Demo day script | Product summary, demo flow (student submit → admin triage → community feed), architecture overview, troubleshooting table, known limitations. |

## Local development

```powershell
# Terminal 1 — backend (http://127.0.0.1:8000)
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Terminal 2 — frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to
`frontend/.env.local`, then fill in your Supabase values. Both real env files
are git-ignored.

> If starting the backend fails with `[Errno 10048] ... only one usage of each
> socket address`, an older uvicorn process still holds port 8000:
> `Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`
> — then start exactly **one** server. Multiple stacked instances on the same
> port serve stale code non-deterministically.

## Tests

```powershell
cd backend  && .\venv\Scripts\python.exe -m pytest -q     # 113 tests
cd frontend && npx vitest run                             # 42 tests
cd frontend && npx vite build                             # production bundle
```

All tests use mocks for Supabase, Postgres and Storage. **No live-service
behaviour has been verified** unless recorded in
`docs/PRODUCTION_VERIFICATION.md` — see `docs/MIGRATION_RUNBOOK.md`.

Run vitest on its own: running it in parallel with pytest can starve the
jsdom tests and produce flaky 5-second timeouts.

## Privacy model

* Students see only their own complaints, and only permitted status fields.
* The student response schema has **no score field at all**, so scores cannot
  leak by omission. Students get at most a coarse `priority_band`
  (Low/Medium/High/Critical) plus the AI `ai_*` suggestion.
* The public feed is a separate table with no reporter identity and no score. A
  row is public only after an admin publishes admin-authored text.
* Images are private; the browser only ever receives short-lived signed URLs.
* The role is always read from `profiles` — a JWT claiming `role: admin`
  grants nothing.

## Known limitations

* Recurrence scoring is inactive until the location/category lists are
  configured.
* No notifications (email/push).
* Admin promotion is a manual Supabase dashboard step by design.
* Files marked **scratch/legacy/artifact** above (`null`, `campuslens.db`,
  `final_check.py`, `*_lines.txt`, `__pycache___backup/`) are not part of the
  application and are safe to delete.
