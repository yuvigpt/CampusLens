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
| GET | `/api/health` | header status pill |
| POST | `/api/complaints` | multipart `image` + `description` + `location` |
| GET | `/api/complaints` | `status`, `category`, `sort`, `limit`, `offset` |
| PATCH | `/api/complaints/{id}/status` | body `{"status": "..."}` |
| GET | `/api/analytics/summary` | dashboard counters and breakdowns |
| GET | `/uploads/{filename}` | complaint images (prefix with the API base URL) |

## Honesty rules baked into the UI

- A band/score is **only** ever the `priority_band` / `priority_score` the API
  returned. Nothing is recomputed or invented client-side.
- `priority_score == null` renders as **Unscored** (dashed badge + explicit
  note), never as Low or 0.
- `uncertainty_or_missing_information`, backend `warnings` and
  `analysis.error` / `error_kind` are shown verbatim.
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
