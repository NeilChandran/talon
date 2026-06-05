"use client";

import { useCallback, useEffect, useRef, useState, Suspense } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  createWorkspaceList,
  getLinkedInStatus,
  getWorkspaces,
  getWorkspace,
  getWorkspaceAgentHistory,
  getWorkspaceList,
  launchFromList,
  listExportCsvUrl,
  pushListToInstantly,
  sendWorkspaceAgentMessage,
} from "@/lib/api";
import type {
  AgentChatMessage,
  LinkedInSession,
  ListLeadRow,
  SuggestedAction,
  Workspace,
  WorkspaceListDetail,
  WorkspaceListMeta,
} from "@/types";

function WorkspaceInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const workspaceId = params.id as string;

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [allWorkspaces, setAllWorkspaces] = useState<Workspace[]>([]);
  const [activeListId, setActiveListId] = useState<string | null>(null);
  const [listDetail, setListDetail] = useState<WorkspaceListDetail | null>(null);
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [lastActions, setLastActions] = useState<SuggestedAction[]>([]);
  const [liSession, setLiSession] = useState<LinkedInSession | null>(null);
  const [copy, setCopy] = useState({ connection: "", followup: "", waitDays: 1 });
  const [launching, setLaunching] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportMode, setExportMode] = useState<"linkedin" | "email" | null>(null);
  const [emailSubject, setEmailSubject] = useState("Quick intro — {{company}}");
  const [emailSteps, setEmailSteps] = useState([
    "Hi {{first_name}},\n\nI noticed your work at {{company}} and wanted to reach out…",
    "Following up — still think this could be valuable for {{company}}.",
    "Last note from me — happy to connect whenever timing works.",
  ]);
  const [instantlyPushing, setInstantlyPushing] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const chatBottom = useRef<HTMLDivElement>(null);

  const loadWorkspace = useCallback(async () => {
    const ws = await getWorkspace(workspaceId);
    setWorkspace(ws);
    const listFromUrl = searchParams.get("list");
    const first = listFromUrl || ws.lists?.[0]?.id;
    if (first) setActiveListId((prev) => prev ?? first);
  }, [workspaceId, searchParams]);

  const loadList = useCallback(async () => {
    if (!activeListId) return;
    const detail = await getWorkspaceList(workspaceId, activeListId);
    setListDetail(detail);
    if (detail.status === "building") {
      if (!pollRef.current) {
        pollRef.current = setInterval(() => loadList(), 1500);
      }
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [workspaceId, activeListId]);

  useEffect(() => {
    loadWorkspace();
    getWorkspaces().then(setAllWorkspaces).catch(() => {});
    getLinkedInStatus().then(setLiSession).catch(() => {});
  }, [loadWorkspace]);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  useEffect(() => {
    if (!activeListId) return;
    getWorkspaceAgentHistory(workspaceId, activeListId).then(setMessages).catch(() => {});
  }, [workspaceId, activeListId]);

  useEffect(() => {
    chatBottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatLoading]);

  const sendChat = async (text: string) => {
    if (!text.trim() || chatLoading) return;
    setChatInput("");
    setChatLoading(true);
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: text, suggested_actions: [], created_at: new Date().toISOString() }]);
    try {
      const res = await sendWorkspaceAgentMessage(workspaceId, text, activeListId ?? undefined);
      setMessages((m) => [...m, { id: `a-${Date.now()}`, role: "assistant", content: res.reply, suggested_actions: res.suggested_actions.map((a) => a.label), created_at: new Date().toISOString() }]);
      setLastActions(res.suggested_actions);
      if (res.apply_copy?.connection_note_template) setCopy((c) => ({ ...c, connection: res.apply_copy!.connection_note_template! }));
      if (res.apply_copy?.message_template) setCopy((c) => ({ ...c, followup: res.apply_copy!.message_template! }));
      if (res.apply_copy?.wait_days_after_accept != null) setCopy((c) => ({ ...c, waitDays: res.apply_copy!.wait_days_after_accept! }));
      if (res.campaign_id) router.push(`/sequencing/campaigns/${res.campaign_id}`);
    } catch (e: unknown) {
      setMessages((m) => [...m, { id: `e-${Date.now()}`, role: "assistant", content: e instanceof Error ? e.message : "Error", suggested_actions: [], created_at: new Date().toISOString() }]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleAction = async (action: string) => {
    if (action === "launch_sequences" || action === "launch_campaign") await handleLaunch();
    else if (action === "open_settings") router.push("/settings");
    else if (action === "create_list" && newListPrompt.trim()) {
      await createWorkspaceList(workspaceId, newListPrompt);
      setNewListPrompt("");
      loadWorkspace();
    }
  };

  const handleLaunch = async () => {
    if (!activeListId || !listDetail?.rows?.length) {
      alert("Wait for the list to finish building, or add leads first.");
      return;
    }
    if (!liSession?.connected) {
      router.push("/settings");
      return;
    }
    setLaunching(true);
    try {
      const res = await launchFromList(workspaceId, activeListId, {
        connection_note_template: copy.connection || undefined,
        message_template: copy.followup || undefined,
        wait_days_after_accept: copy.waitDays,
        campaign_name: listDetail ? `${listDetail.name} — LinkedIn Outreach` : undefined,
      });
      router.push(`/sequencing/campaigns/${res.campaign_id}`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Launch failed");
    } finally {
      setLaunching(false);
    }
  };

  const rows: ListLeadRow[] = listDetail?.rows ?? [];
  const lists: WorkspaceListMeta[] = workspace?.lists ?? [];

  return (
    <div className="workspace-shell" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Link href="/workspaces" style={{ fontSize: 12, color: "var(--text-muted)", textDecoration: "none" }}>← Workspaces</Link>
        <h1 style={{ margin: 0, fontSize: 15, fontWeight: 600, flex: 1 }}>{workspace?.name ?? "…"}</h1>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {lists.map((l) => (
            <button key={l.id} type="button" className={`campaign-chip${activeListId === l.id ? " active" : ""}`}
              onClick={() => setActiveListId(l.id)}>
              {l.name} {l.status === "building" ? "…" : `(${l.row_count})`}
            </button>
          ))}
          <button type="button" className="campaign-chip" style={{ borderStyle: "dashed" }} onClick={async () => {
            const p = prompt("Describe the list to build:");
            if (!p) return;
            const created = await createWorkspaceList(workspaceId, p);
            setActiveListId(created.id);
            loadWorkspace();
          }}>+ List</button>
        </div>
      </div>

      <div className="workspace-body" style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {/* Left: all workspaces */}
        <div className="panel" style={{ width: 200, minWidth: 180, borderRight: "1px solid var(--border)" }}>
          <div className="panel-header">
            <p className="panel-header-label">Workspaces</p>
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {allWorkspaces.map((w) => (
              <Link
                key={w.id}
                href={`/workspaces/${w.id}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 14px",
                  textDecoration: "none",
                  color: "inherit",
                  background: w.id === workspaceId ? "var(--accent-light)" : "transparent",
                  borderLeft: w.id === workspaceId ? "3px solid var(--accent)" : "3px solid transparent",
                }}
              >
                <span style={{ width: 26, height: 26, borderRadius: "50%", background: "#e8e8ea", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>
                  {w.icon_letter}
                </span>
                <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{w.name}</span>
              </Link>
            ))}
            <Link href="/" style={{ display: "block", padding: "12px 14px", fontSize: 12, color: "var(--accent)", fontWeight: 600, textDecoration: "none" }}>+ New search</Link>
          </div>
        </div>

        {/* Middle: agent status */}
        <div className="panel" style={{ width: "min(340px, 32%)", minWidth: 280 }}>
          <div className="panel-header">
            <p className="panel-header-label">Talon AI</p>
            <p className="panel-header-title">{listDetail?.name ?? workspace?.name}</p>
            {!liSession?.connected && (
              <p style={{ margin: "8px 0 0", fontSize: 12, color: "#b45309" }}>
                <Link href="/settings" style={{ color: "var(--accent)", fontWeight: 600 }}>Connect LinkedIn</Link> to send sequences
              </p>
            )}
          </div>
          <div className="panel-scroll">
            {listDetail?.status === "building" && (
              <div style={{ padding: "8px 4px", fontSize: 12, color: "var(--accent)", lineHeight: 1.5 }}>
                <strong>Running search agents…</strong>
                <br />
                {listDetail.build_step}
              </div>
            )}
            {messages.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                Ask me to refine connection notes, update follow-up DMs, or launch LinkedIn sequences for this list.
              </p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`chat-bubble ${m.role}`}>
                <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: m.role === "user" ? "var(--accent)" : "var(--text-secondary)" }}>
                  {m.role === "user" ? "You" : "Talon AI"}
                </div>
                {m.content}
              </div>
            ))}
            {chatLoading && <p style={{ fontSize: 12, color: "var(--text-muted)" }}>Thinking…</p>}
            <div ref={chatBottom} />
          </div>
          {lastActions.length > 0 && (
            <div style={{ padding: "8px 12px", borderTop: "1px solid var(--border-light)", display: "flex", flexDirection: "column", gap: 6 }}>
              {lastActions.map((a) => (
                <button key={a.id} type="button" className="btn-secondary" style={{ width: "100%", justifyContent: "flex-start" }} onClick={() => handleAction(a.action)}>
                  {a.label}
                </button>
              ))}
            </div>
          )}
          <div className="chat-input-wrap">
            <textarea className="chat-input" value={chatInput} onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(chatInput); } }}
              placeholder="What should I do instead…" rows={2} />
            <button type="button" className="btn-primary" style={{ width: "100%" }} disabled={chatLoading} onClick={() => sendChat(chatInput)}>Send</button>
          </div>
        </div>

        {/* Table panel */}
        <div className="panel" style={{ flex: 1, borderRight: "none" }}>
          <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div>
              <p className="panel-header-title">{listDetail?.name ?? "Select a list"}</p>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
                {rows.length} leads · 8 columns
                {listDetail?.status === "building" && ` · Running search agents… ${listDetail.build_step}`}
                {listDetail?.origami_meta?.tableUrl && (
                  <> · <a href={listDetail.origami_meta.tableUrl} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>Open source table</a></>
                )}
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
              <button type="button" className="btn-primary" disabled={rows.length === 0} onClick={() => setExportOpen(!exportOpen)}>
                Send & export ▾
              </button>
              {exportOpen && (
                <div style={{ position: "absolute", top: "100%", right: 0, marginTop: 8, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "var(--shadow-card)", minWidth: 220, zIndex: 20 }}>
                  <button type="button" className="btn-ghost" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 0 }} onClick={() => { setExportOpen(false); setExportMode("linkedin"); handleLaunch(); }}>LinkedIn sequences</button>
                  <button type="button" className="btn-ghost" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 0 }} onClick={() => { setExportOpen(false); setExportMode("email"); }}>Email via Instantly</button>
                  <a href={activeListId ? listExportCsvUrl(activeListId) : "#"} className="btn-ghost" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 0, textDecoration: "none" }} onClick={() => setExportOpen(false)}>Export CSV</a>
                </div>
              )}
            </div>
          </div>

          <div style={{ flex: 1, overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", background: "#fafafa", position: "sticky", top: 0 }}>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, width: 40 }}>#</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>First Name</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>Last Name</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>Title</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>Company</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>Email</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600 }}>LinkedIn</th>
                  <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, width: 50 }}>Score</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
                      {listDetail?.status === "building" ? (listDetail.build_step || "Running search agents…") : "No rows yet — create a list or wait for build to finish."}
                    </td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                    <tr key={r.id} style={{ borderBottom: "1px solid var(--border-light)" }}>
                      <td style={{ padding: "10px 12px", color: "var(--text-muted)" }}>{i + 1}</td>
                      <td style={{ padding: "10px 12px" }}>{r.first_name}</td>
                      <td style={{ padding: "10px 12px" }}>{r.last_name}</td>
                      <td style={{ padding: "10px 12px" }}>{r.title}</td>
                      <td style={{ padding: "10px 12px" }}>{r.company}</td>
                      <td style={{ padding: "10px 12px", fontSize: 12 }}>{r.email || "—"}</td>
                      <td style={{ padding: "10px 12px" }}>
                        {r.linkedin_url ? <a href={r.linkedin_url} target="_blank" rel="noopener noreferrer" style={{ color: "#0077B5", fontSize: 12 }}>Profile</a> : "—"}
                      </td>
                      <td style={{ padding: "10px 12px" }}>{r.icp_score || "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {exportMode === "email" && activeListId && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }} onClick={() => setExportMode(null)}>
          <div className="card" style={{ width: "min(520px, 92vw)", padding: 24, maxHeight: "85vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ margin: "0 0 8px", fontSize: 18 }}>Email sequence (Instantly)</h2>
            <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--text-secondary)" }}>Use {"{{first_name}}"} and {"{{company}}"} in copy. Set campaign ID in Settings.</p>
            <label style={{ fontSize: 12, fontWeight: 600 }}>Subject</label>
            <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)} style={{ width: "100%", marginBottom: 12, padding: 10, borderRadius: 8, border: "1px solid var(--border)" }} />
            {emailSteps.map((step, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 12, fontWeight: 600 }}>Step {i + 1}</label>
                <textarea value={step} onChange={(e) => { const n = [...emailSteps]; n[i] = e.target.value; setEmailSteps(n); }} rows={4} style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid var(--border)", fontFamily: "inherit", fontSize: 13 }} />
              </div>
            ))}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button type="button" className="btn-ghost" onClick={() => setExportMode(null)}>Cancel</button>
              <button type="button" className="btn-primary" disabled={instantlyPushing} onClick={async () => {
                setInstantlyPushing(true);
                try {
                  const r = await pushListToInstantly(activeListId, { subject: emailSubject, step1_body: emailSteps[0], step2_body: emailSteps[1], step3_body: emailSteps[2] });
                  alert(r.dry_run ? `Dry run: would push ${r.pushed} leads` : `Pushed ${r.pushed} leads to Instantly (${r.skipped} skipped — no email)`);
                  setExportMode(null);
                } catch (e: unknown) {
                  alert(e instanceof Error ? e.message : "Instantly push failed");
                } finally {
                  setInstantlyPushing(false);
                }
              }}>{instantlyPushing ? "Pushing…" : "Push to Instantly"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function WorkspacePage() {
  return (
    <Suspense fallback={<div style={{ padding: 40 }}>Loading workspace…</div>}>
      <WorkspaceInner />
    </Suspense>
  );
}
