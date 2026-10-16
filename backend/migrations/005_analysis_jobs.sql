-- ============================================================================
-- CampusLens - migration 005 - analysis_jobs
--
-- The AI reliability mechanism. A complaint row is written FIRST and this job
-- row is created in the same transaction; the worker only ever UPDATES this
-- table. A provider outage can therefore never roll back a complaint.
--
-- Retryable: 503 / 429 / 5xx / timeouts.
-- NOT retryable: 400 (bad model or prompt) and 401 (bad key) - marked failed
-- straight away so an admin sees the real problem instead of a retry loop.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE analysis_jobs;  (destructive)
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    complaint_id  uuid NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    status        text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','succeeded','failed')),
    attempts      int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error    text,
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    provider      text,
    model         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz
);

COMMENT ON TABLE analysis_jobs IS
 'Optional AI analysis queue. The complaint is saved independently of AI this table only tracks whether enrichment has succeeded.';

-- At most one active job per complaint. Without this, two workers could both
-- claim the same complaint and the admin would see analysis twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_jobs_active
    ON analysis_jobs (complaint_id) WHERE status IN ('pending','running');

-- The worker's claim query: due pending jobs, oldest first.
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_claim
    ON analysis_jobs (status, next_retry_at);

-- Admin dashboard view of "what has AI failed to analyse".
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_failed
    ON analysis_jobs (complaint_id) WHERE status = 'failed';

ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;

-- Students may see the status of their own complaint's job, so the UI can say
-- "analysis pending" - but never the raw provider error text.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='analysis_jobs' AND policyname='jobs_own_read'
    ) THEN
        CREATE POLICY jobs_own_read ON analysis_jobs
            FOR SELECT
            USING (EXISTS (
                SELECT 1 FROM complaints c
                WHERE c.id = analysis_jobs.complaint_id
                  AND c.student_id = (SELECT auth.uid())
            ));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='analysis_jobs' AND policyname='jobs_admin_all'
    ) THEN
        CREATE POLICY jobs_admin_all ON analysis_jobs
            FOR ALL
            USING ((SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;