"use client";

import { useEffect, useRef, useState } from "react";
import {
  getSequences, createSequence, updateSequence, deleteSequence,
  runSequence, getAutomationJob, getLeads, getLinkedInStatus,
  testLinkedInSession, getSendCap, checkReplies,
} from "@/lib/api";
import { peek, put } from "@/lib/cache";
import type { AutomationJob, Lead, LinkedInSession, ReplyCheckResult, SendCapStatus, Sequence, SequenceType } from "@/types";

const TYPE_META: Record<SequenceType, { label: string; color: string; bg: string; border: string; desc: string; delay: string }> = {
  connection_request: {
    label: "Connection Request", color: "#1b6fd8", bg: "#eff6ff", border: "#bfdbfe",
    desc: "Personalized ≤300-char note sent with the connection invite.", delay: "Day 0",
  },
  follow_up_message: {
    label: "Follow-up Message", color: "#92400e", bg: "#fffbeb", border: "#fde68a",
    desc: "Message sent after the connection is accepted.", delay: "Day 3",
  },
  final_message: {
    label: "Final Message", color: "#166534", bg: "#f0fdf4", border: "#bbf7d0",
    desc: "Short final touch — leaves the door open warmly.", delay: "Day 7",
  },
};

// ─── Edit modal ───────────────────────────────────────────────────────────────

function Modal({ seq, onClose, onSave }: {
  seq: Partial<Sequence> | null; onClose: () => void; onSave: (d: any) => Promise<void>;
}) {
  const [name, setName] = useState(seq?.name ?? "");
  const [type, setType] = useState<SequenceType>(seq?.type ?? "connection_request");
  const [note, setNote] = useState(seq?.connection_note_template ?? "");
  const [msg, setMsg] = useState(seq?.message_template ?? "");
  const [delay, setDelay] = useState(seq?.delay_days ?? 0);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave({ name, type, connection_note_template: note, message_template: msg, delay_days: delay }); onClose(); }
    catch (e) { console.error(e); }
    finally { setSaving(false); }
  };

  const isConn = type === "connection_request";

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(3px)" }}>
      <div className="card" style={{ width: "100%", maxWidth: 560, margin: "0 16px", overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.18)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", borderBottom: "1px solid #e8e8ea" }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0a0a0a" }}>{seq?.id ? "Edit Sequence" : "New Sequence"}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#8a8a8e", lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <label className="label">Sequence Name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Cold Connect" className="input" />
            </div>
            <div>
              <label className="label">Type</label>
              <select value={type} onChange={e => setType(e.target.value as SequenceType)} className="input" style={{ cursor: "pointer" }}>
                <option value="connection_request">Connection Request</option>
                <option value="follow_up_message">Follow-up Message</option>
                <option value="final_message">Final Message</option>
              </select>
            </div>
          </div>

          {isConn ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <label className="label" style={{ margin: 0 }}>Connection Note <span style={{ color: "#8a8a8e", fontWeight: 400 }}>(max 300 chars)</span></label>
                <span style={{ fontSize: 11, color: note.length > 280 ? "#6E56CF" : "#8a8a8e", fontFamily: "monospace" }}>{note.length}/300</span>
              </div>
              <textarea
                value={note}
                onChange={e => setNote(e.target.value.slice(0, 300))}
                rows={4}
                placeholder="Hi {{first_name}}, love what you're building at {{company}}..."
                className="input"
                style={{ resize: "none", fontFamily: "inherit" }}
              />
              <p style={{ margin: "6px 0 0", fontSize: 11, color: "#8a8a8e" }}>Use {"{{first_name}}"} and {"{{company}}"}. Leave blank to use AI-generated notes.</p>
            </div>
          ) : (
            <div>
              <label className="label">Message Template</label>
              <textarea
                value={msg}
                onChange={e => setMsg(e.target.value)}
                rows={6}
                placeholder={"Hey {{first_name}}, thanks for connecting!\n\n..."}
                className="input"
                style={{ resize: "none", fontFamily: "inherit" }}
              />
              <p style={{ margin: "6px 0 0", fontSize: 11, color: "#8a8a8e" }}>Use {"{{first_name}}"} and {"{{company}}"}. Leave blank for AI-generated messages.</p>
            </div>
          )}

          <div>
            <label className="label">Delay (days after first touch)</label>
            <input type="number" value={delay} onChange={e => setDelay(Number(e.target.value))} min={0} className="input" style={{ width: 80 }} />
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "16px 24px", borderTop: "1px solid #e8e8ea" }}>
          <button onClick={onClose} style={{ padding: "8px 16px", background: "none", border: "1.5px solid #d8d8dc", borderRadius: 7, fontSize: 13, cursor: "pointer", color: "#3a3a3c" }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !name} className="btn-primary">{saving ? "Saving..." : "Save Sequence"}</button>
        </div>
      </div>
    </div>
  );
}

