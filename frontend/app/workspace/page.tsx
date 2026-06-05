"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  checkReplies,
  createCampaign,
  enrollLeadsInCampaign,
  getAgentHistory,
  getCampaignEnrollments,
  getCampaignJob,
  getCampaigns,
  getLinkedInStatus,
  launchCampaign,
  sendAgentMessage,
  stopEnrollment,
  syncCampaign,
} from "@/lib/api";
import type {
  AgentChatMessage,
  Campaign,
  CampaignEnrollment,
  CampaignJob,
  LinkedInSession,
  SuggestedAction,
} from "@/types";

const BADGE: Record<string, string> = {
  replied: "badge-green",
  completed: "badge-green",
  dm_sent: "badge-green",
  stopped: "badge-purple",
  connection_sent: "badge-amber",
  accepted: "badge-blue",
  pending: "badge-gray",
  failed: "badge-red",
};

const BADGE_LABEL: Record<string, string> = {
  replied: "Replied",
  completed: "Completed",
  dm_sent: "Completed",
  stopped: "Stopped",
  connection_sent: "Pending",
  accepted: "Accepted",
  pending: "Ready",
  failed: "Failed",
};

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function AgentPanel({
  campaign,
  liSession,
  onCampaignUpdated,
  onAction,
}: {
  campaign: Campaign | null;
  liSession: LinkedInSession | null;
  onCampaignUpdated: () => void;
  onAction: (action: string) => void;
}) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastActions, setLastActions] = useState<SuggestedAction[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAgentHistory(campaign?.id).then(setMessages).catch(() => {});
  }, [campaign?.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text: string) => {
    if (!text.trim() || loading) return;
    setInput("");
    setLoading(true);
    setMessages((m) => [...m, { id: `tmp-${Date.now()}`, role: "user", content: text, suggested_actions: [], created_at: new Date().toISOString() }]);
    try {
      const res = await sendAgentMessage(text, campaign?.id);
      setMessages((m) => [...m, { id: `asst-${Date.now()}`, role: "assistant", content: res.reply, suggested_actions: res.suggested_actions.map((a) => a.label), created_at: new Date().toISOString() }]);
      setLastActions(res.suggested_actions);
      if (res.campaign_updated) onCampaignUpdated();
    } catch (e: unknown) {
      setMessages((m) => [...m, { id: `err-${Date.now()}`, role: "assistant", content: e instanceof Error ? e.message : "Something went wrong.", suggested_actions: [], created_at: new Date().toISOString() }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <p className="panel-header-label">Talon AI</p>
        <p className="panel-header-title">{campaign?.name ?? "Select a campaign"}</p>
        {liSession && !liSession.connected && (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "#b45309" }}>
            <Link href="/settings" style={{ color: "var(--accent)", fontWeight: 600 }}>Connect LinkedIn</Link> to automate
          </p>
        )}
      </div>
      <div className="panel-scroll">
        {messages.length === 0 && (
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6, padding: "8px 4px" }}>
            Ask me to update copy, launch sequences, or check replies.
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`chat-bubble ${m.role}`}>
            <div style={{ fontSize: 11, fontWeight: 600, color: m.role === "user" ? "var(--accent)" : "var(--text-secondary)", marginBottom: 4 }}>
              {m.role === "user" ? "You" : "Talon AI"}
            </div>
            {m.content}
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--text-muted)" }}>
            <div style={{ width: 14, height: 14, border: "2px solid var(--accent)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
            Thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      {lastActions.length > 0 && (
        <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border-light)", display: "flex", flexDirection: "column", gap: 6 }}>
          {lastActions.map((a) => (
            <button key={a.id} type="button" onClick={() => onAction(a.action)} className="btn-secondary" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 8 }}>
              {a.label}
            </button>
          ))}
        </div>
      )}
      <div className="chat-input-wrap">
        <textarea className="chat-input" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} placeholder="What should I do next..." rows={2} />
        <button type="button" onClick={() => send(input)} disabled={loading || !input.trim()} className="btn-primary" style={{ width: "100%" }}>Send</button>
      </div>
    </div>
  );
}

