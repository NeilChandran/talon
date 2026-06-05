"use client";

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  getRecentSearches,
  getSearchOrNull,
  prepareSearchCampaign,
  pushSearchToInstantly,
  refreshSearchLeads,
  resumeSearch,
  searchAgentMessage,
  searchExportCsvUrl,
  sendSearchLinkedIn,
} from "@/lib/api";
import type { RecentSearch, SearchDetail, SearchLead } from "@/lib/api";
import SearchCampaignPane from "@/components/SearchCampaignPane";
import { useSearchRealtime } from "@/lib/useSearchRealtime";
import { friendlyChatError, searchFailHint, talonMessage } from "@/lib/brand";
import type { CampaignEnrollment } from "@/types";

function tabLabel(prompt: string) {
  const words = prompt.split(/\s+/).slice(0, 4).join(" ");
  return words.length > 22 ? words.slice(0, 20) + "…" : words;
}

function listTitle(prompt: string) {
  const p = prompt.trim();
  if (/linkedin/i.test(p)) {
    const core = p.replace(/^find\s+/i, "").slice(0, 48);
    return core.charAt(0).toUpperCase() + core.slice(1);
  }
  return p.length > 56 ? p.slice(0, 54) + "…" : p;
}

function extractBatch(company: string) {
  const m = company.match(/\(YC[^)]+\)|YC\s*W?\d+/i);
  return m ? m[0].replace(/[()]/g, "").trim() : "—";
}

