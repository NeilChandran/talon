-- Auth + per-user isolation for searches and leads
-- Run after schema.sql in Supabase SQL Editor

-- Columns
ALTER TABLE searches ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_searches_user_id ON searches(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);

-- Remove permissive policies from initial schema
DROP POLICY IF EXISTS "leads_select_anon" ON leads;
DROP POLICY IF EXISTS "searches_select_anon" ON searches;

-- Searches: authenticated users only see their rows
CREATE POLICY "searches_select_own" ON searches
  FOR SELECT TO authenticated USING (auth.uid() = user_id);

CREATE POLICY "searches_insert_own" ON searches
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

CREATE POLICY "searches_update_own" ON searches
  FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "searches_delete_own" ON searches
  FOR DELETE TO authenticated USING (auth.uid() = user_id);

-- Leads: same
CREATE POLICY "leads_select_own" ON leads
  FOR SELECT TO authenticated USING (auth.uid() = user_id);

CREATE POLICY "leads_insert_own" ON leads
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

CREATE POLICY "leads_update_own" ON leads
  FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "leads_delete_own" ON leads
  FOR DELETE TO authenticated USING (auth.uid() = user_id);
