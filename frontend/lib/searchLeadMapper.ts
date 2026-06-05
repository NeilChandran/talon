import type { SearchDetail, SearchLead } from "@/lib/api";
import type { LeadRow } from "@/lib/supabase";

const OUTREACH_LABELS: Record<string, string> = {
  pending: "Ready",
  linkedin_queued: "Ready",
  connection_sent: "Ongoing",
  accepted: "Ongoing",
  dm_sent: "Completed",
  completed: "Completed",
  replied: "Replied",
  stopped: "Stopped",
  failed: "Failed",
  instantly_queued: "Email queued",
  new: "Ready",
  drafted: "Drafted",
};

function personalize(
  tpl: string,
  first_name: string,
  company: string,
  title: string
): string {
  return tpl
    .replace(/\{\{first_name\}\}/gi, first_name || "there")
    .replace(/\{\{company\}\}/gi, company || "your company")
    .replace(/\{\{title\}\}/gi, title || "");
}

/** Map a Supabase lead row into SearchLead (message copy from search outreach kit). */
export function buildLeadFromRow(row: LeadRow, search: SearchDetail): SearchLead {
  const existing = search.leads?.find((l) => l.id === row.id);
  const sc = row.score ?? row.icp_score ?? 5;
  let st = row.sequence_status || "new";
  if (st === "failed" && (row.linkedin_url || "").trim()) {
    st = "drafted";
  }
  const fn = row.first_name || "there";
  const conn =
    search.linkedin_message_template ||
    search.outreach?.linkedin_connection ||
    "";
  const emailTpl = search.outreach?.email_step1 || "";
  const base: SearchLead = {
    id: row.id,
    search_id: row.search_id,
    first_name: row.first_name || "",
    last_name: row.last_name || "",
    title: row.title || "",
    company: row.company || "",
    email: row.email || "",
    linkedin_url: row.linkedin_url || "",
    score: sc,
    sequence_status: st,
    linkedin_outreach_status: st,
    linkedin_outreach_label: OUTREACH_LABELS[st] || "Ready",
    created_at: row.created_at,
    linkedin_message:
      existing?.linkedin_message ||
      (conn ? personalize(conn, fn, row.company || "", row.title || "") : ""),
    email_preview:
      existing?.email_preview ||
      (emailTpl ? personalize(emailTpl, fn, row.company || "", row.title || "") : ""),
  };
  return base;
}
