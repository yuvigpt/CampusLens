-- ============================================================================
-- CampusLens - migration 004 - complaint_scores (score history)
--
-- Decision D9: KEEP history. A row is appended ONLY when an admin confirms
-- the scoring inputs or changes the complaint status - never on every read.
-- Reads recompute age at request time (D5) without writing here.
--
-- This table also carries the values that are expensive to derive and useful
-- to keep for trend analysis: age_days and recurrence_count at that moment.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE complaint_scores;  (destructive)
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS complaint_scores (
    complaint_id uuid NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    age_days     int  NOT NULL CHECK (age_days    >= 0),
    recurrence_count int NOT NULL CHECK (recurrence_count >= 0),
    score        numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
    band         text NOT NULL CHECK (band IN ('Low','Medium','High','Critical')),
    -- band_raw is the pre-floor band. Kept so the safety floor (D3) stays
    -- visible and auditable instead of silently changing the number.
    band_raw     text NOT NULL CHECK (band_raw IN ('Low','Medium','High','Critical')),
    safety_floor_applied boolean NOT NULL DEFAULT false,
    -- What triggered the recomputation.
    trigger_reason text NOT NULL DEFAULT 'admin_confirm'
                   CHECK (trigger_reason IN ('admin_confirm','status_change')),

    PRIMARY KEY (complaint_id, computed_at)
);

COMMENT ON TABLE complaint_scores IS
 'Append-only score history. Rows are written on admin confirmation and on status change only (D9), never during ordinary reads.';

CREATE INDEX IF NOT EXISTS idx_complaint_scores_recent
    ON complaint_scores (complaint_id, computed_at DESC);

ALTER TABLE complaint_scores ENABLE ROW LEVEL SECURITY;

-- History inherits the complaint's audience: an admin sees everything, a
-- student sees only their own complaints' history (never exposed by the API).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaint_scores' AND policyname='scores_admin_all'
    ) THEN
        CREATE POLICY scores_admin_all ON complaint_scores
            FOR ALL
            USING ((SELECT public.is_admin()));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaint_scores' AND policyname='scores_own_read'
    ) THEN
        CREATE POLICY scores_own_read ON complaint_scores
            FOR SELECT
            USING (EXISTS (
                SELECT 1 FROM complaints c
                WHERE c.id = complaint_scores.complaint_id
                  AND c.student_id = (SELECT auth.uid())
            ));
    END IF;
END
$$;

COMMIT;