-- Talon schema for Supabase (PostgreSQL)
-- Run in Supabase SQL Editor, then enable Realtime on `leads` and `searches`.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── Searches (Origami ICP runs) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS searches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  prompt TEXT NOT NULL,
  origami_job_id VARCHAR(255) DEFAULT '',
  status VARCHAR(30) DEFAULT 'running',
  status_message VARCHAR(500) DEFAULT 'Finding leads...',
  lead_count INTEGER DEFAULT 0,
  origami_table_id VARCHAR(64) DEFAULT '',
  origami_table_url VARCHAR(500) DEFAULT '',
  linkedin_message_template TEXT DEFAULT '',
  list_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Leads ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS leads (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
  first_name VARCHAR(120) DEFAULT '',
  last_name VARCHAR(120) DEFAULT '',
  name VARCHAR(255),
  title VARCHAR(255),
  company VARCHAR(255),
  company_size VARCHAR(50),
  email VARCHAR(255),
  linkedin_url VARCHAR(500),
  linkedin_profile_id VARCHAR(255),
  linkedin_member_id VARCHAR(100),
  score INTEGER DEFAULT 5,
  icp_score INTEGER,
  score_reason TEXT,
  source_url VARCHAR(500) DEFAULT '',
  sequence_status VARCHAR(50) DEFAULT 'new',
  tech_stack JSONB DEFAULT '[]'::jsonb,
  status VARCHAR(50) DEFAULT 'new',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_searches_user_id ON searches(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_search_id ON leads(search_id);
CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_email_lower ON leads((lower(email)));

-- ─── Sequences ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sequences (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255),
  type VARCHAR(50),
  connection_note_template TEXT,
  message_template TEXT,
  subject_template TEXT,
  body_template TEXT,
  delay_days INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── LinkedIn outreach log ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS linkedin_outreach_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
  sequence_id UUID REFERENCES sequences(id) ON DELETE SET NULL,
  outreach_type VARCHAR(50),
  content TEXT,
  status VARCHAR(50) DEFAULT 'pending',
  error TEXT,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Emails sent ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS emails_sent (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
  sequence_id UUID REFERENCES sequences(id) ON DELETE SET NULL,
  subject VARCHAR(500),
  body TEXT,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  opened BOOLEAN DEFAULT FALSE,
  replied BOOLEAN DEFAULT FALSE
);

-- ─── Workspaces ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255) NOT NULL,
  icon_letter VARCHAR(2) DEFAULT 'T',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_lists (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  icp_prompt TEXT DEFAULT '',
  status VARCHAR(30) DEFAULT 'idle',
  build_step VARCHAR(255) DEFAULT '',
  row_count INTEGER DEFAULT 0,
  origami_meta JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_list_leads (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  list_id UUID NOT NULL REFERENCES workspace_lists(id) ON DELETE CASCADE,
  lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
  first_name VARCHAR(120) DEFAULT '',
  last_name VARCHAR(120) DEFAULT '',
  title VARCHAR(255) DEFAULT '',
  company VARCHAR(255) DEFAULT '',
  linkedin_url VARCHAR(500) DEFAULT '',
  icp_score INTEGER DEFAULT 0,
  extra JSONB DEFAULT '{}'::jsonb,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Campaigns ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaigns (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
  list_id UUID REFERENCES workspace_lists(id) ON DELETE SET NULL,
  search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
  name VARCHAR(255) NOT NULL,
  connection_note_template TEXT DEFAULT '',
  message_template TEXT DEFAULT '',
  wait_days_after_accept INTEGER DEFAULT 1,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_enrollments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  status VARCHAR(50) DEFAULT 'pending',
  connection_note TEXT,
  follow_up_message TEXT,
  connection_sent_at TIMESTAMPTZ,
  accepted_at TIMESTAMPTZ,
  dm_sent_at TIMESTAMPTZ,
  stopped_reason TEXT,
  last_error TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Agent chat ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_chat_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  list_id UUID REFERENCES workspace_lists(id) ON DELETE CASCADE,
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  role VARCHAR(20),
  content TEXT,
  suggested_actions JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Explore ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS explore_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  icp_prompt TEXT NOT NULL,
  parsed_icp JSONB DEFAULT '{}'::jsonb,
  status VARCHAR(30) DEFAULT 'idle',
  scraper_status JSONB DEFAULT '{}'::jsonb,
  filter_rules JSONB DEFAULT '[]'::jsonb,
  enrichment_columns JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS explore_rows (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES explore_sessions(id) ON DELETE CASCADE,
  company_name VARCHAR(255) NOT NULL,
  website VARCHAR(500) DEFAULT '',
  industry VARCHAR(255) DEFAULT '',
  headcount VARCHAR(50) DEFAULT '',
  location VARCHAR(255) DEFAULT '',
  source VARCHAR(50) DEFAULT '',
  raw_data JSONB DEFAULT '{}'::jsonb,
  fit_score INTEGER DEFAULT 0,
  enrichment JSONB DEFAULT '{}'::jsonb,
  hidden BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS explore_chat_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES explore_sessions(id) ON DELETE CASCADE,
  role VARCHAR(20),
  content TEXT,
  meta JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Realtime + RLS (browser uses publishable key) ───────────────────────────
ALTER PUBLICATION supabase_realtime ADD TABLE leads;
ALTER PUBLICATION supabase_realtime ADD TABLE searches;

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE searches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "searches_select_own" ON searches FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "searches_insert_own" ON searches FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "searches_update_own" ON searches FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "searches_delete_own" ON searches FOR DELETE TO authenticated USING (auth.uid() = user_id);

CREATE POLICY "leads_select_own" ON leads FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "leads_insert_own" ON leads FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "leads_update_own" ON leads FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "leads_delete_own" ON leads FOR DELETE TO authenticated USING (auth.uid() = user_id);
