# CampusLens - Supabase migration runbook

Apply these in order in the **Supabase SQL Editor**. One file per run. Never
batch them: a mid-way failure would leave the schema half-applied.

> **Use the CURRENT `007_public.sql` on disk.** It makes `approved_at` NULLABLE.
> An older copy with `approved_at NOT NULL DEFAULT now()` disables the public
> approval gate: every row would become visible the instant it was inserted.
> Confirm before you start:
> ```sql
> -- expect: approved_at is nullable
> SELECT column_name, is_nullable, column_default
>   FROM information_schema.columns
>  WHERE table_name='public_complaints' AND column_name='approved_at';
> ```
> Run this AFTER applying 007; before that it reports "no rows".

## Order

| # | File | Creates | Depends on |
|---|---|---|---|
| 1 | `001_profiles.sql` | `profiles`, `is_admin()`, 2 policies | Supabase Auth (`auth.users`) |
| 2 | `002_campus_locations.sql` | `campus_locations`, `campus_categories` (both empty) | - |
| 3 | `003_complaints.sql` | `complaints`, 5 indexes, 3 policies | 001, 002 |
| 4 | `004_complaint_scores.sql` | `complaint_scores` (score history) | 003 |
| 5 | `005_analysis_jobs.sql` | `analysis_jobs` (AI queue) | 003 |
| 6 | `006_events_notes.sql` | `complaint_events`, `investigation_notes` | 003, 001 |
| 7 | `007_public.sql` | `public_complaints` (**nullable `approved_at`**) | 003, 001 |
| 8 | `008_triggers.sql` | `touch_updated_at()` + 2 triggers | 003, 005 |
| 9 | `009_storage_policies.sql` | 4 policies on `storage.objects` | bucket `CLimage` must exist |
| 10 | `010_seed_admin.sql` | `promote_to_admin()`, `admin_bootstrap_status()` | 001 |
| 11 | `012_auto_profile.sql` | `handle_new_user()` + signup trigger | 001 |
| 12 | `013_submission_inserts.sql` (in `supabase/migrations/`) | `events_own_insert`, `jobs_own_insert` (students may append their own audit events and AI jobs) | 003, 005, 006 |
| 13 | `014_ai_writeback.sql` | `store_ai_suggestion()`, `record_job_failure()` - narrow `SECURITY DEFINER` functions so the system identity can persist AI results (raw write-back silently updated 0 rows) | 003, 005 |
| 14 | `015_auto_scoring.sql` | `store_auto_score()` - automatic AI scoring from stored `ai_*` levels (manual urgency/impact/safety confirmation removed; never re-scores, never raises) | 003, 004, 005, 006 |
| 15 | `011_verify.sql` | **VERIFICATION ONLY - nothing is created** | all of the above |

**`012` runs before `011`.** `011` asserts the signup trigger exists, so running
it earlier would report a false failure.

## Before you start

1. Confirm the bucket exists and is **PRIVATE**:
   ```sql
   SELECT name, public FROM storage.buckets WHERE name = 'CLimage';
   -- expect one row, public = false
   ```
2. Confirm `pgcrypto` is available (used by `gen_random_uuid()`):
   ```sql
   SELECT gen_random_uuid() IS NOT NULL AS pgcrypto_ok;
   -- expect true. If false: CREATE EXTENSION IF NOT EXISTS pgcrypto;
   ```

## After each file

Expect **no ERROR**. Then confirm the change landed, for example after `003`:

```sql
SELECT count(*) AS tables_in_public
  FROM information_schema.tables
 WHERE table_schema='public'
   AND table_name IN ('profiles','campus_locations','campus_categories',
                      'complaints','complaint_scores','analysis_jobs',
                      'complaint_events','investigation_notes',
                      'public_complaints');
```

## After the last file (`011_verify.sql`)

Expect the notice:

```
CampusLens Stage 1 verification PASSED
```

Two informational notices are normal before you promote an admin:

* `NO ADMIN YET` - expected until you complete admin promotion
* `D8 CONFIGURED` / `reference tables empty` - only one of these appears

## Then

1. Create your admin account and promote it - see `ADMIN_PROMOTION.md`.
2. Re-run `011_verify.sql`; it should now report
   `OK  admin bootstrap complete (N profiles, 1 admins)`.

## If a migration fails

Stop and read the exact error. Do not re-run blindly and do not add workarounds.

| Error | Meaning |
|---|---|
| `permission denied for schema auth` | Wrong project, or not the owner role |
| `function gen_random_uuid() does not exist` | Enable pgcrypto (see above) |
| `relation "complaints" does not exist` | Out of order - run the missing earlier file |
| `infinite recursion detected in policy` | `is_admin()` lost its `SECURITY DEFINER` - re-run `001` |