function SequenceDetail({ enrollment, campaign, liSession, onLaunch, onStop }: {
  enrollment: CampaignEnrollment | null;
  campaign: Campaign | null;
  liSession: LinkedInSession | null;
  onLaunch: () => void;
  onStop: () => void;
}) {
  if (!enrollment || !campaign) {
    return (
      <div className="panel" style={{ borderRight: "none", flex: 1, alignItems: "center", justifyContent: "center" }}>
        <p style={{ color: "var(--text-muted)", fontSize: 14 }}>Select a contact to view their sequence</p>
      </div>
    );
  }

  const badge = BADGE[enrollment.status] || "badge-gray";
  const connSent = ["connection_sent", "accepted", "dm_sent", "completed", "replied"].includes(enrollment.status);
  const accepted = ["accepted", "dm_sent", "completed", "replied"].includes(enrollment.status);
  const dmSent = ["dm_sent", "completed", "replied"].includes(enrollment.status);
  const note = enrollment.connection_note || campaign.connection_note_template;
  const dm = enrollment.follow_up_message || campaign.message_template;

  return (
    <div className="panel" style={{ borderRight: "none", flex: 1 }}>
      <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <p className="panel-header-title" style={{ fontSize: 18 }}>{enrollment.name}</p>
          <p style={{ margin: "4px 0 8px", fontSize: 13, color: "var(--text-secondary)" }}>
            {[enrollment.title, enrollment.company].filter(Boolean).join(" · ")}
          </p>
          <span className={`badge ${badge}`}>{BADGE_LABEL[enrollment.status] || enrollment.status}</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          {enrollment.status !== "stopped" && enrollment.status !== "completed" && (
            <button type="button" onClick={onStop} className="btn-ghost">Stop</button>
          )}
          <button type="button" onClick={onLaunch} disabled={!liSession?.connected} className="btn-primary">Launch sequence</button>
        </div>
      </div>
      <div className="panel-scroll" style={{ padding: "20px 24px" }}>
        <p style={{ margin: "0 0 16px", fontSize: 12, fontWeight: 600, color: "var(--text-muted)" }}>2-step sequence</p>
        <div className="step-card">
          <div className="step-card-head">
            <span style={{ fontWeight: 600, fontSize: 13 }}>Send Connection Request</span>
            <span className={`badge ${accepted || connSent ? "badge-green" : "badge-gray"}`}>
              {accepted ? "Accepted" : connSent ? "Sent" : "Pending"}
            </span>
          </div>
          <div style={{ padding: 16 }}>
            {enrollment.connection_sent_at && <p style={{ margin: "0 0 8px", fontSize: 11, color: "var(--text-muted)" }}>{formatDate(enrollment.connection_sent_at)}</p>}
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{note || <em style={{ color: "var(--text-muted)" }}>AI-generated</em>}</p>
          </div>
        </div>
        <div className="step-wait">
          <span className="step-wait-pill">If accepted, wait {campaign.wait_days_after_accept} day{campaign.wait_days_after_accept !== 1 ? "s" : ""} then send DM</span>
        </div>
        <div className="step-card">
          <div className="step-card-head">
            <span style={{ fontWeight: 600, fontSize: 13 }}>Send Message</span>
            <span className={`badge ${dmSent ? "badge-green" : "badge-gray"}`}>{dmSent ? "Sent" : "Scheduled"}</span>
          </div>
          <div style={{ padding: 16 }}>
            {enrollment.dm_sent_at && <p style={{ margin: "0 0 8px", fontSize: 11, color: "var(--text-muted)" }}>{formatDate(enrollment.dm_sent_at)}</p>}
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{dm || <em style={{ color: "var(--text-muted)" }}>AI-generated</em>}</p>
          </div>
        </div>
        {enrollment.last_error && (
          <div style={{ marginTop: 16, padding: 12, background: "#fef2f2", borderRadius: 8, fontSize: 12, color: "#b91c1c" }}>{enrollment.last_error}</div>
        )}
      </div>
    </div>
  );
}

