"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { getLeads, generateLinkedInMessages } from "@/lib/api";
import { peek, put } from "@/lib/cache";
import type { Lead, LinkedInMessage } from "@/types";

const TYPE_OPTS = [
  { value: "connection_request", label: "Connection Request", desc: "≤300 chars · Sent with connection invite" },
  { value: "follow_up_message", label: "Follow-up Message", desc: "After connecting · Personalized pitch" },
  { value: "final_message", label: "Final Message", desc: "Day 7 · Short, leaves door open" },
] as const;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      style={{ padding: "6px 12px", fontSize: 12, background: copied ? "#f0fdf4" : "#fff", border: `1.5px solid ${copied ? "#bbf7d0" : "#d8d8dc"}`, borderRadius: 6, cursor: "pointer", color: copied ? "#166534" : "#3a3a3c", fontWeight: 500, transition: "all 0.15s" }}
    >
      {copied ? "✓ Copied" : "Copy"}
    </button>
  );
}

function CharBar({ count, max = 300 }: { count: number; max?: number }) {
  const pct = Math.min((count / max) * 100, 100);
  const over = count > max;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 4, background: "#f0f0f2", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: over ? "#D90429" : count > max * 0.85 ? "#f59e0b" : "#16a34a", borderRadius: 4, transition: "width 0.2s" }} />
      </div>
      <span style={{ fontSize: 11, fontFamily: "monospace", color: over ? "#D90429" : "#6b6b70", fontWeight: 600 }}>{count}/{max}</span>
    </div>
  );
}

