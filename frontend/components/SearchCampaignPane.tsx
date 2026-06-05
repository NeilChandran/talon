"use client";

import { useEffect, useRef, useState } from "react";
import {
  getCampaignEnrollments,
  getCampaignJob,
  getLinkedInStatus,
  launchOrigamiCampaign,
  prepareSearchCampaign,
} from "@/lib/api";
import type { CampaignEnrollment, LinkedInSession } from "@/types";

type CampaignMeta = {
  id: string;
  name: string;
  connection_note_template: string;
  message_template: string;
  wait_days_after_accept: number;
};

type Props = {
  searchId: string;
  searchPrompt: string;
  campaignId: string;
  campaign: CampaignMeta;
  enrollments: CampaignEnrollment[];
  initialLeadId?: string | null;
  onClose: () => void;
  onRefresh: () => void;
};

type DisplayStatus = { badge: string; label: string };

function linkedinHandle(url?: string | null) {
  return (url || "").split("/in/")[1]?.replace(/\/$/, "") || "";
}

function truncateHandle(handle: string, max = 16) {
  if (!handle || handle.length <= max) return handle;
  return `${handle.slice(0, max)}…`;
}

function leadLabel(e: CampaignEnrollment) {
  const slug = linkedinHandle(e.linkedin_url);
  if (slug) return slug;
  const name = [e.name].filter(Boolean).join(" ").trim();
  return name || "Lead";
}

function leadInitial(e: CampaignEnrollment) {
  const name = (e.name || leadLabel(e)).trim();
  return (name[0] || "?").toUpperCase();
}

function formatScheduledFor(iso?: string | null) {
  if (!iso) return "Scheduled";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Scheduled";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `Scheduled for ${time}`;
  const day = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  return `Scheduled for ${day} at ${time}`;
}

function isOrigamiScheduled(e: CampaignEnrollment) {
  return (
    e.origami_send_status === "scheduled" ||
    Boolean(e.scheduled_at) ||
    e.status === "connection_sent"
  );
}

function scheduledStatus(e: CampaignEnrollment): DisplayStatus {
  return {
    badge: "scheduled",
    label: formatScheduledFor(e.scheduled_at),
  };
}

function effectiveStatus(e: CampaignEnrollment): DisplayStatus {
  const hasProfile = Boolean((e.linkedin_url || "").trim());
  const st = e.status || "drafted";

  if (st === "failed" && hasProfile) {
    return { badge: "drafted", label: "Drafted" };
  }

  if (isOrigamiScheduled(e) && (st === "connection_sent" || e.origami_send_status === "scheduled")) {
    return scheduledStatus(e);
  }

  const map: Record<string, DisplayStatus> = {
    drafted: { badge: "drafted", label: "Drafted" },
    pending: { badge: "drafted", label: "Drafted" },
    connection_sent: { badge: "scheduled", label: formatScheduledFor(e.scheduled_at) },
    accepted: { badge: "ongoing", label: "Ongoing" },
    dm_sent: { badge: "completed", label: "Completed" },
    completed: { badge: "completed", label: "Completed" },
    replied: { badge: "replied", label: "Replied" },
    stopped: { badge: "ready", label: "Stopped" },
    failed: { badge: "ready", label: "Drafted" },
  };
  return map[st] || { badge: "ready", label: "Ready" };
}

function step1Status(e: CampaignEnrollment, connSent: boolean): DisplayStatus {
  if (connSent || e.origami_send_status === "scheduled") return scheduledStatus(e);
  return effectiveStatus(e);
}

function LinkedInIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="#0A66C2" aria-hidden>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 114.126 0 2.063 2.063 0 01-2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

