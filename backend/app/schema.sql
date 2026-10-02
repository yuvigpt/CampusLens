-- ===========================================================================
-- CampusLens - database schema
--
-- Applied by app/database.py -> init_db(). Safe to re-run: every statement
-- uses IF NOT EXISTS, so existing data is never destroyed.
--
-- All timestamps are stored as UTC text in SQLite's 'YYYY-MM-DD HH:MM:SS'
-- format (produced by datetime('now')). Convert to local time for display only.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS complaints (
    id                                   INTEGER PRIMARY KEY AUTOINCREMENT,

    -- What the student submitted -------------------------------------------
    description                          TEXT NOT NULL,
    location                             TEXT NOT NULL,
    image_path                           TEXT,          -- e.g. uploads/<uuid>.jpg

    -- Gemini's analysis ----------------------------------------------------
    -- Only 'category' and 'issue_summary' are free text; the three levels are
    -- constrained. NULL is allowed on all of them so a complaint can still be
    -- saved when the AI call fails.
    category                             TEXT,
    issue_summary                        TEXT,
    safety_risk                          TEXT CHECK (safety_risk      IN ('Low', 'Medium', 'High')),
    functional_impact                    TEXT CHECK (functional_impact IN ('Low', 'Medium', 'High')),
    urgency                              TEXT CHECK (urgency          IN ('Low', 'Medium', 'High')),
    evidence_from_image                  TEXT,
    uncertainty_or_missing_information   TEXT,

    -- Priority (computed in Python, stored for sorting) ---------------------
    priority_score                       REAL,          -- 0-100
    score_breakdown                      TEXT,          -- JSON string, e.g. {"safety":40,...}

    -- Workflow -------------------------------------------------------------
    status                               TEXT NOT NULL DEFAULT 'Reported'
                                         CHECK (status IN ('Reported', 'In Progress', 'Resolved')),

    -- Lifecycle timestamps (UTC) -------------------------------------------
    created_at                           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                           TEXT,          -- set on status change
    resolved_at                          TEXT           -- set only when status becomes 'Resolved'
);

-- Indexes: the dashboard sorts by priority and filters by status/category.
CREATE INDEX IF NOT EXISTS idx_complaints_status   ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_category ON complaints(category);
CREATE INDEX IF NOT EXISTS idx_complaints_priority ON complaints(priority_score DESC);