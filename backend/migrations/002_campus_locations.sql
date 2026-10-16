-- ============================================================================
-- CampusLens - migration 002 - campus_locations (+ campus_categories)
--
-- STRUCTURED reference data for recurrence matching. Recurrence groups by
-- (category_code, location_code); free text is never matched.
--
-- *** BOTH TABLES ARE INTENTIONALLY EMPTY. ***
-- No buildings, floors or categories are invented here. Recurrence matching
-- stays DISABLED until the real lists are supplied. Until then every complaint
-- has location_code NULL, which scores 0 recurrence points by definition.
--
-- SAFE TO RE-RUN.  Rollback: DROP TABLE campus_categories; DROP TABLE campus_locations;
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS campus_locations (
    code       text PRIMARY KEY,
    building   text NOT NULL,
    floor      text NOT NULL,
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT campus_locations_building_len CHECK (length(building) BETWEEN 1 AND 120),
    CONSTRAINT campus_locations_floor_len    CHECK (length(floor)    BETWEEN 1 AND 40)
);

COMMENT ON TABLE campus_locations IS
 'Admin-managed building/floor list. Deliberately empty until the real campus inventory is supplied; rows are added by an admin, never by students.';
COMMENT ON COLUMN campus_locations.code IS
  'Stable key used by complaints.location_code. Do not reuse a code.';

-- Fixed category list (decision D16). Students pick from this; AI may only
-- suggest a value from it. Also left empty until the list is supplied.
CREATE TABLE IF NOT EXISTS campus_categories (
    code       text PRIMARY KEY,
    label      text NOT NULL,
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT campus_categories_label_len CHECK (length(label) BETWEEN 2 AND 80)
);

COMMENT ON TABLE campus_categories IS
  'Fixed category vocabulary (D16). Empty until the real list is supplied.';

CREATE INDEX IF NOT EXISTS idx_campus_locations_active
    ON campus_locations (is_active, building, floor);
CREATE INDEX IF NOT EXISTS idx_campus_categories_active
    ON campus_categories (is_active);

ALTER TABLE campus_locations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE campus_categories ENABLE ROW LEVEL SECURITY;

-- Read-only, active rows only. These are non-sensitive reference lists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='campus_locations' AND policyname='locations_active_read'
    ) THEN
        CREATE POLICY locations_active_read ON campus_locations
            FOR SELECT USING (is_active);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname='public'
          AND tablename='campus_categories' AND policyname='categories_active_read'
    ) THEN
        CREATE POLICY categories_active_read ON campus_categories
            FOR SELECT USING (is_active);
    END IF;
END
$$;

COMMIT;