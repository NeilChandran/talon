"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { startProspecting, startSignalProspecting, getProspectingStatus } from "@/lib/api";
import type { Lead, ProspectingJob, SignalMode } from "@/types";

// ─── Signal mode metadata ─────────────────────────────────────────────────────

const SIGNAL_MODES: {
  mode: SignalMode | "search";
  label: string;
  icon: string;
  desc: string;
  hint: string;
  color: string;
  bg: string;
}[] = [
  {
    mode: "search",
    label: "LinkedIn Search",
    icon: "🔍",
    desc: "Find anyone on LinkedIn by describing your ICP",
    hint: "e.g. YC W24 founders building B2B SaaS",
    color: "#0a0a0a",
    bg: "#f7f7f8",
  },
  {
    mode: "funded",
    label: "Funded Startups",
    icon: "💰",
    desc: "Founders & VPs at recently-funded startups — they have budget and are setting up their stack",
    hint: "Auto-targets companies that just raised Series A/B",
    color: "#0077B5",
    bg: "#eff6ff",
  },
  {
    mode: "jobs",
    label: "Hiring Sales",
    icon: "📈",
    desc: "Sales leaders at companies actively hiring SDRs/AEs — they need better email tooling now",
    hint: "Auto-targets VP Sales at high-growth teams",
    color: "#92400e",
    bg: "#fffbeb",
  },
  {
    mode: "competitor",
    label: "Competitor Users",
    icon: "⚡",
    desc: "People who already use Superhuman, SaneBox, or Shortwave — they're aware of the category",
    hint: "Auto-targets high-intent email tool buyers",
    color: "#166534",
    bg: "#f0fdf4",
  },
];

const EXAMPLES = [
  "YC W24 founders building B2B SaaS",
  "Seed-stage startup founders in SF",
  "Chiefs of staff at VC-backed startups",
  "VP Sales at Series A startups",
  "Co-founders of developer tools companies",
];

// ─── Lead results table ───────────────────────────────────────────────────────

