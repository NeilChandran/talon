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
  source?: "linkedin" | "ai" | "signal";
  mode?: string;
  error?: string;
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
