# CampusLens - scratch Supabase verification checklist

Manual, step-by-step. Run everything against a **disposable scratch Supabase
project**, never production. Nothing here has been executed against a real
service - this checklist is the plan, not a report.

## 0. Setup

1. Create a throwaway Supabase project.
2. Apply migrations in order, in the SQL editor:
   `001_profiles` -> `002_campus_locations` -> `003_complaints` ->
   `004_complaint_scores` -> `005_analysis_jobs` -> `006_events_notes` ->
   `007_public` -> `008_triggers` -> `009_storage_policies` -> `010_seed_admin`
   -> `012_auto_profile` -> finally `011_verify.sql`.
3. `011_verify.sql` must end with `CampusLens Stage 1 verification PASSED`.
   If it reports `NO ADMIN YET`, finish step 4 and re-run.
4. Create your admin: Authentication -> Users -> Add user. Note the UUID.
   Then run the documented manual step in `010_seed_admin.sql` (insert the
   `profiles` row, then `SELECT public.promote_to_admin('<uuid>');`).
5. Storage -> New bucket: `CLimage`, **Public OFF**, 5 MiB,
   MIME `image/jpeg`, `image/png`, `image/webp`.
6. `backend/.env`: DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY,
   SUPABASE_SERVICE_ROLE_KEY, SUPABASE_BUCKET, GEMINI_API_KEY (optional).
7. `frontend/.env`: VITE_API_BASE_URL, VITE_SUPABASE_URL,
   VITE_SUPABASE_ANON_KEY. Never put the service-role key in either frontend
   variable.
8. Start the backend (`uvicorn app.main:app --reload`) and the frontend
   (`npm run dev`), then open `http://localhost:5173`.

## 1. Student sign-up and sign-in

- [ ] Click "Sign in" -> "Need an account?" -> create an account.
- [ ] Confirm a `profiles` row exists: migration 012's trigger created it with
      `role = 'student'`. Check: `SELECT role FROM profiles;`
- [ ] Sign out, sign back in. You stay signed in after a page reload
      (session persistence).
- [ ] `GET /api/me` returns your own id, email and `role: "student"`.
- [ ] **The Admin tab is NOT visible.**

## 2. Admin sign-in and role detection

- [ ] Sign in with the admin account.
- [ ] The header shows your email followed by `(admin)`.
- [ ] **The "Operations dashboard" tab appears** (this is the Stage 3 fix).
- [ ] `GET /api/me` returns `role: "admin"`.

## 3. Complaint submission and persistence

- [ ] Submit with text + a real JPEG under 5 MB.
- [ ] You get "Complaint #N received", status Reported.
- [ ] `#/mine` lists it with your photo.
- [ ] Row count check: `SELECT count(*) FROM complaints;`
- [ ] `priority_score IS NULL` and all `confirmed_*` are NULL - submission never
      scores by itself.

## 4. Student isolation

- [ ] Create a second student account and have them submit a complaint.
- [ ] Student A's `#/mine` shows only their own complaint.
- [ ] As Student A, request Student B's complaint id directly -> **404**, never
      403 and never a body containing the data.
- [ ] No student response ever contains `priority_score`, `score_breakdown`,
      `ai_*` or `confirmed_*` (check the browser Network tab).

## 5. Private image upload and access restrictions

- [ ] Upload a photo -> object path is `<your-uuid>/<uuid>.jpg`.
- [ ] Your own image loads via a signed URL.
- [ ] Student A cannot read Student B's image.
- [ ] **Unsigned public URL in a logged-out window must fail:**
      `https://<ref>.supabase.co/storage/v1/object/public/CLimage/<path>`
      -> 400/denied, never the photo.
- [ ] Upload a `.txt` or a shell script renamed `.jpg` -> rejected (422); the
      backend sniffs magic bytes, not the filename or Content-Type.

## 6. Admin status and analysis actions

- [ ] Open the dashboard as admin: all complaints are listed.
- [ ] Change a status -> it persists after a reload.
- [ ] Expand "Confirm scoring inputs", choose urgency/impact/safety, click
      "Confirm and score".
- [ ] The card then shows a score and band; `score_breakdown` is populated.
- [ ] The AI suggestion is labelled as a suggestion; it never scores on its own.
- [ ] Unscored complaints stay visibly **Unscored**, never Low.
- [ ] As a student, the same admin URLs return **403**.

## 6b. Public approval gate

- [ ] Submit a complaint and open `#/dashboard`. It is **NOT** in the feed.
- [ ] Check the feed directly: `GET /api/public/complaints` returns nothing.
- [ ] In the admin card, expand "Publish to the community feed", write a public
      summary/category/location, click **Publish sanitized summary**.
- [ ] The feed now shows one sanitized entry. Confirm the reporter's original
      text is **not** present - the public entry only contains what you typed.
- [ ] Click **Withdraw from feed** -> the entry disappears again.
- [ ] As a student, the same publish request returns 403.
- [ ] Confirm in SQL that an unpublished row has `approved_at IS NULL`:
      `SELECT id, approved_at FROM public_complaints;`

## 7. Public community feed

- [ ] `#/community` loads with **no sign-in**.
- [ ] It shows only approved entries, with no reporter identity and no score.
- [ ] An unapproved complaint does not appear.
- [ ] The feed stays read-only: no status control, no score.

## 8. Gemini unavailable

- [ ] Stop the network, or set `AI_ENABLED=false` in `backend/.env` and restart.
- [ ] Submit a complaint -> **still 201**, still listed under `#/mine`.
- [ ] `priority_score` stays NULL; the complaint shows as Unscored, not Low.
- [ ] `analysis_jobs` records the failure without any student-visible error.

## 9. Tear down

Delete the scratch project. Nothing here is production.
