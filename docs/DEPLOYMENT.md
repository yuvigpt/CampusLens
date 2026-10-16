# CampusLens - deployment guide (Vercel + Render)

Two services: the React app on **Vercel**, the FastAPI API on **Render**.
Both talk to the same Supabase project.

```
Browser (Vercel)  --HTTPS-->  Render API  --psycopg-->  Supabase Postgres
       |                                                   |
       +-------------- Supabase Auth (JWT) ---------------+
       |                                                   |
       +-- signed image URLs ----------------------------- +--> Storage (CLimage)
```

## Order of operations

Deploy the **backend first**. The frontend needs the API URL to build correctly
(`VITE_API_BASE_URL` is inlined at build time, not at runtime).

---

## 1. Render (backend)

Dashboard -> New -> Blueprint, or New -> Web Service.

Using the blueprint (`backend/render.yaml`):

| Setting | Value |
|---|---|
| Repository | your repo |
| Root Directory | `backend` |
| Runtime | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |

Set these under **Environment** (values marked `sync: false`):

| Variable | Where to get it | Secret? |
|---|---|---|
| `SUPABASE_URL` | Project Settings -> API | no |
| `SUPABASE_ANON_KEY` | Project Settings -> API (publishable) | no |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings -> API Keys -> secret | **YES** |
| `DATABASE_URL` | Project Settings -> Database -> URI (use the **pooler** string) | **YES** |
| `CORS_ORIGINS` | `https://<your-vercel-domain>` - **not** `*` | no |
| `GEMINI_API_KEY` | Google AI Studio (optional) | **YES** |

Already defaulted in the blueprint: `SUPABASE_BUCKET=CLimage`,
`AI_ENABLED=false`, `GEMINI_MODEL=gemini-2.5-flash`, `PYTHON_VERSION`.

> Free Render services sleep after inactivity. The first request can take
> ~50 seconds while it wakes. That is expected, not a bug.

Verify: `https://<render-host>/api/health` -> `{"status":"ok","service":"campuslens-api","version":"2.0.0"}`

---

## 2. Vercel (frontend)

Dashboard -> Add New -> Project -> import the repo.

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Build Command | `npm run build` |
| Output Directory | `dist` |

`frontend/vercel.json` already pins the build, adds SPA rewrites, caches hashed
assets and sets `X-Content-Type-Options` / `X-Frame-Options` /
`Referrer-Policy`.

Environment variables (**all public** - Vercel inlines `VITE_*` into the
JavaScript bundle, so never put a secret here):

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<render-host>` |
| `VITE_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | publishable key |

> Never add `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` or `GEMINI_API_KEY` to
> Vercel. Anything in a `VITE_*` variable is shipped to every visitor.

---

## 3. Supabase Auth URLs

After the frontend is live, add both URLs under
**Authentication -> URL Configuration**:

| Setting | Value |
|---|---|
| Site URL | `https://<your-vercel-domain>` |
| Redirect URLs | `https://<your-vercel-domain>/**` |

Keep `http://localhost:5173` in the redirect list for local development.

---

## 4. CORS

`CORS_ORIGINS` on Render must list the **deployed** frontend origin. It defaults
to `http://localhost:5173` when unset, so a browser on the Vercel domain will be
blocked until you set it.

Comma-separate for multiple origins. Never `*`: the API authenticates with
bearer tokens.

---

## 5. Verify after deploying

1. Frontend loads over HTTPS, header shows **API online**.
2. Sign up and in; the Admin tab is hidden for a student.
3. Submit a complaint with a photo.
4. `GET /api/health` on the deployed API returns `ok`.
5. Check the browser Network tab: requests carry
   `Authorization: Bearer <token>` and the response bodies contain no scores.
6. Confirm `SUPABASE_SERVICE_ROLE_KEY` appears nowhere in the page source,
   `dist/assets/*.js`, or any network response.
