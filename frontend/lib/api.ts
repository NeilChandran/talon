import type {
  AgentChatMessage,
  AgentChatResponse,
  AutomationJob,
  Campaign,
  CampaignEnrollment,
  CampaignJob,
  ExploreSession,
  AppSettings,
  LaunchFromListResult,
  ListLeadRow,
  Workspace,
  WorkspaceChatResponse,
  WorkspaceListDetail,
  WorkspaceListMeta,
  DayActivity,
  FunnelData,
  Lead,
  LeadStatus,
  LinkedInMessage,
  LinkedInSession,
  ProspectingJob,
  ReplyCheckResult,
  SendCapStatus,
  Sequence,
  SequenceStat,
  SequenceType,
  SignalMode,
  Stats,
} from "@/types";

import { getAccessToken } from "@/lib/supabase";

const BASE = "/api";

async function authHeaders(): Promise<HeadersInit> {
  const token = await getAccessToken();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text);
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg?: string }) => d.msg).join(", ");
    if (j.error) return String(j.error);
    if (j.message) return String(j.message);
  } catch {
    /* not json */
  }
  if (text.includes("ECONNREFUSED") || res.status === 502 || res.status === 503) {
    return "Cannot reach Talon API — start the backend: run scripts/start.sh (port 8000)";
  }
  if (res.status === 404) {
    return "API route not found — restart the backend (./scripts/start.sh) so /searches is available";
  }
  if (res.status === 500 && text === "Internal Server Error") {
    return "Server error — restart with ./scripts/start.sh (check backend terminal for details)";
  }
  return text.slice(0, 200) || `Request failed (${res.status})`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  const headers = await authHeaders();
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: { ...headers, ...(options?.headers as Record<string, string>) },
    });
  } catch {
    throw new Error(
      "Connection failed — Talon API is not running. Open a terminal and run: ./hedwig-outreach/scripts/start.sh"
    );
  }
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json();
}

// ─── LinkedIn Auth ────────────────────────────────────────────────────────────

export const getLinkedInStatus = () =>
  request<LinkedInSession>("/linkedin/session/status");

export const connectLinkedIn = (li_at: string, jsessionid: string, bcookie: string, bscookie: string) =>
  request<LinkedInSession>("/linkedin/session", {
    method: "POST",
    body: JSON.stringify({ li_at, jsessionid, bcookie, bscookie }),
  });

// Opens a real Chrome window for the user to log in — waits up to 3 minutes
export const loginWithLinkedInBrowser = async (): Promise<LinkedInSession> => {
  let res: Response;
  try {
    res = await fetch("/api/linkedin/session/browser-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(210_000),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.includes("aborted") || msg.includes("timeout")) {
      throw new Error("Login timed out — finish signing in to LinkedIn within 3 minutes");
    }
    throw new Error(
      "Connection failed — start the backend first (./hedwig-outreach/scripts/start.sh)"
    );
  }
  const data = (await res.json()) as LinkedInSession & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || (await parseError(res)));
  }
  if (!data.connected) {
    throw new Error(data.error || "LinkedIn login failed");
  }
  return data;
};

export const disconnectLinkedIn = () =>
  request<{ connected: boolean }>("/linkedin/session", { method: "DELETE" });

export const testLinkedInSession = () =>
  request<LinkedInSession>("/linkedin/session/test");

// ─── Leads ───────────────────────────────────────────────────────────────────

export const getStats = () => request<Stats>("/leads/stats");

export const getRecentLeads = (limit = 10) =>
  request<Lead[]>(`/leads/recent?limit=${limit}`);

export const getLeads = (params?: {
  status?: LeadStatus;
  min_score?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
}) => {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
  }
  return request<Lead[]>(`/leads?${qs.toString()}`);
};

export const updateLeadStatus = (id: string, status: LeadStatus) =>
  request<Lead>(`/leads/${id}`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });

