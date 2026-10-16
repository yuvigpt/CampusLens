# CampusLens frontend (Stage 5)

React + Vite single-page app for CampusLens:

- `#/submit` — student complaint submission (photo + description + location)
- `#/dashboard` — admin triage board with analytics, filtering and status updates

## Run it

```bash
# 1. backend (from repo root)
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --port 8000     # Windows

# 2. frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production bundle in dist/
npm run preview      # serve dist/ on http://localhost:5173
```

The dev server is pinned to port **5173** (`strictPort`) because the backend's
CORS allow-list only contains `http://localhost:5173` and
`http://127.0.0.1:5173`.

## Configuration

`VITE_API_BASE_URL` (default `http://127.0.0.1:8000`) — see `.env.example`.
Only `VITE_`-prefixed variables reach the browser bundle. **No API keys belong
in this app**; the Gemini key lives exclusively in `backend/.env`.

## Endpoints used

| Method | Path | Used for |
| --- | --- | --- |
| GET | `/api/health` | header status pill (no auth) |
| POST | `/api/complaints` | multipart `image` + `description` + `location` (any signed-in user) |
| GET | `/api/complaints` | own complaints only - `status`, `sort`, `limit`, `offset` |
| GET | `/api/complaints/{id}` | own complaint only; 404 for anyone else |
| GET | `/api/admin/complaints` | every complaint (admin) |
| GET | `/api/admin/complaints/{id}` | one complaint with its score (admin) |
| PATCH | `/api/admin/complaints/{id}/status` | body `{"status": "..."}` (admin) |
| PATCH | `/api/admin/complaints/{id}/analysis` | `{"confirmed_urgency","confirmed_impact","confirmed_safety"}` (admin) - the only endpoint that scores |
| GET | `/api/admin/analytics/summary` | `total`, `by_status`, `by_band`, `unscored`, `unresolved` (admin) |
| GET | `/api/public/complaints` | approved, sanitized entries (no auth) |

Images are served as short-lived **signed URLs** returned by the backend in
`image_url`; they are used as-is and never constructed in the browser.

## Honesty rules baked into the UI

- A score is **only** ever the `priority_score` the API
  returned. Nothing is recomputed or invented client-side.
- `priority_score == null` renders as **Unscored** (dashed badge + explicit
  note), never as Low or 0.
- `ai_*` fields are shown as an **AI suggestion** only. The values that are
  scored are the `confirmed_*` levels an administrator sets explicitly.
- Status badges show the stored status; "Resolved" only appears when the
  backend says `Resolved`.
- `analysis` and `warnings` are only returned by `POST /api/complaints`, so
  the dashboard shows the persisted AI fields (category, summary, risk,
  impact, urgency, evidence, uncertainty) instead of fabricating an outcome.

## Decisions / limitations

- Routing is a small hash router (no router dependency) so a static build works
  without server rewrite rules.
- Dependencies are exactly: `react`, `react-dom`, plus `vite` and
  `@vitejs/plugin-react` (dev).
- `GET /api/complaints?category=` is an exact match on a stored category, so
  the analytics bucket `Unclassified` (NULL category) cannot be used as a
  filter value; such complaints are labelled "Unclassified · no category" on
  their cards and counted in analytics.
- Pagination uses `limit`/`offset`; there is no total count for a filtered
  page, so the pager shows how many rows are loaded.
- No auth, maps, or offline queue — out of scope for this stage.