export default function SearchCampaignPane({
  searchId,
  searchPrompt,
  campaignId,
  campaign,
  enrollments: initialEnrollments,
  initialLeadId,
  onClose,
  onRefresh,
}: Props) {
  const [enrollments, setEnrollments] = useState(initialEnrollments);
  const pickEnrollmentId = (leadId?: string | null) => {
    if (!leadId) return initialEnrollments[0]?.id || null;
    return (
      initialEnrollments.find((e) => e.lead_id === leadId)?.id ||
      initialEnrollments[0]?.id ||
      null
    );
  };

  const [selectedId, setSelectedId] = useState<string | null>(pickEnrollmentId(initialLeadId));
  const [filter, setFilter] = useState("");
  const [launching, setLaunching] = useState(false);
  const [jobStep, setJobStep] = useState("");
  const [liSession, setLiSession] = useState<LinkedInSession | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const selected = enrollments.find((e) => e.id === selectedId) ?? null;
  const senderHandle = truncateHandle(linkedinHandle(liSession?.linkedin_url) || "you");
  const recipientHandle = selected ? linkedinHandle(selected.linkedin_url) : "";

  useEffect(() => {
    setEnrollments(initialEnrollments);
    if (initialLeadId) {
      const match =
        initialEnrollments.find((e) => e.lead_id === initialLeadId)?.id ||
        initialEnrollments[0]?.id ||
        null;
      setSelectedId(match);
    }
  }, [initialEnrollments, initialLeadId]);

  useEffect(() => {
    getLinkedInStatus()
      .then(setLiSession)
      .catch(() => setLiSession({ connected: false }));
    prepareSearchCampaign(searchId)
      .then((p) => setEnrollments(p.enrollments))
      .catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [searchId]);

  const filtered = enrollments.filter((e) => {
    const q = filter.toLowerCase();
    if (!q) return true;
    return (
      leadLabel(e).toLowerCase().includes(q) ||
      (e.name || "").toLowerCase().includes(q) ||
      (e.company || "").toLowerCase().includes(q) ||
      (e.linkedin_url || "").toLowerCase().includes(q)
    );
  });

  const connSent =
    selected &&
    ["connection_sent", "accepted", "dm_sent", "completed", "replied"].includes(selected.status);
  const accepted =
    selected && ["accepted", "dm_sent", "completed", "replied"].includes(selected.status);
  const dmSent = selected && ["dm_sent", "completed", "replied"].includes(selected.status);

  const launchableCount = enrollments.filter(
    (e) =>
      (e.status === "drafted" || e.status === "pending" || (e.status === "failed" && e.linkedin_url)) &&
      (e.connection_note || "").trim().length > 0
  ).length;

  const handleLaunchAll = async () => {
    setLaunching(true);
    setJobStep("Syncing drafts from Origami…");
    try {
      const prepared = await prepareSearchCampaign(searchId);
      setEnrollments(prepared.enrollments);
      const activeCampaignId = prepared.campaign_id || campaignId;
      const ready = prepared.enrollments.filter(
        (e) =>
          (e.status === "drafted" || e.status === "pending" || (e.status === "failed" && e.linkedin_url)) &&
          (e.connection_note || "").trim().length > 0
      ).length;
      if (!ready) {
        alert("No drafted connection notes to launch — wait for Origami to finish drafting.");
        setLaunching(false);
        return;
      }
      setJobStep(`Launching ${ready} sequences in Origami…`);
      const { job_id } = await launchOrigamiCampaign(searchId);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const j = await getCampaignJob(job_id);
          setJobStep(j.step || `Origami launching ${j.done}/${j.total}…`);
          if (["completed", "failed", "paused"].includes(j.status)) {
            if (pollRef.current) clearInterval(pollRef.current);
            const enrs = await getCampaignEnrollments(activeCampaignId);
            setEnrollments(enrs);
            onRefresh();
            setLaunching(false);
            if (j.status === "failed" && j.error) alert(j.error);
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setLaunching(false);
        }
      }, 2000);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Launch failed");
      setLaunching(false);
    }
  };

  const connectionNote = selected?.connection_note || campaign.connection_note_template || "";
  const noteLen = connectionNote.length;
  const selectedStatus = selected ? effectiveStatus(selected) : null;
  const step1 = selected ? step1Status(selected, Boolean(connSent)) : null;

  return (
    <div className="hedwig-campaign-view">
      <header className="hedwig-campaign-head">
        <div>
          <button type="button" className="hedwig-campaign-back" onClick={onClose}>
            ← Back
          </button>
          <p className="origami-seq-breadcrumb">CAMPAIGN</p>
          <h1 className="hedwig-campaign-title">{searchPrompt}</h1>
          <p className="hedwig-campaign-sub">{enrollments.length} sequences</p>
        </div>
        <div className="hedwig-campaign-actions">
          <button
            type="button"
            className="hedwig-send-export"
            disabled={launching || launchableCount === 0}
            onClick={handleLaunchAll}
          >
            {launching ? jobStep || "Launching…" : "Launch all"}
          </button>
        </div>
      </header>

      <div className="hedwig-campaign-body">
        <aside className="hedwig-campaign-list">
          <div className="hedwig-campaign-list-head">
            <span>Select all {enrollments.length}</span>
          </div>
          <input
            className="hedwig-campaign-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter leads…"
          />
          <div className="hedwig-campaign-list-scroll">
            {filtered.map((e) => {
              const st = effectiveStatus(e);
              return (
                <button
                  key={e.id}
                  type="button"
                  className={`hedwig-campaign-lead${e.id === selectedId ? " selected" : ""}`}
                  onClick={() => setSelectedId(e.id)}
                >
                  <span className="hedwig-campaign-lead-name">{leadLabel(e)}</span>
                  <span className={`hedwig-outreach-badge ${st.badge}`}>{st.label}</span>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="hedwig-campaign-detail">
          {!selected ? (
            <p style={{ padding: 40, color: "var(--text-muted)" }}>Select a lead to preview their sequence</p>
          ) : (
            <>
              <div className="origami-seq-lead-head">
                <div className="origami-seq-lead-info">
                  <div className="origami-seq-avatar">{leadInitial(selected)}</div>
                  <div>
                    <div className="origami-seq-name-row">
                      <h2>{selected.name || leadLabel(selected)}</h2>
                      {selected.linkedin_url && (
                        <a
                          href={selected.linkedin_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="origami-seq-icon-link"
                          aria-label="LinkedIn profile"
                        >
                          <LinkedInIcon />
                        </a>
                      )}
                    </div>
                    <p className="origami-seq-subtitle">
                      {[selected.title, selected.company].filter(Boolean).join(" · ")}
                      {" · "}2-step sequence
                    </p>
                  </div>
                </div>
                <div className="origami-seq-head-actions">
                  {selectedStatus && (
                    <span className={`origami-seq-status-pill ${selectedStatus.badge}`}>
                      {selectedStatus.badge === "scheduled" && (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                          <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
                        </svg>
                      )}
                      {selectedStatus.label}
                    </span>
                  )}
                </div>
              </div>

              <div className="origami-seq-flow">
                <div className="origami-seq-step origami-seq-step--active">
                  <div className="origami-seq-step-head">
                    <div className="origami-seq-step-title">
                      <span className="origami-seq-step-num">1</span>
                      <LinkedInIcon size={16} />
                      <span>Send Connection Request</span>
                    </div>
                    {step1 && (
                      <span className={`origami-seq-step-badge ${step1.badge}`}>{step1.label}</span>
                    )}
                  </div>

                  <div className="origami-seq-route">
                    <span className="origami-seq-premium">Premium</span>
                    <span className="origami-seq-handle">{senderHandle}</span>
                    <span className="origami-seq-arrow">→</span>
                    <span className="origami-seq-network">Not in network</span>
                    <span className="origami-seq-arrow">→</span>
                    <a
                      href={selected.linkedin_url || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="origami-seq-handle origami-seq-handle--recipient"
                    >
                      {recipientHandle || leadLabel(selected)}
                    </a>
                  </div>

                  <div className="origami-seq-message">
                    <p>{connectionNote}</p>
                    <span className={`origami-seq-chars${noteLen > 280 ? " warn" : ""}`}>
                      {noteLen} / 300
                    </span>
                  </div>
                </div>

                <div className="origami-seq-connector">
                  <div className="origami-seq-connector-line" />
                  <div className="origami-seq-wait-pill">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" />
                    </svg>
                    If accepted, wait {campaign.wait_days_after_accept} day
                    {campaign.wait_days_after_accept !== 1 ? "s" : ""} after accept if no response
                  </div>
                  <div className="origami-seq-connector-line" />
                </div>

                <div className="origami-seq-step">
                  <div className="origami-seq-step-head">
                    <div className="origami-seq-step-title">
                      <span className="origami-seq-step-num">2</span>
                      <LinkedInIcon size={16} />
                      <span>
                        Send Message <em className="origami-seq-thread">in thread</em>
                      </span>
                    </div>
                    <span className="origami-seq-step-badge muted">
                      {dmSent ? "Sent" : accepted ? "Ready" : "Waiting for connection"}
                    </span>
                  </div>

                  <div className="origami-seq-route">
                    <span className="origami-seq-premium">Premium</span>
                    <span className="origami-seq-handle">{senderHandle}</span>
                    <span className="origami-seq-arrow">→</span>
                    <span className="origami-seq-handle origami-seq-handle--recipient">
                      {recipientHandle || leadLabel(selected)}
                    </span>
                  </div>

                  <div className="origami-seq-message origami-seq-message--plain">
                    <p>{selected.follow_up_message || campaign.message_template}</p>
                  </div>
                </div>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
