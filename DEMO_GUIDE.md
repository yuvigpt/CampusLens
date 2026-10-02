# CampusLens — Demo Guide

Quick reference for running and presenting CampusLens during the hackathon.
All commands are PowerShell on the demo machine.

---

## 1. What CampusLens is (30-second version)

Students report campus problems (broken lights, leaks, unsafe wiring) with a
photo. The backend sends the photo + description to **Gemini**, which returns a
7-field analysis (category, summary, safety risk, functional impact, urgency,
image evidence, uncertainty). A **transparent scoring formula** converts that
into a 0–100 priority score and a band (Critical / High / Medium / Low), and an
**operations dashboard** lets staff filter complaints and move them through
Reported → In Progress → Resolved.

Two design rules the app never breaks:

* **If AI analysis fails, the complaint is still saved** — as *Unscored*, never
  given a guessed priority.
* **The score is explainable** — every point is accounted for in the breakdown.

---

## 2. Starting the app (two PowerShell windows)

### Window 1 — Backend (leave running)

```powershell
Set-Location C:\Users\yuvig\Campuslens\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Verify: open <http://127.0.0.1:8000/api/health> →
`{"status":"ok","service":"campuslens-api","version":"1.0.0"}`

> Run from the `backend` folder — that is where the `app` package and `.env`
> live. No `pip install` needed; the venv already has every dependency.

### Window 2 — Frontend (leave running)

```powershell
Set-Location C:\Users\yuvig\Campuslens\frontend
npm run dev
```

Open **<http://localhost:5173>**. The backend only allows the origins
`localhost:5173` and `127.0.0.1:5173`, so use one of those two exactly.

The header pill must read **“API online”** (green). If it is red, click it to
re-check, then see §6.

### Fresh-machine setup (only if venv/node_modules are missing)

```powershell
# backend deps
Set-Location C:\Users\yuvig\Campuslens\backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt
# (if no venv yet: py -m venv venv  then  .\venv\Scripts\python.exe -m pip install -r requirements.txt)