export const deleteLead = (id: string) =>
  request<{ message: string }>(`/leads/${id}`, { method: "DELETE" });

export const deleteAllLeads = () =>
  request<{ message: string }>("/leads", { method: "DELETE" });

// ─── Prospecting ─────────────────────────────────────────────────────────────

export const startProspecting = (query: string) =>
  request<{ job_id: string; status: string }>("/prospecting/search", {
    method: "POST",
    body: JSON.stringify({ query }),
  });

export const startSignalProspecting = (mode: SignalMode) =>
  request<{ job_id: string; status: string; mode: string }>(
    `/prospecting/signal?mode=${mode}`,
    { method: "POST" }
  );

export const getProspectingStatus = (jobId: string) =>
  request<ProspectingJob>(`/prospecting/status/${jobId}`);

// ─── LinkedIn Outreach ────────────────────────────────────────────────────────

export type InboxItem = {
  id: string;
  enrollment_id: string;
  lead_id: string;
  campaign_id: string;
  search_id: string;
  recipient: string;
  name: string;
  title: string;
  company: string;
  linkedin_url: string;
  campaign_name: string;
  search_prompt: string;
  status: "draft" | "scheduled" | "sent" | "in_progress" | "replied" | "failed" | "stopped";
  status_label: string;
  enrollment_status: string;
  origami_send_status?: string | null;
  scheduled_at?: string | null;
  connection_note: string;
  follow_up_message: string;
  activity_at?: string | null;
  activity_label: string;
  last_error?: string | null;
};

export type InboxStats = {
  all: number;
  replies: number;
  sent_week: number;
  draft?: number;
  scheduled?: number;
  sent?: number;
  in_progress?: number;
};

export const getInbox = (sync = false) =>
  request<{ items: InboxItem[]; stats: InboxStats }>(
    `/outreach/inbox${sync ? "?sync=1" : ""}`
  );

export const syncInbox = () =>
  request<{ ok: boolean; items: number; stats: InboxStats }>("/outreach/inbox/sync", {
    method: "POST",
  });

export const generateLinkedInMessages = (
  leadIds: string[],
  sequenceType: string
) =>
  request<{ messages: LinkedInMessage[]; count: number }>("/outreach/generate-linkedin", {
    method: "POST",
    body: JSON.stringify({ lead_ids: leadIds, sequence_type: sequenceType }),
  });

// ─── Sequences ────────────────────────────────────────────────────────────────

export const getSequences = () => request<Sequence[]>("/sequences");

