# CampusLens - production verification

Fill in the Result column as you go. Record **Not tested** rather than guessing.
Live checks are not mocked; do not report a mocked pass as a live pass.

Legend: **PASS** / **FAIL** / **NOT TESTED** / **BLOCKED**

## A. Availability

| # | Check | Expected | Result |
|---|---|---|---|
| A1 | Frontend loads over HTTPS | Page renders, no mixed-content warnings | |
| A2 | Header status pill | Green, "API online" | |
| A3 | `https://<render-host>/api/health` | `{"status":"ok","service":"campuslens-api","version":"2.0.0"}` | |
| A4 | Hard reload (`Ctrl+Shift+R`) | App still loads | |

## B. Authentication

| # | Check | Expected | Result |
|---|---|---|---|
| B1 | Sign up as a new student | Account created, no Admin tab | |
| B2 | Sign out, sign back in | Session restored | |
| B3 | Close tab, reopen | Still signed in (session persistence) | |
| B4 | `GET /api/me` as student | `role: "student"` | |
| B5 | `GET /api/me` as admin | `role: "admin"`, `(admin)` in header, Admin tab visible | |
| B6 | Expired/revoked token | `401`, UI prompts sign-in | |

## C. Student flow

| # | Check | Expected | Result |
|---|---|---|---|
| C1 | Submit text + image | 201, appears in `#/mine` | |
| C2 | Submit text only (no image) | 201, no image icon | |
| C3 | Oversized image (>5 MB) | Rejected with a clear message | |
| C4 | Non-image renamed `.jpg` | Rejected - magic-byte validation | |
| C5 | Another student's complaint id | `404`, never `403` or data | |
| C6 | Any `/api/admin/*` call | `403` | |
| C7 | Publish attempt | `403` | |
| C8 | Another user's image | Denied | |

## D. Admin flow

| # | Check | Expected | Result |
|---|---|---|---|
| D1 | Dashboard lists all complaints | Includes other students' | |
| D2 | Confirm scoring inputs | Score and band appear, breakdown shows each factor | |
| D3 | Change status | Persists after reload | |
| D4 | Publish to community feed | Entry appears in `#/community` | |
| D5 | Withdraw from feed | Entry disappears | |
| D6 | Unpublished complaint | Never in the feed | |

## E. Public flow

| # | Check | Expected | Result |
|---|---|---|---|
| E1 | `#/community` with no sign-in | Renders approved entries | |
| E2 | Response fields | Only `id`, `public_summary`, `public_category`, `public_location`, `status`, `approved_at` | |
| E3 | No `student_id`, `priority_score`, `description`, `ai_*` in the response | Absent | |
| E4 | Empty feed | Friendly empty state, no error | |

## F. Resilience

| # | Check | Expected | Result |
|---|---|---|---|
| F1 | Set `AI_ENABLED=false`, redeploy, submit | Still 201, still saved, Unscored | |
| F2 | No `GEMINI_API_KEY` set | Same - submission never calls AI | |
| F3 | Sleep a free-tier service, first request | Slow but succeeds | |

## G. Security

| # | Check | Expected | Result |
|---|---|---|---|
| G1 | Inspect `dist/assets/*.js` for `sb_secret_` / DB URLs / JWTs | None found | |
| G2 | Network tab: any request carrying the service-role key | None | |
| G3 | Request from an unlisted origin | CORS blocks it | |
| G4 | `SUPABASE_SERVICE_ROLE_KEY` absent from all client-side code | Confirmed | |

## H. End-to-end

`Student -> Complaint -> Image -> Backend -> Database -> AI (optional) -> Admin -> Approval -> Public Feed`

| # | Step | Result |
|---|---|---|
| H1 | Student signs in | |
| H2 | Submits complaint with image | |
| H3 | Row exists in Postgres, image in `CLimage` | |
| H4 | Admin scores and sets status | |
| H5 | Admin publishes | |
| H6 | Entry visible publicly, sanitized | |
| H7 | Withdraw, entry gone | |

## Failure log

For any FAIL: observed behaviour, likely cause, safest next action.

| # | Observed | Likely cause | Next action |
|---|---|---|---|
| | | | |