# frontend deps
Set-Location C:\Users\yuvig\Campuslens\frontend
npm install
```

`backend\.env` must contain `GEMINI_API_KEY=...` (template: `.env.example`).
**Never commit or screenshot `.env`.**

---

## 3. Recommended live demo sequence (~4 minutes)

1. **Start state** — open <http://localhost:5173>. Point at the green
   *API online* pill. The dashboard already shows real complaints
   (IDs 1–2): one **Unscored/Reported**, one **51/High/Resolved**.
2. **Student flow** — *Report a problem* → pick a photo (preview appears
   instantly) → type a description and a location → **Submit complaint**.
   Show the disabled button + “Sending the photo to the backend…” spinner
   (repeated clicks do nothing).
3. **Result panel** — when it returns: the stored status, the photo served
   back from the server, the AI’s 7 fields, the **priority badge + score
   meter**, the **breakdown**, and the **uncertainty** note.
4. **Dashboard** — *Operations dashboard*: the new complaint is on top
   (priority sort). Show the analytics tiles and the priority-mix bars
   updating (Total, Unresolved, Resolved, Unscored).
5. **Status update** — on the new card, change Reported → In Progress →
   Resolved. Point out the card reloading and the tiles changing. Press
   **F5** and show the status *stayed* Resolved (persisted in SQLite,
   not just in the browser).
6. **Unscored story** — open complaint **#1**: dashed meter, “No priority
   score”, and the note that it is *never* treated as Low. Point at the
   Unscored tile/bar and the arithmetic “bands + unscored = total”.
7. **Optional resilience** — stop the backend (Ctrl+C): red pill, clear
   error banner with *Try again*. Restart the backend, click the pill →
   green again. Nothing is lost.

---

## 4. What to tell the judges

* **AI analysis (Gemini):** one multimodal call returns exactly seven typed
  fields — category, issue summary, safety risk, functional impact, urgency,
  evidence from the image, and *uncertainty / missing information*. The
  response is schema-validated before it is trusted.
* **Explainable priority scoring:** score = safety (≤40) + impact (≤25) +
  urgency (≤25) + category weight (≤10) = 0–100 → Critical 75+, High 50–74,
  Medium 25–49, Low 0–24. Every complaint shows *why* it got its score; the
  formula lives in `backend/app/priority.py` with unit tests covering it.
* **Uncertainty is surfaced, not hidden:** the model’s own uncertainty text
  is shown verbatim on the result panel.
* **Unscored = honest failure handling:** if the Gemini call fails (quota,
  network, bad output), the complaint is *still saved* with a visible warning
  and no score — counted separately in analytics, never demoted to “Low”.
* **Verification you can run live:**

  ```powershell
  # offline test suite (172 tests, no network, no API key needed)
  Set-Location C:\Users\yuvig\Campuslens
  .\backend\venv\Scripts\python.exe -m unittest discover -s backend/tests -t backend
  ```

  ```powershell
  # production frontend build
  Set-Location C:\Users\yuvig\Campuslens\frontend
  npm run build
  ```

  ⚠️ Use **exactly** `-s backend/tests -t backend`. A bare `test_gemini.py`
  in the `backend` folder is a manual smoke script that makes a **real** API
  call — never run discovery from the `backend` folder root.

---

## 5. Known limitations (say these honestly)

* **Analysis latency:** a submission waits for Gemini (typically 1–10 s,
  90 s hard timeout). There is no background queue; the spinner is shown the
  whole time. Do a warm-up submission before the judges arrive.
* **Free Gemini key limits:** if quota runs out mid-demo, submissions still
  succeed — as *Unscored* with a warning. That is the designed fallback.
* **No authentication:** anyone can submit or change status. It is a demo,
  not a production system.
* **Single-machine demo:** CORS allows only `localhost:5173` /
  `127.0.0.1:5173`, so the browser and servers must run on the same machine.
* **Storage is local:** SQLite file (`backend/campuslens.db`) + photos in
  `backend/uploads/`. No cloud sync, no backups.
* **Analytics aggregation** runs in Python per request — fine at hackathon
  scale, not tuned for thousands of rows.
* **No features beyond the brief:** no auth, maps, email/SMS notifications,
  or real-time websockets.

---

## 6. Troubleshooting

| Symptom | Cause & fix |
| --- | --- |
| Backend won’t start: `error while attempting to bind on address ... :8000` | An old uvicorn is still running. It is probably fine — open <http://127.0.0.1:8000/api/health>. To kill it: `Get-NetTCPConnection -LocalPort 8000 -State Listen \| Select-Object -ExpandProperty OwningProcess` then `Stop-Process -Id <pid> -Force`, and start fresh. |
| Backend exits: `ModuleNotFoundError: No module named 'app'` | You ran uvicorn from the wrong folder. `Set-Location C:\Users\yuvig\Campuslens\backend` first. |
| Frontend won’t start: `Port 5173 is already in use` | Another Vite (often an old window) holds the port — `strictPort` refuses to move. Find and close it: `Get-NetTCPConnection -LocalPort 5173 -State Listen \| Select-Object -ExpandProperty OwningProcess` → `Stop-Process -Id <pid> -Force`. |
| Header pill is red: “API unreachable” | Backend not running, or it crashed. Check Window 1 for a traceback and the health URL above, then click the pill. |
| Console: CORS error / blocked by CORS policy | The page was opened via a LAN IP, another port, or `file://`. Use exactly <http://localhost:5173>. |
| Submit fails: “Cannot reach the CampusLens API at …” | Backend stopped while the page was open. Restart it (§2) and retry — form input is preserved. |
| Submission saved but shows **Unscored** + warning | Gemini failed (key, quota, network). Read the warning on the result panel — the complaint is safely stored and will score normally once the key works. |
| “Image is larger than the 8 MB limit” / upload rejected | Use a smaller photo (JPEG/PNG/WebP ≤ 8 MB) — the form pre-validates this too. |
| PowerShell blocks `.\venv\Scripts\Activate.ps1` | Activation isn’t needed: call the interpreter by full path, as in every command in this guide. |
| Old behavior / stale UI after a change | Old uvicorn or Vite still running: kill the processes above, restart both windows, then Ctrl+Shift+R. |

**Reset for a clean re-demo:** never delete the database as part of normal
demoing. Existing complaints are real demo data — status changes are safe,
submissions accumulate safely. (A full factory reset would be moving
`backend/campuslens.db` aside while both servers are stopped — do it only if
judges never saw the data.)

