"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  checkReplies,
  getAgentHistory,
  getCampaign,
  getCampaignEnrollments,
  getCampaignJob,
  getLinkedInStatus,
  launchCampaign,
  sendAgentMessage,
  stopEnrollment,
  syncCampaign,
} from "@/lib/api";
import type { AgentChatMessage, Campaign, CampaignEnrollment, CampaignJob, LinkedInSession, SuggestedAction } from "@/types";

const BADGE: Record<string, string> = {
  replied: "badge-green", completed: "badge-green", dm_sent: "badge-green",
  stopped: "badge-purple", connection_sent: "badge-amber", accepted: "badge-blue",
  pending: "badge-gray", failed: "badge-red",
};
const BADGE_LABEL: Record<string, string> = {
  replied: "Replied", completed: "Completed", dm_sent: "Completed", stopped: "Stopped",
  connection_sent: "Ongoing", accepted: "Ongoing", pending: "Ready", failed: "Failed",
};

function formatDate(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function CampaignSequencerPage() {
  const params = useParams();
  const campaignId = params.id as string;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [enrollments, setEnrollments] = useState<CampaignEnrollment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [liSession, setLiSession] = useState<LinkedInSession | null>(null);
  const [job, setJob] = useState<CampaignJob | null>(null);
  const [filter, setFilter] = useState("");
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const selected = enrollments.find((e) => e.id === selectedId) ?? null;

  const refresh = useCallback(async () => {
    const [c, enrs, sess] = await Promise.all([
      getCampaign(campaignId),
      getCampaignEnrollments(campaignId),
      getLinkedInStatus().catch(() => ({ connected: false }) as LinkedInSession),
    ]);
    setCampaign(c);
    setEnrollments(enrs);
    setLiSession(sess);
    if (!selectedId && enrs.length > 0) setSelectedId(enrs[0].id);
  }, [campaignId, selectedId]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleLaunchAll = async () => {
    if (!liSession?.connected) { window.location.href = "/settings"; return; }
    const { job_id } = await launchCampaign(campaignId);
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const j = await getCampaignJob(job_id);
      setJob(j);
      if (["completed", "failed", "paused"].includes(j.status)) {
        if (pollRef.current) clearInterval(pollRef.current);
        refresh();
      }
    }, 2000);
  };

  const filtered = enrollments.filter((e) => {
    const q = filter.toLowerCase();
    return !q || (e.name || "").toLowerCase().includes(q) || (e.linkedin_url || "").toLowerCase().includes(q);
  });

  const connSent = selected && ["connection_sent", "accepted", "dm_sent", "completed", "replied"].includes(selected.status);
  const accepted = selected && ["accepted", "dm_sent", "completed", "replied"].includes(selected.status);
  const dmSent = selected && ["dm_sent", "completed", "replied"].includes(selected.status);

  return (
    <div className="workspace-shell" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <p style={{ margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", color: "var(--text-muted)" }}>CAMPAIGN</p>
          <h1 style={{ margin: "4px 0 0", fontSize: 20, fontWeight: 700 }}>{campaign?.name ?? "…"}</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>{enrollments.length} sequences</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Link href="/sequencing/campaigns" className="btn-ghost">Back</Link>
          <button type="button" className="btn-secondary" onClick={() => syncCampaign(campaignId).then(() => setTimeout(refresh, 2000))}>Sync accepts</button>
          <button type="button" className="btn-primary" onClick={handleLaunchAll} disabled={!liSession?.connected}>
            Launch all
          </button>
        </div>
      </div>
      {job?.status === "running" && (
        <div style={{ padding: "8px 24px", background: "#F4F0FF", fontSize: 12 }}>{job.step || `Sending ${job.done}/${job.total}…`}</div>
      )}

      <div className="workspace-body" style={{ flex: 1, minHeight: 0 }}>
        <div className="panel panel-center" style={{ width: 280, minWidth: 240 }}>
          <div className="panel-header">
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter leads…" style={{ width: "100%", fontSize: 13, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }} />
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {filtered.map((e) => (
              <button key={e.id} type="button" className={`opp-card${e.id === selectedId ? " selected" : ""}`} onClick={() => setSelectedId(e.id)} style={{ width: "100%", textAlign: "left" }}>
                <p className="opp-card-title" style={{ fontSize: 13 }}>{(e.linkedin_url || "").split("/in/")[1]?.replace(/\/$/, "") || e.name || "—"}</p>
                <span className={`badge ${BADGE[e.status] || "badge-gray"}`} style={{ marginTop: 6 }}>{BADGE_LABEL[e.status] || e.status}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel" style={{ flex: 1, borderRight: "none" }}>
          {!selected || !campaign ? (
            <p style={{ padding: 40, color: "var(--text-muted)" }}>Select a lead to view their sequence</p>
          ) : (
            <>
              <div className="panel-header" style={{ display: "flex", justifyContent: "space-between" }}>
                <div>
                  <p className="panel-header-title">{selected.name}</p>
                  <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>{[selected.title, selected.company].filter(Boolean).join(" · ")}</p>
                  <span className={`badge ${BADGE[selected.status]}`} style={{ marginTop: 8 }}>{BADGE_LABEL[selected.status]}</span>
                </div>
                {selected.status !== "stopped" && (
                  <button type="button" className="btn-ghost" style={{ color: "#b91c1c" }} onClick={async () => {
                    await stopEnrollment(campaignId, selected.id);
                    refresh();
                  }}>Stop sequence</button>
                )}
              </div>
              <div className="panel-scroll" style={{ padding: "20px 24px" }}>
                <div className="step-card">
                  <div className="step-card-head">
                    <span style={{ fontWeight: 600 }}>Step 1 — Send Connection Request</span>
                    <span className={`badge ${connSent ? "badge-green" : "badge-gray"}`}>{connSent ? "Sent" : "Pending"}</span>
                  </div>
                  <div style={{ padding: 16 }}>
                    {selected.connection_sent_at && <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>{formatDate(selected.connection_sent_at)}</p>}
                    <p style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.6, margin: 0 }}>{selected.connection_note || campaign.connection_note_template}</p>
                  </div>
                </div>
                <div className="step-wait">
                  <span className="step-wait-pill">Waiting for connection acceptance then {campaign.wait_days_after_accept} day{campaign.wait_days_after_accept !== 1 ? "s" : ""} after accept if no reply</span>
                </div>
                <div className="step-card">
                  <div className="step-card-head">
                    <span style={{ fontWeight: 600 }}>Step 2 — Send Message</span>
                    <span className={`badge ${dmSent ? "badge-green" : accepted ? "badge-amber" : "badge-gray"}`}>
                      {dmSent ? "Sent" : accepted ? "Ready" : "Waiting for connection"}
                    </span>
                  </div>
                  <div style={{ padding: 16 }}>
                    <p style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.6, margin: 0 }}>{selected.follow_up_message || campaign.message_template}</p>
                  </div>
                </div>
                {selected.last_error && <p style={{ color: "#b91c1c", fontSize: 12, marginTop: 16 }}>{selected.last_error}</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
