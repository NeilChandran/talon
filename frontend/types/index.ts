export type LeadStatus = "new" | "contacted" | "replied" | "closed";
export type SequenceType = "connection_request" | "follow_up_message" | "final_message";

export interface Lead {
  id: string;
  name: string;
  title: string | null;
  company: string | null;
  company_size: string | null;
  email: string | null;
  linkedin_url: string | null;
  linkedin_profile_id: string | null;
  linkedin_member_id: string | null;
  icp_score: number | null;
  score_reason: string | null;
  tech_stack: string[];
  status: LeadStatus;
  created_at: string;
}

export interface Sequence {
  id: string;
  name: string;
  type: SequenceType;
  connection_note_template: string;
  message_template: string;
  subject_template?: string;
  body_template?: string;
  delay_days: number;
  created_at: string;
}

export interface LinkedInMessage {
  lead_id: string;
  lead_name: string;
  company: string | null;
  linkedin_url: string | null;
  type: string;
  content: string;
  char_count?: number;
}

export interface AutomationJob {
  status: "pending" | "running" | "completed" | "failed";
  step?: string;
  total: number;
  done: number;
  sent: number;
  failed: number;
  current: string | null;
  error?: string;
  results: Array<{
    lead_id: string;
    name: string;
    status: string;
    content?: string;
    error?: string;
  }>;
}

export interface GeneratedEmail {
  lead_id: string;
  lead_name: string;
  lead_email: string | null;
  company: string | null;
  subject: string;
  body: string;
}

export interface LinkedInSession {
  connected: boolean;
  name?: string;
  headline?: string;
  linkedin_url?: string;
  error?: string;
}

export interface Stats {
  total_leads: number;
  emails_sent: number;
  reply_rate: number;
  leads_this_week: number;
}

export interface ProspectingJob {
  status: "pending" | "running" | "completed" | "failed";
  step: string;
  leads: Partial<Lead>[];
  total: number;
  query: string;
  source?: "linkedin" | "ai" | "signal" | "playwright";
  mode?: string;
  error?: string;
  scraper_status?: Record<string, string>;
}

export type SignalMode = "funded" | "jobs" | "competitor";

// ─── Analytics ────────────────────────────────────────────────────────────────

export interface FunnelStage {
  stage: string;
  count: number;
  pct: number;
}

export interface FunnelData {
  funnel: FunnelStage[];
  total_outreach_sent: number;
  new_this_week: number;
  reply_rate: number;
  contact_rate: number;
}

export interface SequenceStat {
  sequence_id: string;
  name: string;
  type: string;
  sent: number;
  failed: number;
  total: number;
  success_rate: number;
}

export interface DayActivity {
  date: string;
  count: number;
}

export interface SendCapStatus {
  daily_cap: number;
  sent_today: number;
  remaining_today: number;
  is_capped: boolean;
  pct_used: number;
  date: string;
}

export interface ReplyCheckResult {
  checked: number;
  replied: number;
  replied_names: string[];
  error: string | null;
}

// ─── Campaign workspace (origami-style) ───────────────────────────────────────

export type EnrollmentStatus =
  | "drafted"
  | "pending"
  | "connection_sent"
  | "accepted"
  | "dm_sent"
  | "replied"
  | "completed"
  | "stopped"
  | "failed";

export interface Campaign {
  id: string;
  name: string;
  connection_note_template: string;
  message_template: string;
  wait_days_after_accept: number;
  is_active: boolean;
  enrollment_count: number;
  created_at: string;
  updated_at?: string;
}

export interface CampaignEnrollment {
  id: string;
  campaign_id: string;
  lead_id: string;
  status: EnrollmentStatus;
  connection_note: string | null;
  follow_up_message: string | null;
  connection_sent_at: string | null;
  accepted_at: string | null;
  dm_sent_at: string | null;
  stopped_reason: string | null;
  last_error: string | null;
  name: string | null;
  title: string | null;
  company: string | null;
  linkedin_url: string | null;
  lead_status: LeadStatus | null;
  scheduled_at?: string | null;
  origami_send_status?: string | null;
}

export interface SuggestedAction {
  id: string;
  label: string;
  action: string;
}

export interface AgentChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggested_actions: string[];
  created_at: string;
}

export interface AgentChatResponse {
  reply: string;
  suggested_actions: SuggestedAction[];
  campaign_updated: boolean;
}

export interface CampaignJob {
  status: "pending" | "running" | "completed" | "failed" | "paused";
  step?: string;
  total: number;
  done: number;
  sent: number;
  failed: number;
  current: string | null;
  error?: string;
}

// ─── Workspaces (Origami-style) ───────────────────────────────────────────────

export interface Workspace {
  id: string;
  name: string;
  icon_letter: string;
  list_count: number;
  created_at: string | null;
  updated_at: string | null;
  lists?: WorkspaceListMeta[];
}

export interface WorkspaceListMeta {
  id: string;
  name: string;
  status: "idle" | "building" | "ready" | "failed";
  build_step: string;
  row_count: number;
  icp_prompt: string;
  updated_at?: string;
}

export interface ListLeadRow {
  id: string;
  lead_id: string | null;
  first_name: string;
  last_name: string;
  title: string;
  company: string;
  email?: string;
  linkedin_url: string;
  icp_score: number;
  score_reason?: string;
}

export interface WorkspaceListDetail extends WorkspaceListMeta {
  workspace_id: string;
  rows: ListLeadRow[];
  build_job?: { status?: string; step?: string; count?: number; error?: string; origami_table_url?: string };
  origami_meta?: { agentId?: string; tableId?: string; tableUrl?: string; runId?: string };
}

export interface WorkspaceChatResponse {
  reply: string;
  suggested_actions: SuggestedAction[];
  apply_copy?: {
    connection_note_template?: string;
    message_template?: string;
    wait_days_after_accept?: number;
  };
  campaign_id?: string;
}

export interface AppSettings {
  instantly_campaign_id: string;
  linkedin_connection_template?: string;
  linkedin_follow_up_template?: string;
  dry_run: boolean;
  has_serper: boolean;
  has_proxycurl: boolean;
  has_instantly: boolean;
  has_origami?: boolean;
}

export interface LaunchFromListResult {
  campaign_id: string;
  job_id: string;
  enrolled: number;
  status: string;
}

// ─── Explore (Origami-style) ──────────────────────────────────────────────────

export interface ExploreEnrichmentCell {
  value: string;
  status: "loading" | "done" | "error";
  meta?: Record<string, unknown>;
}

export interface ExploreRow {
  id: string;
  company_name: string;
  website: string;
  industry: string;
  headcount: string;
  location: string;
  source: string;
  fit_score: number;
  enrichment: Record<string, ExploreEnrichmentCell>;
  raw_data?: { signals?: string[]; raw_url?: string; sources?: string[] };
  hidden?: boolean;
}

export interface ExploreChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: Record<string, unknown>;
  created_at: string;
}

export interface ExploreSession {
  id: string;
  icp_prompt: string;
  parsed_icp: Record<string, unknown>;
  status: "idle" | "running" | "completed" | "failed";
  scraper_status: Record<string, { status: string; error?: string | null; count: number }>;
  filter_rules: Array<{ field: string; op: string; value: string }>;
  enrichment_columns: Array<{ key: string; type: string; label?: string }>;
  rows: ExploreRow[];
  messages: ExploreChatMsg[];
  created_at: string;
}

export type EnrichmentColumnType =
  | "work_email"
  | "phone"
  | "tech_stack"
  | "funding"
  | "decision_maker_linkedin";
