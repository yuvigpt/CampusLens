# Promoting your account to administrator

Run this **after** the migrations have been applied. It is the ONLY supported
way to become an admin.

There is deliberately no self-service path: no public registration endpoint, no
"role" field on any signup or profile request, and `promote_to_admin()` is
revoked from `PUBLIC`, `anon` and `authenticated`. A student calling it gets
`permission denied for function promote_to_admin`.

## Step 1 - Create your account

Dashboard -> **Authentication** -> **Users** -> **Add user**.

Use your real email. Copy the generated UUID; it looks like
`8f14e45f-ceea-467a-9ba4-1d2f3b4c5d6e`.

## Step 2 - Make sure the profile row exists

Migration `012` creates a `profiles` row automatically for users created
**after** it ran. If you signed up before applying `012`, or you created the
user above, insert the row yourself:

```sql
INSERT INTO public.profiles (id, email, full_name, role)
VALUES (
    '<PASTE-YOUR-AUTH-UUID-HERE>',
    '<PASTE-YOUR-EMAIL-HERE>',
    'Your Name',
    'student'          -- always start as a student
);
```

## Step 3 - Promote the account

Run this in the SQL Editor (as the project owner):

```sql
SELECT public.promote_to_admin('<PASTE-YOUR-AUTH-UUID-HERE>');
```

Expected: `User <uuid> promoted from student to admin.`

The function refuses if no `profiles` row exists, so Step 2 cannot be skipped
silently. Re-running is safe - it reports that the user is already an admin.

## Step 4 - Verify

```sql
SELECT id, email, role FROM public.profiles WHERE role = 'admin';
```

Exactly one row should appear. Do not paste your UUID or email into chat.

## Step 5 - Confirm in the app

Sign out of the frontend, sign back in as the admin, then reload. The header
shows your email followed by `(admin)`, and the **Operations dashboard** tab
appears. That tab only renders when `GET /api/me` returns `role: "admin"` -
the role is read from this table, never from the token.

## Demoting an account

There is no demote helper on purpose. Use SQL and record the change:

```sql
-- 1. Demote the account.
UPDATE public.profiles SET role = 'student' WHERE id = '<uuid>';

-- 2. Record who did it, for the audit trail. Repeat per complaint you want to
--    annotate, or drop this step if an audit entry is not required.
INSERT INTO public.complaint_events
    (complaint_id, actor_id, actor_role, event_type, from_value, to_value)
SELECT c.id, '<your-uuid>', 'admin', 'status_changed', 'admin', 'student'
  FROM public.complaints c
 WHERE c.id = '<the-complaint-id>';

-- 3. Confirm.
SELECT id, email, role FROM public.profiles WHERE id = '<uuid>';
```

The signed-in admin must reload (or sign in again) for the UI to drop the
admin tab: `GET /api/me` is read once per session.

## Security notes

* The backend never reads a role from the client or from a JWT claim. A
  hand-crafted token claiming `role: "admin"` grants nothing.
* Promotion is a deliberate out-of-band act, performed only by someone with
  SQL access to the project.
