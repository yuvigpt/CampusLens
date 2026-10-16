-- ============================================================================
-- CampusLens - migration 006 - complaint_events + investigation_notes
--
-- complaint_events : append-only audit trail. Answers "who changed this and
--                    when" for status changes, confirmations and approvals.
-- investigation_notes : admin and AI notes. author_kind distinguishes them so
--                    AI output is never mistaken for an admin decision.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE investigation_notes; DROP TABLE complaint_events;
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS complaint_events (
    id           bigserial PRIMARY KEY,
    complaint_id uuid NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    -- SET NULL, not CASCADE: losing an admin must not erase the audit trail.
    actor_id     uuid REFERENCES profiles(id) ON DELETE SET NULL,
    actor_role   text NOT NULL CHECK (actor_role IN ('student','admin','system','ai')),
    event_type   text NOT NULL CHECK (event_type IN (
                      'created', 'status_changed', 'analysis_confirmed',
                      'scored', 'public_approved', 'public_revoked',
                      'ai_retried', 'note_added')),
    from_value   text,
    to_value     text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE complaint_events IS
  'Append-only audit trail. Rows are never updated or deleted by the app.';

CREATE INDEX IF NOT EXISTS idx_complaint_events_timeline
    ON complaint_events (complaint_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_complaint_events_recent
    ON complaint_events (created_at DESC);

CREATE TABLE IF NOT EXISTS investigation_notes (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    complaint_id uuid REFERENCES complaints(id) ON DELETE CASCADE,
    author_id    uuid REFERENCES profiles(id) ON DELETE SET NULL,
    author_kind  text NOT NULL CHECK (author_kind IN ('admin','ai')),
    body         text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    created_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE investigation_notes IS
 'Admin notes and AI investigation output, kept visibly distinct. The Cline agent writes here only; it has no tool that can modify complaints.';

CREATE INDEX IF NOT EXISTS idx_investigation_notes_complaint
    ON investigation_notes (complaint_id, created_at DESC);

ALTER TABLE complaint_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigation_notes ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaint_events' AND policyname='events_admin_all'
    ) THEN
        CREATE POLICY events_admin_all ON complaint_events
            FOR ALL USING ((SELECT public.is_admin()));
    END IF;
END
$$;

-- Students may read the history of their own complaint only.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='complaint_events' AND policyname='events_own_read'
    ) THEN
        CREATE POLICY events_own_read ON complaint_events
            FOR SELECT
            USING (EXISTS (
                SELECT 1 FROM complaints c
                WHERE c.id = complaint_events.complaint_id
                  AND c.student_id = (SELECT auth.uid())
            ));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='investigation_notes' AND policyname='notes_admin_all'
    ) THEN
        CREATE POLICY notes_admin_all ON investigation_notes
            FOR ALL USING ((SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;