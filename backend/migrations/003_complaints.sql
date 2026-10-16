-- ============================================================================
-- CampusLens - migration 003 - complaints
--
-- THE central table. Two rules are enforced by the COLUMN LAYOUT itself:
--
--   ai_*        AI suggestion. Advisory only. NEVER read by the scorer.
--   confirmed_* Admin-confirmed. The ONLY human-set inputs to the score.
--
-- An AI response therefore cannot move a score, because there is no column
-- the scorer reads that AI is allowed to write.
--
-- The five-factor formula (Urgency 0-30, Impact 0-25, Recurrence 0-20,
-- Age 0-15, Safety 0-10) has NO category-weight column - that concept is gone.
--
-- priority_score NULL  => Unscored (D7). A stored 0 is a REAL score.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE complaints;  (destructive)
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS complaints (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id   uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    description  text NOT NULL
                 CHECK (length(description) BETWEEN 10 AND 4000),   -- D15
    -- Free text the student typed. Never used for recurrence matching.
    location_raw text NOT NULL
                 CHECK (length(location_raw) BETWEEN 2 AND 200),
    -- Structured key for recurrence. NULL while campus_locations is empty
    -- => recurrence is "not applicable" => 0 points (D10).
    location_code text REFERENCES campus_locations(code) ON DELETE SET NULL,
    -- Admin may exclude an outlier from grouping entirely.
    recurrence_na boolean NOT NULL DEFAULT false,
    image_path   text,

    -- ---- AI suggestion (advisory; admin must confirm before it counts) ----
    ai_category   text,
    ai_summary    text,
    ai_evidence   text,
    ai_uncertainty text,
    ai_urgency    text CHECK (ai_urgency IN ('Low','Medium','High')),
    ai_impact     text CHECK (ai_impact  IN ('Low','Medium','High')),
    ai_safety     text CHECK (ai_safety  IN ('Low','Medium','High')),

    -- ---- Admin-confirmed: the ONLY scorer inputs ----
    confirmed_urgency text CHECK (confirmed_urgency IN ('Low','Medium','High')),
    confirmed_impact  text CHECK (confirmed_impact  IN ('Low','Medium','High')),
    confirmed_safety  text CHECK (confirmed_safety  IN ('Low','Medium','High')),
    analysis_confirmed_at timestamptz,
    confirmed_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,

    -- ---- Score (admin-only; never returned by student or public APIs) ----
    priority_score    numeric(5,2) CHECK (priority_score BETWEEN 0 AND 100),
    score_breakdown   jsonb,          -- nested, validated by Pydantic (D6)
    score_version     text NOT NULL DEFAULT 'v1',
    score_computed_at timestamptz,    -- set whenever the score is recomputed

    status       text NOT NULL DEFAULT 'Reported'
                 CHECK (status IN ('Reported','In Progress','Resolved')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);

COMMENT ON COLUMN complaints.score_breakdown IS
 'Nested JSON: urgency/impact/safety {level,points,max}, recurrence {count,points,max,window_days,key,not_applicable}, age {days,points,max, computed_at}, plus total, band, band_raw, safety_floor_applied, max_possible, scored_at, version.';
COMMENT ON COLUMN complaints.score_breakdown IS
 'Nested JSON: urgency/impact/safety {level,points,max}, recurrence {count,points,max,window_days,key,not_applicable}, age {days,points,max, computed_at}, plus total, band, band_raw, safety_floor_applied, max_possible, scored_at, version.';

-- Sorting and filtering the admin dashboard.
CREATE INDEX IF NOT EXISTS idx_complaints_student ON complaints (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_complaints_status  ON complaints (status);
-- NULLS LAST so Unscored rows sort after every real score, including 0.
CREATE INDEX IF NOT EXISTS idx_complaints_score   ON complaints (priority_score DESC NULLS LAST);
-- Supports the recurrence snapshot query (D5): 90-day window per location.
CREATE INDEX IF NOT EXISTS idx_complaints_location
    ON complaints (location_code, created_at DESC);
-- Partial index: only rows that still need analysis. Stays tiny.
CREATE INDEX IF NOT EXISTS idx_complaints_unscored
    ON complaints (created_at DESC) WHERE priority_score IS NULL;

ALTER TABLE complaints ENABLE ROW LEVEL SECURITY;

-- A student may read ONLY their own complaints. Scores are filtered by the
-- API response schema, not by this policy.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaints' AND policyname='complaints_own_read'
    ) THEN
        CREATE POLICY complaints_own_read ON complaints
            FOR SELECT
            USING (student_id = (SELECT auth.uid()));
    END IF;
END
$$;

-- A student may insert their own complaint - and only their own.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaints' AND policyname='complaints_own_insert'
    ) THEN
        CREATE POLICY complaints_own_insert ON complaints
            FOR INSERT
            WITH CHECK (student_id = (SELECT auth.uid()));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaints' AND policyname='complaints_admin_all'
    ) THEN
        CREATE POLICY complaints_admin_all ON complaints
            FOR ALL
            USING ((SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;