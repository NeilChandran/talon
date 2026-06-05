# Supabase setup for Talon

1. Open your [Supabase project](https://supabase.com/dashboard) → **SQL Editor**.
2. Paste and run the full contents of [`schema.sql`](./schema.sql).
3. In **Database → Replication**, confirm `leads` and `searches` are enabled for Realtime (the SQL script adds them to `supabase_realtime`).
4. Copy API keys into env files:
   - **backend/.env**: `SUPABASE_URL`, `SUPABASE_KEY` (secret key — `sb_secret_...` or legacy `service_role` JWT)
   - **frontend/.env.local**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable / `anon` key)
5. Run auth migration: [`migrations/002_auth_rls.sql`](./migrations/002_auth_rls.sql)
6. In Supabase Dashboard → **Authentication** → enable **Email** provider
7. Seed defaults: `cd backend && python init_db.py`

If you see `Invalid API key`, use the **Secret** key from Settings → API (not the publishable key on the backend). New keys use the `sb_secret_` prefix (not `ssb_secret_`).