export const createSequence = (data: {
  name: string;
  type: SequenceType;
  connection_note_template: string;
  message_template: string;
  delay_days: number;
}) =>
  request<Sequence>("/sequences", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateSequence = (id: string, data: Partial<Sequence>) =>
  request<Sequence>(`/sequences/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const deleteSequence = (id: string) =>
  request<{ message: string }>(`/sequences/${id}`, { method: "DELETE" });

export const runSequence = (sequenceId: string, leadIds: string[]) =>
  request<{ job_id: string; status: string; total: number }>(
    `/sequences/${sequenceId}/run`,
    {
      method: "POST",
      body: JSON.stringify({ sequence_id: sequenceId, lead_ids: leadIds }),
    }
  );

export const getAutomationJob = (jobId: string) =>
  request<AutomationJob>(`/sequences/jobs/${jobId}`);

// ─── Reply detection ──────────────────────────────────────────────────────────

export const checkReplies = () =>
  request<ReplyCheckResult>("/sequences/check-replies", { method: "POST" });

export const getSendCap = () =>
  request<SendCapStatus>("/sequences/send-cap");

// ─── Analytics ────────────────────────────────────────────────────────────────

export const getAnalyticsFunnel = () =>
  request<FunnelData>("/analytics/funnel");

export const getAnalyticsSequences = () =>
  request<SequenceStat[]>("/analytics/sequences");

export const getAnalyticsDailyActivity = () =>
  request<DayActivity[]>("/analytics/daily-activity");

export const getAnalyticsSendCap = () =>
  request<SendCapStatus>("/analytics/send-cap");

// ─── Campaigns (workspace) ────────────────────────────────────────────────────

export const getCampaigns = () => request<Campaign[]>("/campaigns");

export const getCampaign = (id: string) => request<Campaign>(`/campaigns/${id}`);

export const createCampaign = (data: Partial<Campaign>) =>
  request<Campaign>("/campaigns", { method: "POST", body: JSON.stringify(data) });

export const updateCampaign = (id: string, data: Partial<Campaign>) =>
  request<Campaign>(`/campaigns/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const getCampaignEnrollments = (campaignId: string) =>
  request<CampaignEnrollment[]>(`/campaigns/${campaignId}/enrollments`);

export const enrollLeadsInCampaign = (campaignId: string, leadIds?: string[]) =>
  request<{ enrolled: number; total_leads: number }>(`/campaigns/${campaignId}/enroll`, {
    method: "POST",
    body: JSON.stringify({ lead_ids: leadIds ?? null }),
  });

export const launchCampaign = (campaignId: string) =>
  request<{ job_id: string; status: string }>(`/campaigns/${campaignId}/launch`, {
    method: "POST",
  });

export const getCampaignJob = (jobId: string) =>
  request<CampaignJob>(`/campaigns/jobs/${jobId}`);

export const syncCampaign = (campaignId: string) =>
  request<{ status: string }>(`/campaigns/${campaignId}/sync`, { method: "POST" });

export const stopEnrollment = (campaignId: string, enrollmentId: string) =>
  request<{ status: string }>(
    `/campaigns/${campaignId}/enrollments/${enrollmentId}/stop`,
    { method: "POST" }
  );

// ─── AI Agent ─────────────────────────────────────────────────────────────────

export const getAgentHistory = (campaignId?: string) => {
  const qs = campaignId ? `?campaign_id=${campaignId}` : "";
  return request<AgentChatMessage[]>(`/agent/history${qs}`);
};

export const sendAgentMessage = (message: string, campaignId?: string) =>
  request<AgentChatResponse>("/agent/chat", {
    method: "POST",
    body: JSON.stringify({ message, campaign_id: campaignId ?? null }),
  });

// ─── Searches (Origami → Instantly) ───────────────────────────────────────────

export interface RecentSearch {
  id: string;
  prompt: string;
  status: string;
  status_message?: string;
  lead_count: number;
  created_at: string | null;
}

export interface OutreachKit {
  linkedin_connection: string;
  email_subject: string;
  email_step1: string;
  email_step2: string;
  email_step3: string;
  channel_hint: string;
  targets_founders: boolean;
}

export interface SearchLead {
  id: string;
  search_id: string | null;
  first_name: string;
  last_name: string;
  title: string;
  company: string;
  email: string;
  linkedin_url: string;
  score: number;
  sequence_status: string;
  created_at: string | null;
  linkedin_message?: string;
  email_preview?: string;
  linkedin_outreach_status?: string;
  linkedin_outreach_label?: string;
}

export interface SearchProgress {
  percent: number;
  label: string;
  step: number | null;
  max_steps: number | null;
  leads_found: number;
  target_leads: number;
  status: string;
}

export interface SearchDetail {
  id: string;
  prompt: string;
  origami_job_id: string;
  status: string;
  status_message: string;
  lead_count: number;
  origami_table_url: string;
  linkedin_message_template?: string;
  created_at: string | null;
  leads: SearchLead[];
  job?: { status?: string; step?: string; count?: number; error?: string };
  outreach?: OutreachKit;
  progress?: SearchProgress;
}

export const createSearch = (prompt: string) =>
  request<SearchDetail>("/searches/", { method: "POST", body: JSON.stringify({ prompt }) });

export const getRecentSearches = () => request<RecentSearch[]>("/searches/recent");

export const deleteSearch = (id: string) =>
  request<{ ok: boolean; id: string }>(`/searches/${id}`, { method: "DELETE" });

export const getSearch = (id: string) => request<SearchDetail>(`/searches/${id}`);

/** Returns null when workspace was deleted — avoids crashing the search page. */
export async function getSearchOrNull(id: string): Promise<SearchDetail | null> {
  try {
    return await getSearch(id);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.toLowerCase().includes("not found")) return null;
    throw e;
  }
}

export const resumeSearch = (id: string) =>
  request<{ ok: boolean; id: string; status: string }>(`/searches/${id}/resume`, { method: "POST" });

export const refreshSearchLeads = (id: string) =>
  request<{ ok: boolean; lead_count: number; message: string }>(`/searches/${id}/refresh`, {
    method: "POST",
  });

export const setSearchLinkedInTemplate = (id: string, template: string) =>
  request<{ ok: boolean; outreach: OutreachKit }>(`/searches/${id}/linkedin-template`, {
    method: "PATCH",
    body: JSON.stringify({ template }),
  });

export const searchAgentMessage = (id: string, message: string) =>
  request<{ ok: boolean; reply: string; outreach: OutreachKit }>(`/searches/${id}/agent-message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });

export const prepareSearchCampaign = (searchId: string) =>
  request<{
    ok: boolean;
    campaign_id: string;
    campaign: {
      id: string;
      name: string;
      connection_note_template: string;
      message_template: string;
      wait_days_after_accept: number;
    };
    enrollments: import("@/types").CampaignEnrollment[];
    count: number;
  }>(`/searches/${searchId}/campaign/prepare`, { method: "POST" });

export const launchOrigamiCampaign = (searchId: string) =>
  request<{ job_id: string; status: string; campaign_id: string; ready_count: number }>(
    `/searches/${searchId}/campaign/launch-origami`,
    { method: "POST" }
  );

export const sendSearchLinkedIn = (
  searchId: string,
  data?: {
    lead_ids?: string[];
    connection_note_template?: string;
    message_template?: string;
    campaign_name?: string;
  }
) =>
  request<{
    campaign_id: string;
    job_id: string;
    enrolled: number;
    status: string;
    message: string;
  }>(`/searches/${searchId}/send/linkedin`, { method: "POST", body: JSON.stringify(data ?? {}) });

export function searchExportCsvUrl(searchId: string) {
  return `/api/searches/${searchId}/export.csv`;
}

export const pushSearchToInstantly = (
  searchId: string,
  data?: { lead_ids?: string[]; subject?: string; step1_body?: string; step2_body?: string; step3_body?: string }
) =>
  request<{ pushed: number; skipped: number; errors: string[]; dry_run?: boolean }>(
    `/searches/${searchId}/instantly`,
    { method: "POST", body: JSON.stringify(data ?? {}) }
  );

// ─── Workspaces (legacy) ──────────────────────────────────────────────────────

export const getWorkspaces = () => request<Workspace[]>("/workspaces");

export const createWorkspace = (name: string) =>
  request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name }) });

export const quickStartWorkspace = (prompt: string) =>
  request<{ workspace: Workspace; list: WorkspaceListMeta }>("/workspaces/quick-start", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });

export const getWorkspace = (id: string) => request<Workspace>(`/workspaces/${id}`);

export const getWorkspaceList = (workspaceId: string, listId: string) =>
  request<WorkspaceListDetail>(`/workspaces/${workspaceId}/lists/${listId}`);

export const createWorkspaceList = (workspaceId: string, prompt: string, name?: string) =>
  request<{ id: string; name: string; status: string }>(`/workspaces/${workspaceId}/lists`, {
    method: "POST",
    body: JSON.stringify({ prompt, name }),
  });

export const getListBuildStatus = (workspaceId: string, listId: string) =>
  request<{ status: string; build_step: string; row_count: number; job: Record<string, unknown> }>(
    `/workspaces/${workspaceId}/lists/${listId}/build-status`
  );

export const getWorkspaceAgentHistory = (workspaceId: string, listId?: string) => {
  const qs = listId ? `?list_id=${listId}` : "";
  return request<AgentChatMessage[]>(`/workspaces/${workspaceId}/agent/history${qs}`);
};

export const sendWorkspaceAgentMessage = (workspaceId: string, message: string, listId?: string) =>
  request<WorkspaceChatResponse>(`/workspaces/${workspaceId}/agent/chat`, {
    method: "POST",
    body: JSON.stringify({ message, list_id: listId ?? null }),
  });

export const launchFromList = (
  workspaceId: string,
  listId: string,
  copy?: {
    connection_note_template?: string;
    message_template?: string;
    wait_days_after_accept?: number;
    campaign_name?: string;
  }
) =>
  request<LaunchFromListResult>(`/workspaces/${workspaceId}/lists/${listId}/launch`, {
    method: "POST",
    body: JSON.stringify(copy ?? {}),
  });

// ─── Explore (Origami-style) ──────────────────────────────────────────────────

export const createExploreSession = (icp_prompt: string) =>
  request<ExploreSession>("/explore/sessions", {
    method: "POST",
    body: JSON.stringify({ icp_prompt }),
  });

export const getExploreSession = (sessionId: string) =>
  request<ExploreSession>(`/explore/sessions/${sessionId}`);

export const updateExploreRow = (
  sessionId: string,
  rowId: string,
  data: Partial<Pick<ExploreSession["rows"][0], "company_name" | "website" | "industry" | "headcount" | "location">>
) =>
  request<{ ok: boolean; fit_score: number }>(`/explore/sessions/${sessionId}/rows/${rowId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const refineExploreSession = (sessionId: string, message: string) =>
  request<ExploreSession>(`/explore/sessions/${sessionId}/refine`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });

export const addExploreEnrichment = (sessionId: string, column_key: string, column_type: string) =>
  request<ExploreSession>(`/explore/sessions/${sessionId}/enrich`, {
    method: "POST",
    body: JSON.stringify({ column_key, column_type }),
  });

export const setExploreFilters = (
  sessionId: string,
  rules: Array<{ field: string; op: string; value: string }>
) =>
  request<ExploreSession>(`/explore/sessions/${sessionId}/filters`, {
    method: "PUT",
    body: JSON.stringify(rules),
  });

export function exploreExportUrl(sessionId: string) {
  return `/api/explore/sessions/${sessionId}/export.csv`;
}

// ─── Outreach export & Instantly ──────────────────────────────────────────────

export const getAppSettings = () => request<AppSettings>("/outreach-export/settings");

export const updateAppSettings = (data: {
  instantly_campaign_id?: string;
  linkedin_connection_template?: string;
  linkedin_follow_up_template?: string;
}) =>
  request<AppSettings>("/outreach-export/settings", {
    method: "PUT",
    body: JSON.stringify(data),
  });

export function listExportCsvUrl(listId: string) {
  return `/api/outreach-export/lists/${listId}/export.csv`;
}

export const pushListToInstantly = (
  listId: string,
  data: {
    lead_ids?: string[];
    subject?: string;
    step1_body?: string;
    step2_body?: string;
    step3_body?: string;
  }
) =>
  request<{ pushed: number; skipped: number; errors: string[]; dry_run?: boolean }>(
    `/outreach-export/lists/${listId}/instantly`,
    { method: "POST", body: JSON.stringify(data) }
  );

// ─── Legacy email ─────────────────────────────────────────────────────────────

export const generateEmails = (leadIds: string[], sequenceId: string) =>
  request<{ emails: any[]; sequence: string }>("/outreach/generate", {
    method: "POST",
    body: JSON.stringify({ lead_ids: leadIds, sequence_id: sequenceId }),
  });