function ResultsTable({ leads, source }: { leads: Partial<Lead>[]; source?: string }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="talon-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Title</th>
            <th>Company</th>
            <th>Size</th>
            <th>Score</th>
            <th>Why</th>
            <th>LinkedIn</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 600, color: "#0a0a0a", whiteSpace: "nowrap", letterSpacing: "-0.01em" }}>
                {lead.name || "—"}
              </td>
              <td style={{ color: "#5a5a5e", whiteSpace: "nowrap" }}>{lead.title || "—"}</td>
              <td style={{ color: "#1a1a1e", whiteSpace: "nowrap" }}>{lead.company || "—"}</td>
              <td style={{ color: "#9a9aa0", whiteSpace: "nowrap" }}>{(lead as any).company_size || "—"}</td>
              <td>
                {lead.icp_score != null ? (
                  <span style={{
                    fontSize: 11.5, fontWeight: 700, width: 26, height: 26, borderRadius: "50%",
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    background: (lead.icp_score ?? 0) >= 8 ? "#f0fdf4" : (lead.icp_score ?? 0) >= 5 ? "#fffbeb" : "#fff1f2",
                    color: (lead.icp_score ?? 0) >= 8 ? "#166534" : (lead.icp_score ?? 0) >= 5 ? "#92400e" : "#9f1239",
                  }}>
                    {lead.icp_score}
                  </span>
                ) : <span style={{ color: "#c0c0c4" }}>—</span>}
              </td>
              <td style={{ color: "#8a8a8e", fontSize: 12, maxWidth: 240 }}>
                <span style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } as any}>
                  {lead.score_reason || "—"}
                </span>
              </td>
              <td>
                {lead.linkedin_url ? (
                  <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer"
                    style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#0077B5", textDecoration: "none", fontWeight: 500, whiteSpace: "nowrap" }}>
                    <svg viewBox="0 0 24 24" fill="currentColor" width={11} height={11}>
                      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                    </svg>
                    View
                  </a>
                ) : <span style={{ color: "#c0c0c4", fontSize: 12 }}>—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ProspectingPage() {
  const [activeMode, setActiveMode] = useState<SignalMode | "search">("search");
  const [query, setQuery] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ProspectingJob | null>(null);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  useEffect(() => {
    if (!jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await getProspectingStatus(jobId);
        setJob(s);
        if (s.status === "completed" || s.status === "failed") { stopPolling(); setLoading(false); }
      } catch { stopPolling(); setLoading(false); }
    }, 2500);
    return stopPolling;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const handleSearch = async () => {
    if (loading) return;
    setLoading(true); setJob(null); setJobId(null); stopPolling();

    try {
      if (activeMode === "search") {
        if (!query.trim()) { setLoading(false); return; }
        const { job_id } = await startProspecting(query.trim());
        setJobId(job_id);
      } else {
        const { job_id } = await startSignalProspecting(activeMode);
        setJobId(job_id);
      }
    } catch { setLoading(false); }
  };

  const leads = job?.leads ?? [];
  const currentMeta = SIGNAL_MODES.find(m => m.mode === activeMode)!;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Prospect</h1>
          <p className="page-subtitle">Find people who should be using Hedwig</p>
        </div>
        {job?.status === "completed" && (
          <Link href="/sequences" className="btn-primary">
            Run Sequence →
          </Link>
        )}
      </header>

      <div style={{ padding: "0 40px 40px", maxWidth: 1140 }}>

        {/* ── Mode tabs ── */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          {SIGNAL_MODES.map(m => (
            <button
              key={m.mode}
              onClick={() => { setActiveMode(m.mode); setJob(null); setJobId(null); stopPolling(); setLoading(false); }}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "7px 14px", borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                border: activeMode === m.mode ? `2px solid ${m.color === "#0a0a0a" ? "#0a0a0a" : m.color}` : "1.5px solid #e8e8ea",
                background: activeMode === m.mode ? (m.color === "#0a0a0a" ? "#0a0a0a" : m.bg) : "#fff",
                color: activeMode === m.mode ? (m.color === "#0a0a0a" ? "#fff" : m.color) : "#5a5a5e",
                cursor: "pointer",
                transition: "all 0.12s",
              }}
            >
              <span>{m.icon}</span>
              {m.label}
            </button>
          ))}
        </div>

        {/* ── Signal description ── */}
        {activeMode !== "search" && (
          <div style={{
            marginBottom: 16, padding: "12px 16px", borderRadius: 9,
            background: currentMeta.bg, border: `1px solid ${currentMeta.color}22`,
            display: "flex", alignItems: "center", gap: 12,
          }}>
            <span style={{ fontSize: 20 }}>{currentMeta.icon}</span>
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>{currentMeta.label}</p>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: "#5a5a5e" }}>{currentMeta.desc}</p>
              <p style={{ margin: "2px 0 0", fontSize: 11, color: "#8a8a8e" }}>{currentMeta.hint}</p>
            </div>
          </div>
        )}

        {/* ── Search box (only for LinkedIn Search mode) ── */}
        {activeMode === "search" && (
          <div className="card" style={{ padding: "22px 24px", marginBottom: 20 }}>
            <textarea
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSearch(); }}
              placeholder="e.g. VP Sales at Series A startups who live in their inbox..."
              rows={3}
              className="input"
              style={{ resize: "none", fontSize: 14 }}
            />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, flexWrap: "wrap", gap: 10 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
                {EXAMPLES.map(ex => (
                  <button
                    key={ex}
                    onClick={() => setQuery(ex)}
                    style={{
                      fontSize: 11.5, padding: "4px 11px", borderRadius: 20,
                      background: "#fff", border: "1.5px solid #e8e8ea",
                      color: "#6b6b70", cursor: "pointer", fontWeight: 400,
                      letterSpacing: "-0.01em", transition: "all 0.1s",
                    }}
                    onMouseOver={e => { e.currentTarget.style.borderColor = "#0a0a0a"; e.currentTarget.style.color = "#0a0a0a"; }}
                    onMouseOut={e => { e.currentTarget.style.borderColor = "#e8e8ea"; e.currentTarget.style.color = "#6b6b70"; }}
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <button
                onClick={handleSearch}
                disabled={!query.trim() || loading}
                className="btn-primary"
                style={{ flexShrink: 0 }}
              >
                {loading ? "Searching..." : "Find Leads"}
              </button>
            </div>
          </div>
        )}

        {/* ── Signal mode launch button ── */}
        {activeMode !== "search" && !loading && !job && (
          <div className="card" style={{ padding: "24px", marginBottom: 20, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>Ready to find {currentMeta.label} leads</p>
              <p style={{ margin: "3px 0 0", fontSize: 12, color: "#6b6b70" }}>
                Talon will search LinkedIn for ~25 high-fit leads using this signal. Takes ~2 minutes.
              </p>
            </div>
            <button onClick={handleSearch} className="btn-primary" style={{ flexShrink: 0, gap: 7 }}>
              <span>{currentMeta.icon}</span>
              Find {currentMeta.label}
            </button>
          </div>
        )}

        {/* ── Progress ── */}
        {loading && (
          <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "13px 18px", background: "#fff", border: "1px solid #e8e8ea", borderRadius: 9, marginBottom: 20 }}>
            <div style={{ width: 16, height: 16, border: "2.5px solid #e8e8ea", borderTopColor: "#0a0a0a", borderRadius: "50%", animation: "spin 0.8s linear infinite", flexShrink: 0 }} />
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "#0a0a0a", letterSpacing: "-0.01em" }}>
                {job?.step || "Initializing..."}
              </p>
              {leads.length > 0 && <p style={{ margin: "2px 0 0", fontSize: 12, color: "#8a8a8e" }}>{leads.length} found so far</p>}
            </div>
          </div>
        )}

        {/* ── Error state ── */}
        {job?.status === "failed" && (
          <div style={{ padding: "14px 18px", background: "#fff", border: "1px solid #e8e8ea", borderRadius: 9, marginBottom: 20, display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ flex: 1 }}>
              <p style={{ margin: "0 0 3px", fontSize: 13, fontWeight: 700, color: "#0a0a0a", letterSpacing: "-0.02em" }}>
                {job.error?.includes("not connected") ? "LinkedIn not connected" : "Search failed"}
              </p>
              <p style={{ margin: 0, fontSize: 12, color: "#8a8a8e", lineHeight: 1.5 }}>
                {job.error?.includes("not connected") ? "Connect your LinkedIn account in Settings first." : job.error}
              </p>
            </div>
            {(job.error?.includes("not connected") || job.error?.includes("expired")) && (
              <a href="/settings" style={{
                flexShrink: 0, fontSize: 12, fontWeight: 600, color: "#0a0a0a",
                background: "#f5f5f7", border: "1.5px solid #e0e0e2",
                padding: "7px 14px", borderRadius: 7, textDecoration: "none", whiteSpace: "nowrap",
              }}>
                Settings
              </a>
            )}
          </div>
        )}

        {/* ── Results table ── */}
        {leads.length > 0 && (
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 18px", borderBottom: "1px solid #f0f0f2" }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#0a0a0a", letterSpacing: "-0.02em" }}>
                Results <span style={{ fontWeight: 400, color: "#9a9aa0" }}>({leads.length})</span>
              </p>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {job?.status === "completed" && (
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 20, background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
                    ✓ Saved to Leads
                  </span>
                )}
                {activeMode !== "search" && (
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 20, background: currentMeta.bg, color: currentMeta.color === "#0a0a0a" ? "#3a3a3c" : currentMeta.color, border: `1px solid ${currentMeta.color}33` }}>
                    {currentMeta.icon} {currentMeta.label}
                  </span>
                )}
                {activeMode === "search" && (
                  <span style={{ fontSize: 11, fontWeight: 500, padding: "3px 9px", borderRadius: 20, background: "#f7f7f8", color: "#6b6b70", border: "1px solid #e8e8ea" }}>
                    LinkedIn
                  </span>
                )}
              </div>
            </div>
            <ResultsTable leads={leads} source={activeMode} />
          </div>
        )}

        {/* ── Empty state (search mode only) ── */}
        {!loading && !job && activeMode === "search" && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "72px 0" }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: "#f7f7f8", border: "1px solid #e8e8ea", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
              <svg viewBox="0 0 20 20" fill="#9a9aa0" width={20} height={20}>
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
              </svg>
            </div>
            <p style={{ margin: "0 0 5px", fontSize: 14, fontWeight: 700, color: "#0a0a0a", letterSpacing: "-0.025em" }}>Search for people</p>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: "#9a9aa0", textAlign: "center", maxWidth: 340, lineHeight: 1.6 }}>
              Describe your target or pick a signal above — Talon finds real LinkedIn profiles and scores them for Hedwig's ICP.
            </p>
            <a href="/settings" style={{ fontSize: 12, fontWeight: 500, color: "#6b6b70", background: "#f7f7f8", border: "1px solid #e8e8ea", padding: "6px 14px", borderRadius: 20, textDecoration: "none" }}>
              LinkedIn must be connected
            </a>
          </div>
        )}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