function companyDomainGuess(company: string) {
  const base = company.split(/[(\[]/)[0].trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  return base ? `${base}.com` : "";
}

function outreachBadgeClass(label: string) {
  const l = label.toLowerCase();
  if (l === "replied" || l === "completed") return "completed";
  if (l === "ongoing") return "ongoing";
  if (l === "failed") return "failed";
  if (l === "drafted") return "drafted";
  return "ready";
}

function SearchWorkspace() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchId = params.id as string;

  const [search, setSearch] = useState<SearchDetail | null>(null);
  const [recent, setRecent] = useState<RecentSearch[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [instantlyOpen, setInstantlyOpen] = useState(false);
  const [linkedInNote, setLinkedInNote] = useState("");
  const [sendingLi, setSendingLi] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [emailSubject, setEmailSubject] = useState("Quick intro — {{company}}");
  const [emailSteps, setEmailSteps] = useState([
    "Hi {{first_name}},\n\nI wanted to reach out about {{company}}…",
    "Following up — still think this could be valuable for {{company}}.",
    "Last note — happy to connect whenever timing works.",
  ]);
  const [pushing, setPushing] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [campaignOpen, setCampaignOpen] = useState(false);
  const [campaignLoading, setCampaignLoading] = useState(false);
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [campaignMeta, setCampaignMeta] = useState<{
    id: string;
    name: string;
    connection_note_template: string;
    message_template: string;
    wait_days_after_accept: number;
  } | null>(null);
  const [campaignEnrollments, setCampaignEnrollments] = useState<CampaignEnrollment[]>([]);
  const [campaignLeadId, setCampaignLeadId] = useState<string | null>(null);
  const [chatSending, setChatSending] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [chatMessages, setChatMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const menuRef = useRef<HTMLDivElement>(null);
  const autoNameSyncRef = useRef(false);
  const autoResumeRef = useRef(false);
  const campaignDeepLinkRef = useRef(false);

  const load = useCallback(async () => {
    const [s, r] = await Promise.all([
      getSearchOrNull(searchId),
      getRecentSearches().catch(() => [] as RecentSearch[]),
    ]);
    if (!s) {
      setSearch(null);
      return null;
    }
    setSearch(s);
    setRecent(r);
    return s;
  }, [searchId, router]);

  useEffect(() => {
    load().catch(() => setSearch(null));
  }, [load]);

  useSearchRealtime({ searchId, search, setSearch, reload: load });

  useEffect(() => {
    if (autoResumeRef.current || !search) return;
    const createdMs = search.created_at ? new Date(search.created_at).getTime() : Date.now();
    const ageSec = (Date.now() - createdMs) / 1000;
    const queued = /queued/i.test(search.status_message || "");
    const stuckQueued = search.status === "running" && queued && ageSec > 20;
    const stuckNoJob =
      search.status === "running" &&
      !search.origami_job_id &&
      (search.lead_count ?? 0) === 0 &&
      ageSec > 60;
    if (stuckQueued || stuckNoJob) {
      autoResumeRef.current = true;
      resumeSearch(searchId)
        .then(() => load())
        .catch(() => {});
    }
  }, [search, searchId, load]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => {
    const o = search?.outreach;
    if (!o || search?.status !== "completed") return;
    setEmailSubject(o.email_subject);
    setEmailSteps([o.email_step1, o.email_step2, o.email_step3]);
    setLinkedInNote(o.linkedin_connection);
  }, [search?.outreach, search?.status, search?.linkedin_message_template]);

  useEffect(() => {
    if (autoNameSyncRef.current || !search || search.status !== "completed") return;
    const list = search.leads ?? [];
    if (list.length === 0) return;
    const missingNames = list.every((r) => !r.first_name?.trim() && !r.last_name?.trim());
    if (!missingNames) return;
    autoNameSyncRef.current = true;
    refreshSearchLeads(searchId)
      .then(() => load())
      .catch(() => {});
  }, [search, searchId, load]);

  const submitChat = async () => {
    const text = chatInput.trim();
    if (!text || chatSending) return;
    setChatSending(true);
    setChatMessages((m) => [...m, { role: "user", text }]);
    setChatInput("");
    try {
      const r = await searchAgentMessage(searchId, text);
      setChatMessages((m) => [...m, { role: "assistant", text: r.reply }]);
      if (r.outreach?.linkedin_connection) setLinkedInNote(r.outreach.linkedin_connection);
      await load();
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : "Could not update message";
      const err = friendlyChatError(raw, (search?.leads?.length ?? 0) > 0);
      setChatMessages((m) => [...m, { role: "assistant", text: err }]);
    } finally {
      setChatSending(false);
    }
  };

  const rows: SearchLead[] = search?.leads ?? [];
  const hasList = rows.length > 0;
  const selectedLead = rows.find((r) => r.id === selectedLeadId) ?? null;
  const progress = search?.progress;
  const building = search?.status === "running" && !hasList;
  const needsInput = search?.status === "needs_input" && !hasList;
  const failed = search?.status === "failed" && !hasList;
  const done = search?.status === "completed" || hasList;

  const openCampaign = async (leadId?: string) => {
    setCampaignLoading(true);
    try {
      const r = await prepareSearchCampaign(searchId);
      setCampaignId(r.campaign_id);
      setCampaignMeta(r.campaign);
      setCampaignEnrollments(r.enrollments);
      setCampaignLeadId(leadId || null);
      setCampaignOpen(true);
      await load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not open campaign");
    } finally {
      setCampaignLoading(false);
    }
  };

  useEffect(() => {
    if (campaignDeepLinkRef.current || !search || search.status !== "completed") return;
    if (searchParams.get("campaign") !== "1") return;
    campaignDeepLinkRef.current = true;
    openCampaign(searchParams.get("lead") || undefined);
  }, [search, searchParams]);

  const onResume = async () => {
    setResuming(true);
    try {
      await resumeSearch(searchId);
      await load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not resume search");
    } finally {
      setResuming(false);
    }
  };
  const title = search ? listTitle(search.prompt) : "…";

  const sampleLinkedIn = rows[0]?.linkedin_message ?? search?.outreach?.linkedin_connection ?? "";
  const wantsFounders = /founder/i.test(search?.prompt ?? "");

  const suggestedActions = useMemo(() => {
    if (!done || rows.length === 0) return [];
    const who = wantsFounders ? "founders" : "leads";
    return [
      "Type your LinkedIn step-1 note in the chat below (use {{first_name}}, {{company}})",
      "Click LinkedIn Outreach on a row to preview that founder’s connection draft",
      `Send from Talon — ${rows.length} ${who} (LinkedIn or email)`,
    ];
  }, [done, rows.length, wantsFounders]);

  const assistantBody = useMemo(() => {
    if (!search) return null;
    if (hasList) {
      const allDrafted = rows.every((r) => (r.linkedin_outreach_label || "").toLowerCase() === "drafted");
      return (
        <>
          <p style={{ margin: "0 0 8px" }}>
            <strong>{rows.length} {wantsFounders ? "founders" : "leads"}</strong> in your table.
            {allDrafted
              ? " LinkedIn connection notes are drafted and ready to go — click any row to preview."
              : " Say “reach out on LinkedIn” to draft messages for everyone."}
          </p>
          {allDrafted && sampleLinkedIn && (
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>
              Preview (step 1): {sampleLinkedIn.slice(0, 120)}
              {sampleLinkedIn.length > 120 ? "…" : ""}
            </p>
          )}
        </>
      );
    }
    if (done) {
      return (
        <>
          <p style={{ margin: "0 0 8px" }}>
            <strong>{rows.length} {wantsFounders ? "founders" : "leads"}</strong> ready — outreach copy is prepared.
            {search.status_message ? ` ${talonMessage(search.status_message)}` : ""}
          </p>
          {sampleLinkedIn && (
            <div className="hedwig-suggested" style={{ marginTop: 12, marginBottom: 12 }}>
              <h4>LinkedIn connection note (ready to send)</h4>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{sampleLinkedIn}</p>
              <button
                type="button"
                className="hedwig-send-export"
                style={{ marginTop: 12 }}
                onClick={() => setSendOpen(true)}
              >
                Send from Talon →
              </button>
            </div>
          )}
          <ul>
            <li>Per-founder LinkedIn + email preview in the table</li>
            <li>Email sequence pre-filled in Send &amp; export</li>
          </ul>
        </>
      );
    }
    if (failed) {
      return (
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "var(--text-secondary)" }}>
          {searchFailHint(search.status_message, hasList)}
        </p>
      );
    }
    return (
      <p style={{ margin: 0 }}>
        {building && <span className="hedwig-spinner" />}
        {talonMessage(search.status_message) || (wantsFounders ? "Finding founders…" : "Building your list…")}
      </p>
    );
  }, [search, done, building, failed, hasList, rows, sampleLinkedIn, wantsFounders]);

  if (campaignOpen && campaignId && campaignMeta) {
    return (
      <div className="hedwig-workspace">
        <SearchCampaignPane
          searchId={searchId}
          searchPrompt={search?.prompt ?? "Campaign"}
          campaignId={campaignId}
          campaign={campaignMeta}
          enrollments={campaignEnrollments}
          initialLeadId={campaignLeadId}
          onClose={() => setCampaignOpen(false)}
          onRefresh={() => load()}
        />
      </div>
    );
  }

  return (
    <div className="hedwig-workspace">
      <div className={`hedwig-workspace-panes${selectedLead ? " with-sequence" : ""}`}>
        {/* Agent chat */}
        <section className="hedwig-chat-pane">
          <header className="hedwig-chat-head">
            <p className="hedwig-chat-breadcrumb" title={search?.prompt}>
              {search?.prompt ?? "…"}
            </p>
            <button type="button" className="hedwig-icon-btn" title="History" aria-label="History">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
              </svg>
            </button>
          </header>

          <div className="hedwig-chat-scroll">
            {search && (
              <>
                <div className="hedwig-msg-user">{search.prompt}</div>
                <div className="hedwig-msg-assistant">{assistantBody}</div>
                {chatMessages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "hedwig-msg-user" : "hedwig-msg-assistant"}>
                    {m.text}
                  </div>
                ))}
                {chatSending && (
                  <div className="hedwig-msg-assistant">
                    <span className="hedwig-spinner" /> Updating…
                  </div>
                )}
                {(needsInput || failed) && (
                  <div style={{ marginTop: 16 }}>
                    {needsInput && (
                      <p style={{ fontSize: 12, color: "#b45309", margin: "0 0 10px" }}>
                        Talon needs a quick answer — click Continue to finish.
                      </p>
                    )}
                    <button
                      type="button"
                      className="hedwig-send-export"
                      disabled={resuming}
                      onClick={onResume}
                    >
                      {resuming ? "Starting…" : failed ? "Try again" : "Continue search"}
                    </button>
                  </div>
                )}
                {building && rows.length === 0 && search?.origami_job_id && (
                  <div style={{ marginTop: 12 }}>
                    <button type="button" className="btn-secondary" disabled={resuming} onClick={onResume}>
                      {resuming ? "Resuming…" : "Stuck? Resume polling"}
                    </button>
                  </div>
                )}
                <p style={{ marginTop: 12, fontSize: 12, color: "var(--text-muted)" }}>
                  Talon research · send and track outreach without leaving the app.
                </p>
              </>
            )}

            {suggestedActions.length > 0 && (
              <div className="hedwig-suggested">
                <h4>Suggested next actions</h4>
                <ol>
                  {suggestedActions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ol>
              </div>
            )}
          </div>

          <div className="hedwig-chat-input-bar">
            <div className="hedwig-chat-input-box">
              <button type="button" className="hedwig-icon-btn" aria-label="Attach">+</button>
              <textarea
                rows={1}
                placeholder="Set LinkedIn message for step 1… (e.g. Hi {{first_name}} — I'm Neil building…)"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitChat();
                  }
                }}
              />
              <div className="hedwig-input-tools">
                <span className="hedwig-lite-pill">Agent</span>
                <button
                  type="button"
                  className="hedwig-icon-btn"
                  aria-label="Send"
                  style={{ color: "#111" }}
                  disabled={chatSending || !chatInput.trim()}
                  onClick={submitChat}
                >
                  ↑
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Data workspace */}
        <section className="hedwig-data-pane">
          <div className="hedwig-tab-bar">
            {recent.slice(0, 8).map((r) => (
              <Link
                key={r.id}
                href={`/search/${r.id}`}
                className={`hedwig-tab${r.id === searchId ? " active" : ""}`}
                title={r.prompt}
              >
                {tabLabel(r.prompt)}
              </Link>
            ))}
            <Link href="/" className="hedwig-tab-add" title="New search">+</Link>
            <div className="hedwig-notify" title="Notifications">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
              </svg>
              {recent.length > 0 && <span className="hedwig-notify-badge">{Math.min(recent.length, 9)}</span>}
            </div>
          </div>

          {!hasList && (building || progress) && (
            <div className="hedwig-progress-wrap">
              <div className="hedwig-progress-track">
                <div
                  className="hedwig-progress-fill"
                  style={{ width: `${progress?.percent ?? (building ? 12 : 0)}%` }}
                />
              </div>
              <div className="hedwig-progress-label">
                <span>{talonMessage(progress?.label ?? search?.status_message) || "Working…"}</span>
                <span>
                  {progress?.leads_found ?? rows.length}{" "}
                  {wantsFounders ? "founders" : "leads"}
                </span>
              </div>
            </div>
          )}

          <div className="hedwig-list-header">
            <h1 className="hedwig-list-title">{title}</h1>
            <div className="hedwig-list-meta">
              <span className="hedwig-est-leads">
                Est. total leads: <strong>{rows.length || search?.lead_count || "—"}</strong>
                <span style={{ color: "var(--text-muted)" }}>▾</span>
              </span>
              <div className="hedwig-list-actions">
                <a href="/">Get More Leads</a>
                <a href="/">Expand search</a>
              </div>
            </div>
          </div>

          <div className="hedwig-table-toolbar">
            <span className="hedwig-toolbar-count">
              {rows.length} {wantsFounders ? "founders" : "leads"} · 8 columns
            </span>
            {rows.length > 0 && (
              <div className="hedwig-update-pill">
                <button
                  type="button"
                  disabled={campaignLoading}
                  onClick={() => openCampaign()}
                >
                  {campaignLoading ? "Opening…" : `${rows.length} rows ready ›`}
                </button>
              </div>
            )}
            <div className="hedwig-toolbar-right">
              {done && (
                <button
                  type="button"
                  className="btn-secondary"
                  style={{ fontSize: 12, padding: "6px 12px" }}
                  disabled={refreshing}
                  onClick={async () => {
                    setRefreshing(true);
                    try {
                      await refreshSearchLeads(searchId);
                      await load();
                    } catch (e: unknown) {
                      alert(e instanceof Error ? e.message : "Refresh failed");
                    } finally {
                      setRefreshing(false);
                    }
                  }}
                >
                  {refreshing ? "Syncing…" : "Sync names"}
                </button>
              )}
              <button type="button" className="hedwig-toolbar-icon" title="Filter" aria-label="Filter">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 6h16M7 12h10M10 18h4" />
                </svg>
              </button>
              <button type="button" className="hedwig-toolbar-icon" title="Columns" aria-label="Columns">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="18" rx="1" />
                </svg>
              </button>
              <div style={{ position: "relative" }} ref={menuRef}>
                <button
                  type="button"
                  className="hedwig-send-export"
                  disabled={rows.length === 0}
                  onClick={() => setMenuOpen(!menuOpen)}
                >
                  Send &amp; export <span style={{ opacity: 0.7 }}>▾</span>
                </button>
                {menuOpen && (
                  <div className="hedwig-send-menu">
                    <button type="button" onClick={() => { setMenuOpen(false); setSendOpen(true); }}>
                      Send from Talon…
                    </button>
                    <a href={searchExportCsvUrl(searchId)} onClick={() => setMenuOpen(false)}>
                      Export CSV
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="hedwig-table-wrap">
            <table className="hedwig-table">
              <thead>
                <tr>
                  {["#", "First Name", "Last Name", "Title", "Company", "LinkedIn", "LinkedIn Outreach", "Score"].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
                      {building ? (
                        <>
                          <span className="hedwig-spinner" />
                          {talonMessage(search?.status_message) || (wantsFounders ? "Finding founders…" : "Building list…")}
                        </>
                      ) : (
                        wantsFounders ? "No founders yet — still building your list" : "No leads yet"
                      )}
                    </td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                      <tr
                        key={r.id}
                        style={{ background: r.id === selectedLeadId ? "var(--accent-light)" : undefined }}
                      >
                        <td style={{ color: "var(--text-muted)" }}>{i + 1}</td>
                        <td>{r.first_name || "—"}</td>
                        <td>{r.last_name || "—"}</td>
                        <td>{r.title || "—"}</td>
                        <td>{r.company || "—"}</td>
                        <td>
                          {r.linkedin_url ? (
                            <a
                              href={r.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: "#0077B5", fontSize: 12 }}
                            >
                              {(r.linkedin_url || "").split("/in/")[1]?.replace(/\/$/, "") || "Profile"}
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            className={`hedwig-outreach-badge ${outreachBadgeClass(r.linkedin_outreach_label || "Ready")}`}
                            disabled={campaignLoading}
                            onClick={() => {
                              const drafted =
                                (r.linkedin_outreach_label || "").toLowerCase() === "drafted";
                              if (drafted || hasList) {
                                openCampaign(r.id);
                              } else {
                                setSelectedLeadId(r.id);
                              }
                            }}
                          >
                            {r.linkedin_outreach_label || "Ready"}
                          </button>
                        </td>
                        <td style={{ fontWeight: 600 }}>{r.score}</td>
                      </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        {selectedLead && (
          <section className="hedwig-sequence-pane">
            <div className="hedwig-chat-head">
              <p className="hedwig-chat-breadcrumb" style={{ maxWidth: "100%" }}>
                {[selectedLead.first_name, selectedLead.last_name].filter(Boolean).join(" ") || "Founder"}
              </p>
              <button type="button" className="hedwig-icon-btn" onClick={() => setSelectedLeadId(null)} aria-label="Close">
                ×
              </button>
            </div>
            <div className="panel-scroll" style={{ padding: 16 }}>
              <p style={{ margin: "0 0 12px", fontSize: 12, color: "var(--text-muted)" }}>
                {[selectedLead.title, selectedLead.company].filter(Boolean).join(" · ")}
              </p>
              <div className="step-card">
                <div className="step-card-head">
                  <span style={{ fontWeight: 600 }}>Step 1 — Connection request</span>
                  <span className="badge badge-gray">
                    {(selectedLead.linkedin_outreach_label || "").toLowerCase() === "drafted"
                      ? "Drafted and ready to go"
                      : "Draft"}
                  </span>
                </div>
                <div style={{ padding: 14 }}>
                  <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
                    {selectedLead.linkedin_message}
                  </p>
                  <p style={{ margin: "8px 0 0", fontSize: 11, color: "var(--text-muted)" }}>
                    {(selectedLead.linkedin_message || "").length} / 300
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="hedwig-send-export"
                style={{ width: "100%", marginTop: 8 }}
                disabled={sendingLi || !selectedLead.linkedin_url}
                onClick={async () => {
                  setSendingLi(true);
                  try {
                    const r = await sendSearchLinkedIn(searchId, {
                      lead_ids: [selectedLead.id],
                      connection_note_template: selectedLead.linkedin_message,
                    });
                    await load();
                    setSelectedLeadId(selectedLead.id);
                    if (r.campaign_id) router.push(`/sequencing/campaigns/${r.campaign_id}`);
                  } catch (e: unknown) {
                    alert(e instanceof Error ? e.message : "Send failed");
                  } finally {
                    setSendingLi(false);
                  }
                }}
              >
                {sendingLi ? "Sending…" : "Send connection (step 1)"}
              </button>
              {selectedLead.linkedin_url && (
                <p style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)", wordBreak: "break-all" }}>
                  {selectedLead.linkedin_url}
                </p>
              )}
            </div>
          </section>
        )}
      </div>

      {sendOpen && (
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}
          onClick={() => setSendOpen(false)}
        >
          <div className="card" style={{ width: "min(540px, 92vw)", padding: 24 }} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ margin: "0 0 6px", fontSize: 18 }}>Send from Talon</h2>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: "var(--text-secondary)" }}>
              Your list is ready — run outreach here without leaving Talon.
            </p>

            <div style={{ marginBottom: 20, padding: 14, background: "#fafafa", borderRadius: 10, border: "1px solid var(--border)" }}>
              <p style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 700 }}>LinkedIn sequences</p>
              <textarea
                value={linkedInNote}
                onChange={(e) => setLinkedInNote(e.target.value)}
                rows={4}
                style={{ width: "100%", fontSize: 13, padding: 10, borderRadius: 8, border: "1px solid var(--border)", fontFamily: "inherit" }}
              />
              <button
                type="button"
                className="hedwig-send-export"
                style={{ marginTop: 10 }}
                disabled={sendingLi || rows.length === 0}
                onClick={async () => {
                  setSendingLi(true);
                  try {
                    const r = await sendSearchLinkedIn(searchId, {
                      connection_note_template: linkedInNote,
                    });
                    setSendOpen(false);
                    router.push(`/sequencing/campaigns/${r.campaign_id}`);
                  } catch (e: unknown) {
                    alert(e instanceof Error ? e.message : "LinkedIn send failed");
                  } finally {
                    setSendingLi(false);
                  }
                }}
              >
                {sendingLi ? "Launching…" : `Send ${rows.length} LinkedIn connection${rows.length === 1 ? "" : "s"}`}
              </button>
            </div>

            <div style={{ marginBottom: 16, padding: 14, background: "#fafafa", borderRadius: 10, border: "1px solid var(--border)" }}>
              <p style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 700 }}>Email (Instantly)</p>
              <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--text-muted)" }}>
                Pre-filled 3-step sequence — edit before pushing.
              </p>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => { setSendOpen(false); setInstantlyOpen(true); }}
              >
                Configure email &amp; send →
              </button>
            </div>

            <button type="button" className="btn-ghost" onClick={() => setSendOpen(false)}>Cancel</button>
          </div>
        </div>
      )}

      {instantlyOpen && (
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}
          onClick={() => setInstantlyOpen(false)}
        >
          <div className="card" style={{ width: "min(520px, 92vw)", padding: 24 }} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ margin: "0 0 8px", fontSize: 18 }}>Email from Talon (Instantly)</h2>
            <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--text-secondary)" }}>
              Stays in Talon — pushes to Instantly using your campaign ID. Variables: {"{{first_name}}"}, {"{{company}}"}.
            </p>
            <label style={{ fontSize: 12, fontWeight: 600 }}>Subject</label>
            <input
              value={emailSubject}
              onChange={(e) => setEmailSubject(e.target.value)}
              style={{ width: "100%", marginBottom: 12, padding: 10, borderRadius: 8, border: "1px solid var(--border)" }}
            />
            {emailSteps.map((step, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 12, fontWeight: 600 }}>Step {i + 1}</label>
                <textarea
                  value={step}
                  onChange={(e) => {
                    const n = [...emailSteps];
                    n[i] = e.target.value;
                    setEmailSteps(n);
                  }}
                  rows={3}
                  style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid var(--border)", fontFamily: "inherit", fontSize: 13 }}
                />
              </div>
            ))}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <a href={searchExportCsvUrl(searchId)} className="btn-secondary" style={{ textDecoration: "none" }} onClick={() => setInstantlyOpen(false)}>
                Export CSV
              </a>
              <button type="button" className="btn-ghost" onClick={() => setInstantlyOpen(false)}>Cancel</button>
              <button
                type="button"
                className="btn-primary"
                disabled={pushing}
                onClick={async () => {
                  setPushing(true);
                  try {
                    const r = await pushSearchToInstantly(searchId, {
                      subject: emailSubject,
                      step1_body: emailSteps[0],
                      step2_body: emailSteps[1],
                      step3_body: emailSteps[2],
                    });
                    alert(r.dry_run ? `Dry run: ${r.pushed} leads` : `Pushed ${r.pushed} to Instantly (${r.skipped} skipped — no email)`);
                    setInstantlyOpen(false);
                    load();
                  } catch (e: unknown) {
                    alert(e instanceof Error ? e.message : "Push failed");
                  } finally {
                    setPushing(false);
                  }
                }}
              >
                {pushing ? "Pushing…" : "Push to Instantly"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40 }}>Loading…</div>}>
      <SearchWorkspace />
    </Suspense>
  );
}