// ─── Run modal ────────────────────────────────────────────────────────────────

function RunModal({ seq, leads, onClose }: { seq: Sequence; leads: Lead[]; onClose: () => void; }) {
  const [selected, setSelected] = useState<Set<string>>(new Set(leads.filter(l => l.status === "new").map(l => l.id)));
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<AutomationJob | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const stopPoll = () => { if (pollRef.current) clearInterval(pollRef.current); };

  useEffect(() => {
    if (!jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const j = await getAutomationJob(jobId);
        setJob(j);
        if (j.status === "completed" || j.status === "failed") stopPoll();
      } catch {}
    }, 2000);
    return stopPoll;
  }, [jobId]);

  const handleRun = async () => {
    if (selected.size === 0) return;
    setStarting(true);
    try { const r = await runSequence(seq.id, Array.from(selected)); setJobId(r.job_id); }
    catch (e: any) { alert(e.message || "Failed to start"); }
    finally { setStarting(false); }
  };

  const isDone = job?.status === "completed" || job?.status === "failed";
  const pct = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(3px)" }}>
      <div className="card" style={{ width: "100%", maxWidth: 560, margin: "0 16px", overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.18)", maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", borderBottom: "1px solid #e8e8ea", flexShrink: 0 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0a0a0a" }}>Run: {seq.name}</h2>
            <p style={{ margin: "3px 0 0", fontSize: 12, color: "#6b6b70" }}>{TYPE_META[seq.type]?.desc}</p>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#8a8a8e" }}>×</button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {!job ? (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>Select leads ({selected.size} selected)</p>
                <button onClick={() => { if (selected.size === leads.length) setSelected(new Set()); else setSelected(new Set(leads.map(l => l.id))); }}
                  style={{ fontSize: 12, color: "#6E56CF", background: "none", border: "none", cursor: "pointer" }}>
                  {selected.size === leads.length ? "Deselect all" : "Select all"}
                </button>
              </div>

              <div style={{ border: "1.5px solid #e8e8ea", borderRadius: 8, maxHeight: 280, overflowY: "auto" }}>
                {leads.map((lead, i) => (
                  <label key={lead.id} style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "10px 14px",
                    borderBottom: i < leads.length - 1 ? "1px solid #f0f0f2" : "none",
                    cursor: "pointer",
                    background: selected.has(lead.id) ? "#fff5f6" : "#fff",
                    transition: "background 0.08s",
                  }}>
                    <input type="checkbox" checked={selected.has(lead.id)} onChange={() => {
                      const next = new Set(selected); next.has(lead.id) ? next.delete(lead.id) : next.add(lead.id); setSelected(next);
                    }} style={{ accentColor: "#6E56CF", flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "#0a0a0a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lead.name}</p>
                      <p style={{ margin: 0, fontSize: 11, color: "#6b6b70", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{[lead.title, lead.company].filter(Boolean).join(" · ")}</p>
                    </div>
                    <div style={{ flexShrink: 0 }}>
                      {lead.linkedin_url
                        ? <span style={{ fontSize: 10, color: "#0077B5", fontWeight: 600 }}>● LinkedIn</span>
                        : <span style={{ fontSize: 10, color: "#d0d0d4", fontWeight: 500 }}>No URL</span>
                      }
                    </div>
                  </label>
                ))}
              </div>
              <p style={{ margin: "8px 0 0", fontSize: 11, color: "#8a8a8e" }}>
                All leads with a LinkedIn URL will be automated — profile IDs are resolved automatically if missing.
              </p>

              {(seq.connection_note_template || seq.message_template) && (
                <div style={{ marginTop: 18 }}>
                  <p style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 600, color: "#3a3a3c" }}>Template preview</p>
                  <div style={{ background: "#f7f7f8", border: "1px solid #e8e8ea", borderRadius: 8, padding: "12px 14px" }}>
                    <p style={{ margin: 0, fontSize: 13, color: "#1a1a1e", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                      {seq.connection_note_template || seq.message_template}
                    </p>
                    {seq.connection_note_template && (
                      <p style={{ margin: "8px 0 0", fontSize: 11, color: "#8a8a8e" }}>{seq.connection_note_template.length}/300 chars · {"{{first_name}}"} and {"{{company}}"} are replaced per lead</p>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div>
              {/* Progress */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>
                    {job.status === "running" ? "Running..." : job.status === "completed" ? "Done" : job.status === "pending" ? "Starting..." : "Failed"}
                  </span>
                  <span style={{ fontSize: 13, color: "#6b6b70" }}>{job.done}/{job.total}</span>
                </div>
                <div style={{ height: 8, background: "#f0f0f2", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ height: "100%", background: "#6E56CF", width: `${pct}%`, transition: "width 0.5s", borderRadius: 4 }} />
                </div>
              </div>

              {/* Stats */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 20 }}>
                {[{ label: "Sent", value: job.sent, color: "#166534", bg: "#f0fdf4", border: "#bbf7d0" },
                  { label: "Failed", value: job.failed, color: "#9f1239", bg: "#fff1f2", border: "#E4DEFF" },
                  { label: "Left", value: job.total - job.done, color: "#6b6b70", bg: "#f7f7f8", border: "#e8e8ea" }
                ].map(s => (
                  <div key={s.label} style={{ background: s.bg, border: `1px solid ${s.border}`, borderRadius: 8, padding: "14px", textAlign: "center" }}>
                    <div style={{ fontSize: 24, fontWeight: 700, color: s.color, letterSpacing: "-0.04em" }}>{s.value}</div>
                    <div style={{ fontSize: 11, color: s.color, marginTop: 2, fontWeight: 500 }}>{s.label}</div>
                  </div>
                ))}
              </div>

              {job.status === "running" && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: "#f7f7f8", border: "1px solid #e8e8ea", borderRadius: 8, marginBottom: 16 }}>
                  <div style={{ width: 14, height: 14, border: "2px solid #6E56CF", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite", flexShrink: 0 }} />
                  <span style={{ fontSize: 13, color: "#3a3a3c" }}>
                    {job.step || (job.current ? `Sending to ${job.current}...` : "Working...")}
                  </span>
                </div>
              )}

              {job.status === "failed" && job.error && (
                <div style={{ padding: "10px 14px", background: "#fff1f2", border: "1px solid #E4DEFF", borderRadius: 7, fontSize: 13, color: "#9f1239", marginBottom: 16 }}>
                  {job.error}
                </div>
              )}

              {job.results.length > 0 && (
                <div style={{ maxHeight: 200, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                  {job.results.map((r, i) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "8px 12px", borderRadius: 7, fontSize: 12,
                      background: r.status === "sent" ? "#f0fdf4" : r.status === "failed" ? "#fff1f2" : "#f7f7f8",
                      border: `1px solid ${r.status === "sent" ? "#bbf7d0" : r.status === "failed" ? "#E4DEFF" : "#e8e8ea"}`,
                    }}>
                      <span style={{ fontWeight: 500, color: "#0a0a0a" }}>{r.name}</span>
                      <span style={{ color: r.status === "sent" ? "#166534" : r.status === "failed" ? "#9f1239" : "#8a8a8e", fontSize: 11, maxWidth: 220, textAlign: "right" }}>
                        {r.status === "sent" ? "✓ Sent" : r.error ? `✗ ${r.error}` : `✗ ${r.status}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "16px 24px", borderTop: "1px solid #e8e8ea", flexShrink: 0 }}>
          <button onClick={onClose} style={{ padding: "8px 16px", background: "none", border: "1.5px solid #d8d8dc", borderRadius: 7, fontSize: 13, cursor: "pointer", color: "#3a3a3c" }}>{isDone ? "Close" : "Cancel"}</button>
          {!job && (
            <button onClick={handleRun} disabled={starting || selected.size === 0} className="btn-primary">
              {starting ? "Starting..." : `▶ Run for ${selected.size} lead${selected.size !== 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ─── Test Connection Button ───────────────────────────────────────────────────

function TestConnectionButton() {
  const [state, setState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [msg, setMsg] = useState("");

  const handleTest = async () => {
    setState("testing");
    try {
      const r = await testLinkedInSession();
      if (r.connected) {
        setState("ok");
        setMsg(r.name ? `Session valid — ${r.name}` : "Session valid");
      } else {
        setState("fail");
        setMsg(r.error || "Session invalid — reconnect in Settings");
      }
    } catch {
      setState("fail");
      setMsg("Could not reach LinkedIn — check your connection");
    }
    setTimeout(() => setState("idle"), 4000);
  };

  const colors = {
    idle: { color: "#5a5a5e", border: "#d8d8dc" },
    testing: { color: "#8a8a8e", border: "#e0e0e2" },
    ok: { color: "#166534", border: "#bbf7d0" },
    fail: { color: "#9f1239", border: "#E4DEFF" },
  }[state];

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {msg && <span style={{ fontSize: 11, color: colors.color, maxWidth: 220 }}>{msg}</span>}
      <button
        onClick={handleTest}
        disabled={state === "testing"}
        style={{
          fontSize: 11, fontWeight: 600, padding: "5px 12px", borderRadius: 6, whiteSpace: "nowrap",
          background: "none", border: `1.5px solid ${colors.border}`, cursor: state === "testing" ? "wait" : "pointer",
          color: colors.color,
        }}
      >
        {state === "testing" ? "Testing..." : "Test Connection"}
      </button>
    </div>
  );
}

// ─── Reply check button ───────────────────────────────────────────────────────

function CheckRepliesButton({ onResult }: { onResult: (r: ReplyCheckResult) => void }) {
  const [state, setState] = useState<"idle" | "checking" | "done">("idle");

  const handleCheck = async () => {
    setState("checking");
    try {
      const result = await checkReplies();
      onResult(result);
    } catch {
      onResult({ checked: 0, replied: 0, replied_names: [], error: "Could not check replies" });
    } finally {
      setState("done");
      setTimeout(() => setState("idle"), 5000);
    }
  };

  return (
    <button
      onClick={handleCheck}
      disabled={state === "checking"}
      style={{
        fontSize: 11, fontWeight: 600, padding: "5px 12px", borderRadius: 6, whiteSpace: "nowrap",
        background: "none", border: "1.5px solid #d8d8dc",
        cursor: state === "checking" ? "wait" : "pointer",
        color: state === "done" ? "#166534" : "#5a5a5e",
      }}
    >
      {state === "checking" ? "Checking..." : state === "done" ? "✓ Done" : "Check Replies"}
    </button>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function SequencesPage() {
  const [sequences, setSequences] = useState<Sequence[]>(() => peek<Sequence[]>("sequences") ?? []);
  const [leads, setLeads] = useState<Lead[]>(() => peek<Lead[]>("leads") ?? []);
  const [liSession, setLiSession] = useState<LinkedInSession | null>(() => peek<LinkedInSession>("li-session") ?? null);
  const [sendCap, setSendCap] = useState<SendCapStatus | null>(null);
  const [replyResult, setReplyResult] = useState<ReplyCheckResult | null>(null);
  const [loading, setLoading] = useState(!peek("sequences"));
  const [editing, setEditing] = useState<Partial<Sequence> | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [running, setRunning] = useState<Sequence | null>(null);

  const load = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [seqs, ls, sess, cap] = await Promise.all([
        getSequences(), getLeads(),
        getLinkedInStatus().catch(() => ({ connected: false }) as LinkedInSession),
        getSendCap().catch(() => null),
      ]);
      setSequences(seqs); put("sequences", seqs);
      setLeads(ls); put("leads", ls);
      setLiSession(sess); put("li-session", sess);
      setSendCap(cap);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (peek("sequences")) {
      load(true); // refresh silently in background
    } else {
      load();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = async (data: any) => {
    if (editing?.id) { const u = await updateSequence(editing.id, data); setSequences(p => p.map(s => s.id === u.id ? u : s)); }
    else { const c = await createSequence(data); setSequences(p => [...p, c]); }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this sequence?")) return;
    await deleteSequence(id);
    setSequences(p => p.filter(s => s.id !== id));
  };

  const liCount = leads.filter(l => l.linkedin_profile_id).length;

  return (
    <>
      <header className="page-header">
        <h1 className="page-title">Sequences</h1>
        <button onClick={() => { setEditing(null); setShowModal(true); }} className="btn-primary">+ New Sequence</button>
      </header>

      <div style={{ padding: "0 40px 40px" }}>
        {/* Status banner */}
        {liSession && !liSession.connected && (
          <div style={{ marginBottom: 20, padding: "12px 16px", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 9, display: "flex", gap: 12, alignItems: "center" }}>
            <span style={{ fontSize: 16 }}>⚠️</span>
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#92400e" }}>LinkedIn not connected</p>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: "#78350f" }}>
                <a href="/settings" style={{ color: "#6E56CF" }}>Connect in Settings</a> to enable automation. Message preview still works.
              </p>
            </div>
          </div>
        )}

        {liSession?.connected && (
          <div style={{ marginBottom: 14, padding: "12px 16px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 9, display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span style={{ fontSize: 16 }}>✅</span>
              <p style={{ margin: 0, fontSize: 13, color: "#166534" }}>
                <strong>{liSession.name}</strong> connected · {liCount} lead{liCount !== 1 ? "s" : ""} ready for automation
              </p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <CheckRepliesButton onResult={r => setReplyResult(r)} />
              <TestConnectionButton />
            </div>
          </div>
        )}

        {/* Reply check result */}
        {replyResult && (
          <div style={{
            marginBottom: 14, padding: "12px 16px", borderRadius: 9, display: "flex", gap: 12, alignItems: "center",
            background: replyResult.error ? "#fff1f2" : replyResult.replied > 0 ? "#eff6ff" : "#f7f7f8",
            border: `1px solid ${replyResult.error ? "#E4DEFF" : replyResult.replied > 0 ? "#bfdbfe" : "#e8e8ea"}`,
          }}>
            <span style={{ fontSize: 16 }}>{replyResult.error ? "⚠️" : replyResult.replied > 0 ? "💬" : "📭"}</span>
            <div style={{ flex: 1 }}>
              {replyResult.error ? (
                <p style={{ margin: 0, fontSize: 13, color: "#9f1239" }}>{replyResult.error}</p>
              ) : replyResult.replied > 0 ? (
                <>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#1b6fd8" }}>
                    {replyResult.replied} reply{replyResult.replied > 1 ? "ies" : ""} detected!
                  </p>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: "#3a3a3c" }}>
                    {replyResult.replied_names.join(", ")} — marked as Replied in Leads
                  </p>
                </>
              ) : (
                <p style={{ margin: 0, fontSize: 13, color: "#3a3a3c" }}>
                  Checked {replyResult.checked} contacted lead{replyResult.checked !== 1 ? "s" : ""} — no new replies
                </p>
              )}
            </div>
            <button onClick={() => setReplyResult(null)} style={{ background: "none", border: "none", fontSize: 16, cursor: "pointer", color: "#8a8a8e", lineHeight: 1, flexShrink: 0 }}>×</button>
          </div>
        )}

        {/* Daily send cap banner */}
        {sendCap && (
          <div style={{
            marginBottom: 20, padding: "10px 16px", borderRadius: 9,
            display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between",
            background: sendCap.is_capped ? "#fff1f2" : sendCap.pct_used >= 75 ? "#fffbeb" : "#f7f7f8",
            border: `1px solid ${sendCap.is_capped ? "#E4DEFF" : sendCap.pct_used >= 75 ? "#fde68a" : "#e8e8ea"}`,
          }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 14 }}>{sendCap.is_capped ? "🛑" : sendCap.pct_used >= 75 ? "⚠️" : "📊"}</span>
              <span style={{ fontSize: 12, color: sendCap.is_capped ? "#9f1239" : sendCap.pct_used >= 75 ? "#92400e" : "#3a3a3c" }}>
                <strong>LinkedIn daily cap:</strong>{" "}
                {sendCap.is_capped
                  ? "Limit reached — run again tomorrow"
                  : `${sendCap.sent_today} / ${sendCap.daily_cap} sent today · ${sendCap.remaining_today} remaining`
                }
              </span>
            </div>
            {/* Mini bar */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              <div style={{ width: 80, height: 4, background: "#e8e8ea", borderRadius: 2, overflow: "hidden" }}>
                <div style={{
                  height: "100%",
                  width: `${Math.min(100, sendCap.pct_used)}%`,
                  background: sendCap.is_capped ? "#6E56CF" : sendCap.pct_used >= 75 ? "#f59e0b" : "#22c55e",
                  borderRadius: 2,
                }} />
              </div>
              <span style={{ fontSize: 11, color: "#8a8a8e", whiteSpace: "nowrap" }}>{sendCap.pct_used}%</span>
            </div>
          </div>
        )}

        {loading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {[0,1,2].map(i => <div key={i} className="skeleton" style={{ height: 240, borderRadius: 10 }} />)}
          </div>
        ) : sequences.length === 0 ? (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <p style={{ color: "#8a8a8e", fontSize: 14 }}>No sequences yet.</p>
            <button onClick={() => { setEditing(null); setShowModal(true); }} style={{ marginTop: 10, color: "#6E56CF", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>Create your first sequence →</button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
            {sequences.map(seq => {
              const meta = TYPE_META[seq.type as SequenceType];
              return (
                <div key={seq.id} className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 20, background: meta?.bg, color: meta?.color, border: `1px solid ${meta?.border}` }}>
                        {meta?.label}
                      </span>
                      <p style={{ margin: "8px 0 0", fontWeight: 600, fontSize: 14, color: "#0a0a0a" }}>{seq.name}</p>
                    </div>
                    <span style={{ fontSize: 11, color: "#8a8a8e", flexShrink: 0, marginLeft: 8 }}>{meta?.delay}</span>
                  </div>

                  <p style={{ margin: 0, fontSize: 12, color: "#6b6b70", lineHeight: 1.5 }}>{meta?.desc}</p>

                  <div style={{ background: "#f7f7f8", border: "1px solid #e8e8ea", borderRadius: 7, padding: "10px 12px" }}>
                    <p style={{ margin: "0 0 4px", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", color: "#8a8a8e" }}>Template</p>
                    <p style={{ margin: 0, fontSize: 12, color: "#3a3a3c", lineHeight: 1.6, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" } as any}>
                      {seq.connection_note_template || seq.message_template || <em style={{ color: "#b0b0b4" }}>AI-generated per lead</em>}
                    </p>
                    {seq.connection_note_template && (
                      <p style={{ margin: "6px 0 0", fontSize: 10, color: "#b0b0b4" }}>{seq.connection_note_template.length}/300 chars</p>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: 8, borderTop: "1px solid #f0f0f2", paddingTop: 12 }}>
                    <button
                      onClick={() => setRunning(seq)}
                      className="btn-primary"
                      style={{ flex: 1, justifyContent: "center", gap: 6 }}
                    >
                      ▶ Run
                    </button>
                    <button
                      onClick={() => { setEditing(seq); setShowModal(true); }}
                      style={{ padding: "7px 12px", background: "none", border: "1.5px solid #d8d8dc", borderRadius: 7, fontSize: 12, cursor: "pointer", color: "#3a3a3c" }}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(seq.id)}
                      style={{ padding: "7px 10px", background: "none", border: "1.5px solid #d8d8dc", borderRadius: 7, fontSize: 12, cursor: "pointer", color: "#8a8a8e" }}
                      onMouseOver={e => { e.currentTarget.style.color = "#6E56CF"; e.currentTarget.style.borderColor = "#E4DEFF"; }}
                      onMouseOut={e => { e.currentTarget.style.color = "#8a8a8e"; e.currentTarget.style.borderColor = "#d8d8dc"; }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showModal && <Modal seq={editing} onClose={() => { setShowModal(false); setEditing(null); }} onSave={handleSave} />}
      {running && <RunModal seq={running} leads={leads} onClose={() => setRunning(null)} />}
    </>
  );
}
