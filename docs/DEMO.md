# CampusLens - demo package

## Product in one sentence

CampusLens lets students report campus problems with a photo, gives operations
staff a deterministic, explainable priority score, and publishes only the
sanitized results to a public transparency feed.

## The three portals

| Portal | Route | Who | Shows |
|---|---|---|---|
| Student | `#/submit`, `#/mine` | any signed-in user | own complaints + status only |
| Admin | `#/dashboard` | verified admins | every complaint, score, scoring, publication |
| Community | `#/community` | anyone, no sign-in | approved, sanitized summaries only |

## Demo script (about 2.5 minutes)

**0:00 - Problem (15s)**
"Campus complaints are lost in email. Staff triage them by whoever is loudest
this week. Students never learn whether anything happened."

**0:15 - Student submits (30s)**
Show `#/submit`. Type a real-looking complaint, attach a photo. Press Submit.
Point out: *"The complaint is saved FIRST. Analysis happens after, on the
server. If AI is down, this still succeeds - it is just shown as Unscored."*

**0:45 - Scoring is deterministic, not AI (35s)**
Switch to the admin account, open `#/dashboard`. Expand **Confirm scoring
inputs**, pick urgency / impact / safety, press **Confirm and score**.
*"The number comes from a fixed formula a human confirmed. The AI only ever
suggests. A student can never set their own priority."*

**1:20 - The score is explainable (20s)**
Point at the score and band.
*"Urgency 30, impact 12, safety 0. Every point traces to a named input."*

**1:40 - Privacy by construction (30s)**
Open `#/mine` as the student, then `#/community` as anyone.
*"The public feed shows only what an admin typed - not the reporter's words,
not their identity, not the score. Nothing appears there until an admin
publishes it."*

**2:10 - Close (20s)**
*"Deterministic scoring, role-based access, and a public feed that cannot leak.
Everything here works with AI switched off."*

## Recommended order

1. Migrations + `011_verify.sql` PASSED (shows rigor)
2. Student sign-up -> complaint with image
3. AI-unavailable resilience (one line, or skip if short on time)
4. Admin scoring
5. Approval -> public feed
6. Security: student cannot reach admin routes (one curl, optional)

## Prerequisites

- Migrations applied, `011_verify.sql` passing
- One **admin** account (see `ADMIN_PROMOTION.md`)
- One **student** account
- Bucket `CLimage` exists and is private
- Both servers running, or both deployed

## Fallback plan

| Problem | Plan B |
|---|---|
| Gemini unavailable / no API key | Fine. `AI_ENABLED=false` is the honest default. Say so: "analysis is optional; complaints still save." |
| Network to Supabase down | Show the schema diagram or screenshots. Do not claim it works. |
| Image upload fails | Submit without a photo - the backend accepts text-only. |
| Admin sign-in fails | Show the student and community portals, then the scoring code. |
| Nothing deployed | Run locally: two terminals, `uvicorn` + `npm run dev`. |

**Never fabricate demo statistics.** If the database is empty, say so and submit
something live.

## Demo data

Use clearly fictional records - never real student information. Suggested
fictional entries:

- "Ceiling light flickers in Science Block, second floor corridor"
- "Drinking fountain runs constantly outside the library"
- "Broken window latch in the Block C stairwell"

**Do not insert demo rows into a live database without approval.** Producing them
live during the demo is cleaner than seeding.

## Architecture, in 60 seconds

- **Frontend** React + Vite on Vercel. Hash routing, three portals, one bundle.
- **Backend** FastAPI on Render. Every request verified against Supabase Auth's
  JWKS (RS256 only); the role is read from Postgres, never from the token.
- **Database** Supabase Postgres with Row Level Security on all 9 tables. Each
  request opens a transaction that sets the caller's role, so policies are
  evaluated exactly as they are for a browser client.
- **Storage** private `CLimage` bucket; the browser only ever sees short-lived
  signed URLs.
- **AI** Gemini, advisory only, runs after persistence and never blocks a write.

## Key decisions

1. **The score is deterministic.** Five fixed factors, human-confirmed.
   Reproducible and auditable; AI cannot move it.
2. **AI is optional and post-hoc.** Complaint persistence never depends on it.
3. **Three separate response schemas.** A student model has no score field at
   all, so it cannot leak by accident.
4. **RLS is the real boundary.** The app does not decide who sees what; Postgres
   does.
5. **`Unscored` is a real state.** NULL and 0 are different, and the UI shows the
   difference.
6. **The public feed is opt-in.** A row is public only after an admin publishes
   admin-authored text.
7. **Storage paths carry ownership.** `<user_id>/<uuid>.jpg`, enforced in policy.
8. **AI failure is async-only.** Every provider error collapses to a recorded
   job failure; the complaint is already committed.

## Known limitations (disclose honestly)

- Recurrence scoring is **inactive** until the building/floor/category lists are
  configured, so recurrence always scores 0.
- There is no email or push notification.
- Free-tier hosts sleep; the first request is slow.
- Admin promotion is a manual dashboard step (by design, not self-service).
- No offline support; submissions require connectivity.
- The public feed is read-only: no public voting or commenting.
