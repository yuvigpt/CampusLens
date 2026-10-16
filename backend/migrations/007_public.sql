-- ============================================================================
-- CampusLens - migration 007 - public_complaints
--
-- The ONLY table the community portal reads. It is a separate, sanitised copy:
--
--   * no student_id      - a reporter can never be identified
--   * no description     - free text can identify a person ("I'm the only woman
--                          on this floor"); only a rewritten summary is stored
--   * no priority_score  - scores and breakdowns are admin-only
--   * no ai_* / confirmed_* - raw analysis is never published
--   * no location_code   - only a generalised public_location string
--
-- Public exposure is opt-in per complaint: a row exists ONLY after an admin
-- approves it. There is no "published" flag to forget to set.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE public_complaints;  (destructive)
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public_complaints (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- UNIQUE: one public entry per complaint. Re-approving updates the row
    -- rather than creating a duplicate.
    source_complaint_id uuid NOT NULL UNIQUE
                        REFERENCES complaints(id) ON DELETE CASCADE,
    public_summary      text NOT NULL CHECK (length(public_summary) BETWEEN 10 AND 1000),
    public_category     text NOT NULL CHECK (length(public_category) BETWEEN 2 AND 80),
    -- Deliberately free text ("Science Block, 2nd floor"), never the internal
    -- location_code, so the public never learns the exact grouping key.
    public_location     text NOT NULL CHECK (length(public_location) BETWEEN 2 AND 160),
    -- Optional and separate from the original: an admin may publish the text
    -- without the photo, or publish a redacted copy instead.
    image_path          text,
    status              text NOT NULL DEFAULT 'Reported'
                        CHECK (status IN ('Reported','In Progress','Resolved')),
    approved_by         uuid REFERENCES profiles(id) ON DELETE SET NULL,
    -- NULLABLE ON PURPOSE: a row with approved_at IS NULL is a DRAFT and stays
    -- invisible to the public. Previously this was NOT NULL DEFAULT now(),
    -- which made `approved_at IS NOT NULL` true for every row and turned the
    -- public_read_approved policy into a no-op.
    approved_at         timestamptz
);

COMMENT ON TABLE public_complaints IS
 'Admin-approved, privacy-safe complaints shown on the community portal Contains no reporter identity and no priority score by construction.';

CREATE INDEX IF NOT EXISTS idx_public_complaints_recent
    ON public_complaints (approved_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_complaints_category
    ON public_complaints (public_category, approved_at DESC);

ALTER TABLE public_complaints ENABLE ROW LEVEL SECURITY;

-- Anonymous read of APPROVED rows only. A row is published only once an admin
-- sets approved_at; a draft (approved_at IS NULL) is filtered out here. This
-- clause is the public approval gate and it is only meaningful because
-- approved_at is nullable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='public_complaints' AND policyname='public_read_approved'
    ) THEN
        CREATE POLICY public_read_approved ON public_complaints
            FOR SELECT
            USING (approved_at IS NOT NULL);
    END IF;
END
$$;

-- Only admins write. Students and anonymous users get no INSERT/UPDATE/DELETE.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='public_complaints' AND policyname='public_admin_all'
    ) THEN
        CREATE POLICY public_admin_all ON public_complaints
            FOR ALL
            USING ((SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;