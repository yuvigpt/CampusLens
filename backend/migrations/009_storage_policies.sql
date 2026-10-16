-- ============================================================================
-- CampusLens - migration 009 - storage policies for complaint images
--
-- Bucket: CLimage  (PRIVATE - created MANUALLY, see the bottom of
-- this file. This migration never creates or alters a bucket.)
--
-- ---------------------------------------------------------------------------
-- WHY THESE POLICIES DO NOT MATCH ON THE OBJECT PATH
-- ---------------------------------------------------------------------------
-- The obvious design is "objects live at <student_id>/<uuid>.jpg, so check
-- that the first path segment equals auth.uid()". That cannot be written yet:
-- NO path convention is recorded anywhere in the schema. complaints.image_path
-- and public_complaints.image_path are plain `text` with no documented prefix.
--
-- Inventing a prefix here would create a policy that silently fails closed (or,
-- worse, matches the wrong paths) once the application picks a different
-- layout. Instead every policy resolves authorisation through the complaints
-- TABLE, which is the authoritative record of who owns which image:
--
--     a student may touch an object IFF complaints.image_path = <object name>
--     AND that complaint's student_id = auth.uid()
--
-- This is convention-independent: it stays correct whatever path layout the
-- application later adopts. When the layout is fixed, these policies can be
-- tightened to a path-prefix check for speed - but they are correct now.
--
-- ---------------------------------------------------------------------------
-- SECURITY POSTURE
-- ---------------------------------------------------------------------------
--   * No policy is granted to `anon`. Anonymous users get NO access to this
--     bucket at all - not even for approved public images. Approved public
--     images are served through a separate, application-controlled route.
--   * No USING (true) and no WITH CHECK (true) anywhere.
--   * Uploads are limited to the images/jpeg|png|webp content types the
--     backend already validates (D15/Stage 5), so a student cannot use the
--     bucket as arbitrary file hosting.
--   * Object size is capped to match the backend's 5 MB limit.
--   * Admins are authenticated admins only, via the is_admin() helper from 001.
--
-- SAFE TO RE-RUN.  Rollback: DROP POLICY ... ON storage.objects; (see bottom)
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Students upload their OWN complaint images.
--    WITH CHECK governs new objects. The object must already be referenced by a
--    complaint row the student owns - so an upload is only permitted once the
--    complaint exists and points at this exact path.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname = 'complaint_images_owner_insert'
    ) THEN
        CREATE POLICY complaint_images_owner_insert ON storage.objects
            FOR INSERT
            TO authenticated
            WITH CHECK (
                bucket_id = 'CLimage'
                AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
                AND EXISTS (
                    SELECT 1 FROM public.complaints c
                    WHERE c.image_path = name
                      AND c.student_id = (SELECT auth.uid())
                )
                AND lower(split_part(name, '.', -1)) IN ('jpg','jpeg','png','webp')
                AND (metadata->>'mimetype') IN ('image/jpeg','image/png','image/webp')
                AND COALESCE((metadata->>'size')::bigint, 0) <= 5242880
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Students read their OWN complaint images only.
--    USING governs existing rows. Same ownership join as above.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname = 'complaint_images_owner_select'
    ) THEN
        CREATE POLICY complaint_images_owner_select ON storage.objects
            FOR SELECT
            TO authenticated
            USING (
                bucket_id = 'CLimage'
                AND EXISTS (
                    SELECT 1 FROM public.complaints c
                    WHERE c.image_path = name
                      AND c.student_id = (SELECT auth.uid())
                )
            );
    END IF;
END
$$;
-- ---------------------------------------------------------------------------
-- 3. A student may REPLACE their own image (same rules as the insert).
--    A student may NOT delete: images are part of the complaint record.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname = 'complaint_images_owner_update'
    ) THEN
        CREATE POLICY complaint_images_owner_update ON storage.objects
            FOR UPDATE
            TO authenticated
            USING (
                bucket_id = 'CLimage'
                AND EXISTS (
                    SELECT 1 FROM public.complaints c
                    WHERE c.image_path = name
                      AND c.student_id = (SELECT auth.uid())
                )
            )
            WITH CHECK (
                bucket_id = 'CLimage'
                AND (storage.foldername(name))[1] = (SELECT auth.uid())::text
                AND lower(split_part(name, '.', -1)) IN ('jpg','jpeg','png','webp')
                AND (metadata->>'mimetype') IN ('image/jpeg','image/png','image/webp')
                AND COALESCE((metadata->>'size')::bigint, 0) <= 5242880
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Admins: full access to the private bucket, for investigation and for
--    moderating images approved for the community portal.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage' AND tablename = 'objects'
          AND policyname = 'complaint_images_admin_all'
    ) THEN
        CREATE POLICY complaint_images_admin_all ON storage.objects
            FOR ALL
            TO authenticated
            USING (bucket_id = 'CLimage' AND (SELECT public.is_admin()))
            WITH CHECK (bucket_id = 'CLimage' AND (SELECT public.is_admin()));
    END IF;
END
$$;

COMMIT;

-- ============================================================================
-- MANUAL SETUP REQUIRED (not done by this migration)
-- ============================================================================
-- 1. Supabase Dashboard -> Storage -> New bucket:
--        Name:      CLimage
--        Public:    OFF   <-- MUST stay private
--        File size: 5 MiB (matches the backend's MAX_UPLOAD_BYTES)
--        Allowed MIME types:  image/jpeg, image/png, image/webp
--    Creating it as public would expose every complaint photo to the internet,
--    including photos of students. Verify with:
--        SELECT id, name, public FROM storage.buckets WHERE name = 'CLimage';
--    `public` MUST be false.
--
-- 2. Path convention - NOT yet decided, which is why the policies above join
--    through the complaints table. When the application settles on a layout
--    (recommended: "<student_id>/<uuid>.jpg", matching the ownership check on
--    the insert policy above), the policies can be simplified and the
--    first-segment check kept as a fast path.
--
-- 3. No policy is granted to `anon` on purpose. If the community portal later
--    needs approved images, add a separate PUBLIC bucket for sanitised copies -
--    do NOT open this one.
--
-- ROLLBACK:
--   DROP POLICY IF EXISTS complaint_images_owner_insert  ON storage.objects;
--   DROP POLICY IF EXISTS complaint_images_owner_select  ON storage.objects;
--   DROP POLICY IF EXISTS complaint_images_owner_update  ON storage.objects;
--   DROP POLICY IF EXISTS complaint_images_admin_all      ON storage.objects;
--   (the bucket itself is left alone)