const DEFAULT_CAMPAIGN = {
  name: "LinkedIn Outreach",
  connection_note_template:
    "Hi {{first_name}} — I'm Neil, a Stanford student building Hedwig, a free AI agent for Gmail and Google Calendar. Would love to connect!",
  message_template:
    "Hey {{first_name}}, thanks for connecting!\n\nHedwig is a free AI agent that plugs into Gmail and Google Calendar — it triages your inbox, drafts replies, and handles scheduling.\n\nWould love to show you a quick demo if you're open to it!",
  wait_days_after_accept: 1,
};

export default function WorkspacePage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [activeCampaignId, setActiveCampaignId] = useState<string | null>(null);
  const [enrollments, setEnrollments] = useState<CampaignEnrollment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [liSession, setLiSession] = useState<LinkedInSession | null>(null);
  const [job, setJob] = useState<CampaignJob | null>(null);
  const [filter, setFilter] = useState("");
  const [tab, setTab] = useState<"active" | "done" | "all">("active");
  const [loadError, setLoadError] = useState("");
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const activeCampaign = campaigns.find((c) => c.id === activeCampaignId) ?? null;
  const selected = enrollments.find((e) => e.id === selectedId) ?? null;

  const loadCampaigns = useCallback(async () => {
    try {
      const [camps, sess] = await Promise.all([
        getCampaigns(),
        getLinkedInStatus().catch(() => ({ connected: false }) as LinkedInSession),
      ]);
      setCampaigns(camps);
      setLiSession(sess);
      setLoadError("");
      setActiveCampaignId((prev) => prev ?? (camps.length > 0 ? camps[0].id : null));
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : "Failed to load campaigns");
    }
  }, []);

  const loadEnrollments = useCallback(async () => {
    if (!activeCampaignId) return;
    const enrs = await getCampaignEnrollments(activeCampaignId);
    setEnrollments(enrs);
    if (!selectedId && enrs.length > 0) setSelectedId(enrs[0].id);
  }, [activeCampaignId, selectedId]);

  useEffect(() => { loadCampaigns(); }, [loadCampaigns]);
  useEffect(() => { loadEnrollments(); }, [loadEnrollments]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const createDefaultCampaign = async () => {
    const c = await createCampaign(DEFAULT_CAMPAIGN);
    setCampaigns((p) => [...p, c]);
    setActiveCampaignId(c.id);
  };

  const refreshAll = () => { loadCampaigns(); loadEnrollments(); };

  const handleAgentAction = async (action: string) => {
    if (!activeCampaignId) return;
    if (action === "launch_campaign") await handleLaunch();
    else if (action === "enroll_all") { await enrollLeadsInCampaign(activeCampaignId); refreshAll(); }
    else if (action === "check_replies") { await checkReplies(); refreshAll(); }
    else if (action === "sync_campaign") { await syncCampaign(activeCampaignId); setTimeout(refreshAll, 3000); }
    else if (action === "open_settings") window.location.href = "/settings";
  };

  const handleLaunch = async () => {
    if (!activeCampaignId) return;
    try {
      const { job_id } = await launchCampaign(activeCampaignId);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        const j = await getCampaignJob(job_id);
        setJob(j);
        if (["completed", "failed", "paused"].includes(j.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          refreshAll();
        }
      }, 2000);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Launch failed");
    }
  };

  const filtered = enrollments.filter((e) => {
    const q = filter.toLowerCase();
    const matchQ = !q || (e.name || "").toLowerCase().includes(q) || (e.linkedin_url || "").toLowerCase().includes(q);
    const done = ["completed", "replied", "stopped"].includes(e.status);
    const matchTab = tab === "all" || (tab === "done" ? done : !done);
    return matchQ && matchTab;
  });

  return (
    <div className="workspace-shell">
      {loadError && (
        <div style={{ padding: "12px 24px", background: "#F4F0FF", borderBottom: "1px solid #E4DEFF", fontSize: 13, color: "#5B46B8" }}>
          {loadError}
        </div>
      )}
      <div style={{ padding: "20px 24px 0", background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
        <h1 className="page-title" style={{ marginBottom: 12 }}>Explore campaigns</h1>
        <div className="tabs">
          <button type="button" className={`tab${tab === "active" ? " active" : ""}`} onClick={() => setTab("active")}>Active sequences</button>
          <button type="button" className={`tab${tab === "done" ? " active" : ""}`} onClick={() => setTab("done")}>Completed</button>
          <button type="button" className={`tab${tab === "all" ? " active" : ""}`} onClick={() => setTab("all")}>All contacts</button>
        </div>
        <div className="toolbar" style={{ marginBottom: 16 }}>
          <div className="search-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3-3"/></svg>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Type to search" />
          </div>
          <button type="button" className="btn-ghost">Filter</button>
          <button type="button" className="btn-secondary" onClick={() => activeCampaignId && syncCampaign(activeCampaignId).then(() => setTimeout(refreshAll, 2000))}>Sync accepts</button>
          <button type="button" className="btn-primary" onClick={handleLaunch} disabled={!liSession?.connected}>
            Launch outreach
          </button>
        </div>
        <div className="campaign-chips" style={{ borderBottom: "none", padding: "0 0 12px" }}>
          {campaigns.length === 0 && !loadError && (
            <button type="button" className="btn-primary" onClick={createDefaultCampaign}>
              Create default campaign
            </button>
          )}
          {campaigns.map((c) => (
            <button key={c.id} type="button" className={`campaign-chip${activeCampaignId === c.id ? " active" : ""}`} onClick={() => { setActiveCampaignId(c.id); setSelectedId(null); }}>
              {c.name} ({c.enrollment_count})
            </button>
          ))}
          <button type="button" className="campaign-chip" style={{ borderStyle: "dashed" }} onClick={async () => {
            const name = prompt("Campaign name:");
            if (!name) return;
            const { createCampaign } = await import("@/lib/api");
            const c = await createCampaign({ name, connection_note_template: "", message_template: "", wait_days_after_accept: 1 });
            setCampaigns((p) => [...p, c]);
            setActiveCampaignId(c.id);
          }}>+ New table</button>
          {job?.status === "running" && <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 8 }}>{job.step || `Running ${job.done}/${job.total}...`}</span>}
        </div>
      </div>

      <div className="workspace-body">
        <AgentPanel campaign={activeCampaign} liSession={liSession} onCampaignUpdated={refreshAll} onAction={handleAgentAction} />

        <div className="panel panel-center">
          <div className="panel-header">
            <p className="panel-header-label">Sequencer</p>
            <p className="panel-header-title">{filtered.length} contacts</p>
          </div>
          <div className="enrollment-grid" style={{ flex: 1, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <p style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: 24 }}>
                No contacts yet. <button type="button" className="btn-secondary" style={{ marginTop: 8 }} onClick={async () => { if (activeCampaignId) { await enrollLeadsInCampaign(activeCampaignId); refreshAll(); } }}>Enroll leads</button>
              </p>
            ) : (
              filtered.map((e) => (
                <button key={e.id} type="button" className={`opp-card${e.id === selectedId ? " selected" : ""}`} onClick={() => setSelectedId(e.id)}>
                  <p className="opp-card-title">{e.name || "Unknown"}</p>
                  <p className="opp-card-sub">{[e.title, e.company].filter(Boolean).join(" · ") || e.linkedin_url || "—"}</p>
                  <div className="opp-card-footer">
                    <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>2-step sequence</span>
                    <span className={`badge ${BADGE[e.status] || "badge-gray"}`}>{BADGE_LABEL[e.status]}</span>
                  </div>
                  {e.status === "pending" && liSession?.connected && (
                    <span className="badge-1click">✓ 1-click launch</span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>

        <SequenceDetail enrollment={selected} campaign={activeCampaign} liSession={liSession} onLaunch={handleLaunch} onStop={async () => {
          if (!activeCampaignId || !selected) return;
          await stopEnrollment(activeCampaignId, selected.id);
          refreshAll();
        }} />
      </div>
    </div>
  );
}