function OutreachContent() {
  const searchParams = useSearchParams();
  const preIds = searchParams.get("ids")?.split(",").filter(Boolean) ?? [];

  const [leads, setLeads] = useState<Lead[]>(() => peek<Lead[]>("leads") ?? []);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(preIds));
  const [seqType, setSeqType] = useState("connection_request");
  const [messages, setMessages] = useState<LinkedInMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [leadsLoading, setLeadsLoading] = useState(!peek("leads"));

  useEffect(() => {
    if (peek("leads")) {
      // Already cached — fetch silently in background to stay fresh
      getLeads().then(data => { setLeads(data); put("leads", data); }).catch(console.error);
      return;
    }
    getLeads()
      .then(data => { setLeads(data); put("leads", data); })
      .catch(console.error)
      .finally(() => setLeadsLoading(false));
  }, []);

  const toggle = (id: string) => {
    setSelectedIds(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
    setMessages([]);
  };

  const handleGenerate = async () => {
    if (selectedIds.size === 0) return;
    setLoading(true); setMessages([]);
    try { const r = await generateLinkedInMessages(Array.from(selectedIds), seqType); setMessages(r.messages); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Outreach</h1>
          <p className="page-subtitle">AI-personalized LinkedIn messages — select leads, pick type, generate</p>
        </div>
      </header>

      <div style={{ padding: "0 36px 36px", display: "grid", gridTemplateColumns: "220px 1fr 1fr", gap: 20, alignItems: "start" }}>

        {/* Col 1: Lead list */}
        <div className="card" style={{ overflow: "hidden" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid #e8e8ea" }}>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>Leads</p>
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "#6b6b70" }}>{selectedIds.size} selected</p>
          </div>
          <div style={{ maxHeight: 520, overflowY: "auto" }}>
            {leadsLoading && leads.length === 0 ? (
              <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
                {[0,1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 44, borderRadius: 7 }} />)}
              </div>
            ) : leads.length === 0 ? (
              <p style={{ padding: 16, margin: 0, fontSize: 13, color: "#8a8a8e", textAlign: "center" }}>No leads. Start prospecting.</p>
            ) : leads.map((lead, i) => (
              <label key={lead.id} style={{
                display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                borderBottom: i < leads.length - 1 ? "1px solid #f0f0f2" : "none",
                cursor: "pointer",
                background: selectedIds.has(lead.id) ? "#fff5f6" : "#fff",
                transition: "background 0.08s",
              }}>
                <input type="checkbox" checked={selectedIds.has(lead.id)} onChange={() => toggle(lead.id)} style={{ accentColor: "#D90429", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: "#0a0a0a", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{lead.name}</p>
                  <p style={{ margin: 0, fontSize: 11, color: "#6b6b70", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{lead.company}</p>
                </div>
                {lead.icp_score && (
                  <span style={{
                    fontSize: 11, fontWeight: 700, minWidth: 22, height: 22, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                    background: lead.icp_score >= 8 ? "#f0fdf4" : lead.icp_score >= 5 ? "#fffbeb" : "#fff1f2",
                    color: lead.icp_score >= 8 ? "#166534" : lead.icp_score >= 5 ? "#92400e" : "#9f1239",
                  }}>
                    {lead.icp_score}
                  </span>
                )}
              </label>
            ))}
          </div>
          {leads.length > 0 && (
            <div style={{ padding: "10px 14px", borderTop: "1px solid #e8e8ea" }}>
              <button onClick={() => { if (selectedIds.size === leads.length) setSelectedIds(new Set()); else setSelectedIds(new Set(leads.map(l => l.id))); setMessages([]); }}
                style={{ fontSize: 12, color: "#6b6b70", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                {selectedIds.size === leads.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          )}
        </div>

        {/* Col 2: Type + Generate */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card" style={{ padding: 20 }}>
            <p style={{ margin: "0 0 14px", fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>Message Type</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {TYPE_OPTS.map(opt => (
                <button key={opt.value} onClick={() => { setSeqType(opt.value); setMessages([]); }}
                  style={{
                    display: "flex", flexDirection: "column", alignItems: "flex-start",
                    padding: "12px 14px", borderRadius: 8, cursor: "pointer", textAlign: "left",
                    border: `1.5px solid ${seqType === opt.value ? "#D90429" : "#e8e8ea"}`,
                    background: seqType === opt.value ? "#fff5f6" : "#fff",
                    transition: "all 0.12s",
                  }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: seqType === opt.value ? "#D90429" : "#0a0a0a" }}>{opt.label}</span>
                  <span style={{ fontSize: 11, color: "#6b6b70", marginTop: 2 }}>{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleGenerate}
            disabled={loading || selectedIds.size === 0}
            className="btn-primary"
            style={{ width: "100%", justifyContent: "center", padding: "12px 0", fontSize: 14 }}
          >
            {loading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ display: "inline-block", width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                Generating with Claude...
              </span>
            ) : `Generate ${selectedIds.size > 0 ? `${selectedIds.size} ` : ""}Message${selectedIds.size !== 1 ? "s" : ""}`}
          </button>

          <div className="card" style={{ padding: 16 }}>
            <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 600, color: "#3a3a3c" }}>To automate sending</p>
            <p style={{ margin: 0, fontSize: 12, color: "#6b6b70", lineHeight: 1.6 }}>
              Go to <strong style={{ color: "#0a0a0a" }}>Sequences</strong> → pick a sequence → click <strong style={{ color: "#D90429" }}>Run</strong> to connect and message everyone automatically.
            </p>
          </div>
        </div>

        {/* Col 3: Preview */}
        <div className="card" style={{ overflow: "hidden" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid #e8e8ea" }}>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>
              Preview {messages.length > 0 && <span style={{ fontWeight: 400, color: "#6b6b70" }}>({messages.length})</span>}
            </p>
          </div>

          <div style={{ maxHeight: 580, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
            {loading && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 0" }}>
                <div style={{ width: 32, height: 32, border: "3px solid #f0f0f2", borderTopColor: "#D90429", borderRadius: "50%", animation: "spin 0.8s linear infinite", marginBottom: 12 }} />
                <p style={{ margin: 0, fontSize: 13, color: "#6b6b70" }}>Claude is personalizing messages...</p>
              </div>
            )}

            {!loading && messages.length === 0 && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 0" }}>
                <div style={{ width: 44, height: 44, borderRadius: "50%", background: "#f0f0f2", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="#8a8a8e" strokeWidth={1.5} width={22} height={22}><path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" /></svg>
                </div>
                <p style={{ margin: 0, fontSize: 13, color: "#8a8a8e" }}>Select leads and click Generate</p>
              </div>
            )}

            {messages.map(msg => (
              <div key={msg.lead_id} style={{ border: "1.5px solid #e8e8ea", borderRadius: 10, overflow: "hidden" }}>
                <div style={{ padding: "10px 14px", background: "#f7f7f8", borderBottom: "1px solid #e8e8ea", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <p style={{ margin: 0, fontSize: 12, fontWeight: 600, color: "#0a0a0a" }}>{msg.lead_name}</p>
                    <p style={{ margin: 0, fontSize: 11, color: "#6b6b70" }}>{msg.company}</p>
                  </div>
                  {msg.linkedin_url && (
                    <a href={msg.linkedin_url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 11, color: "#0077B5", textDecoration: "none", fontWeight: 500 }}>
                      LinkedIn ↗
                    </a>
                  )}
                </div>
                <div style={{ padding: 14 }}>
                  <p style={{ margin: "0 0 12px", fontSize: 13, color: "#1a1a1e", whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                    {msg.content}
                  </p>
                  {msg.type === "connection_request" && (
                    <div style={{ marginBottom: 12 }}>
                      <CharBar count={msg.char_count ?? msg.content.length} />
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8 }}>
                    <CopyButton text={msg.content} />
                    {msg.linkedin_url && (
                      <a href={msg.linkedin_url} target="_blank" rel="noopener noreferrer"
                        style={{ padding: "6px 12px", fontSize: 12, background: "#e8f4fd", border: "1.5px solid #bfdbfe", borderRadius: 6, color: "#1b6fd8", textDecoration: "none", fontWeight: 500 }}>
                        Open LinkedIn
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}

export default function OutreachPage() {
  return (
    <Suspense fallback={<div style={{ padding: 36, color: "#6b6b70" }}>Loading...</div>}>
      <OutreachContent />
    </Suspense>
  );
}
