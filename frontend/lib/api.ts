import type {
  AutomationJob,
  Lead,
  LeadStatus,
  LinkedInMessage,
  LinkedInSession,
  ProspectingJob,
  Sequence,
  SequenceType,
  Stats,
} from "@/types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const error = await res.text();
    throw new Error(error || `Request failed: ${res.status}`);
  }
  return res.json();
}

// ─── LinkedIn Auth ────────────────────────────────────────────────────────────

export const getLinkedInStatus = () =>
  request<LinkedInSession>("/linkedin/session/status");

export const connectLinkedIn = (li_at: string) =>
  request<LinkedInSession>("/linkedin/session", {
    method: "POST",
    body: JSON.stringify({ li_at }),
  });

export const disconnectLinkedIn = () =>
  request<{ connected: boolean }>("/linkedin/session", { method: "DELETE" });

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

// ─── Prospecting ─────────────────────────────────────────────────────────────

export const startProspecting = (query: string) =>
  request<{ job_id: string; status: string }>("/prospecting/search", {
    method: "POST",
    body: JSON.stringify({ query }),
  });

export const getProspectingStatus = (jobId: string) =>
  request<ProspectingJob>(`/prospecting/status/${jobId}`);

// ─── LinkedIn Outreach ────────────────────────────────────────────────────────

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

// ─── Legacy email ─────────────────────────────────────────────────────────────

export const generateEmails = (leadIds: string[], sequenceId: string) =>
  request<{ emails: any[]; sequence: string }>("/outreach/generate", {
    method: "POST",
    body: JSON.stringify({ lead_ids: leadIds, sequence_id: sequenceId }),
  });
