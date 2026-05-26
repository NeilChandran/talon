"use client";

import { useEffect, useRef, useState } from "react";
import { startProspecting, getProspectingStatus } from "@/lib/api";
import type { Lead, ProspectingJob } from "@/types";

const EXAMPLES = [
  "YC W24 founders building B2B SaaS",
  "Seed-stage startup founders in SF",
  "Chiefs of staff at VC-backed startups",
  "Co-founders of developer tools companies",
];

export default function ProspectingPage() {
  const [query, setQuery] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ProspectingJob | null>(null);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const stopPolling = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

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
  }, [jobId]);

  const handleSearch = async () => {
    if (!query.trim() || loading) return;
    setLoading(true); setJob(null); setJobId(null); stopPolling();
    try { const { job_id } = await startProspecting(query.trim()); setJobId(job_id); }
    catch { setLoading(false); }
  };

  const leads = job?.leads ?? [];

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Prospect</h1>
          <p className="page-subtitle">Describe who you're looking for — Talon finds real LinkedIn profiles and scores them</p>
        </div>
      </header>

      <div style={{ padding: "0 36px 36px", maxWidth: 1100 }}>
        {/* Search box */}
        <div className="card" style={{ padding: 24, marginBottom: 20 }}>
          <label className="label">Who are you looking for?</label>
          <textarea
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSearch(); }}
            placeholder="e.g. YC W24 founders building B2B SaaS with 5-20 employees..."
            rows={3}
            className="input"
            style={{ resize: "none" }}
          />

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, flexWrap: "wrap", gap: 10 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {EXAMPLES.map(ex => (
                <button
                  key={ex}
                  onClick={() => setQuery(ex)}
                  style={{
                    fontSize: 11, padding: "4px 12px", borderRadius: 20,
                    background: "#fff", border: "1.5px solid #e0e0e2",
                    color: "#5a5a5e", cursor: "pointer", fontWeight: 400,
                    transition: "all 0.1s",
                  }}
                  onMouseOver={e => { e.currentTarget.style.borderColor = "#D90429"; e.currentTarget.style.color = "#D90429"; }}
                  onMouseOut={e => { e.currentTarget.style.borderColor = "#e0e0e2"; e.currentTarget.style.color = "#5a5a5e"; }}
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

        {/* Progress */}
        {loading && job && (
          <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", background: "#fff", border: "1.5px solid #fecdd3", borderRadius: 9, marginBottom: 20 }}>
            <div style={{ width: 18, height: 18, border: "2.5px solid #fecdd3", borderTopColor: "#D90429", borderRadius: "50%", animation: "spin 0.8s linear infinite", flexShrink: 0 }} />
            <div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "#0a0a0a" }}>{job.step}</p>
              {leads.length > 0 && <p style={{ margin: "2px 0 0", fontSize: 12, color: "#6b6b70" }}>{leads.length} leads found so far...</p>}
            </div>
          </div>
        )}
        {loading && !job && (
          <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", background: "#fff", border: "1px solid #e8e8ea", borderRadius: 9, marginBottom: 20 }}>
            <div style={{ width: 18, height: 18, border: "2.5px solid #e0e0e2", borderTopColor: "#D90429", borderRadius: "50%", animation: "spin 0.8s linear infinite", flexShrink: 0 }} />
            <p style={{ margin: 0, fontSize: 13, color: "#6b6b70" }}>Initializing search...</p>
          </div>
        )}
        {job?.status === "failed" && (
          <div style={{ padding: "14px 18px", background: "#fff1f2", border: "1px solid #fecdd3", borderRadius: 9, marginBottom: 20 }}>
            <p style={{ margin: 0, fontSize: 13, color: "#9f1239", fontWeight: 500 }}>
              {job.error?.includes("not connected")
                ? "LinkedIn is not connected."
                : `Search failed: ${job.error}`}
            </p>
            {job.error?.includes("not connected") && (
              <a href="/settings" style={{ fontSize: 13, color: "#9f1239", fontWeight: 600, display: "inline-block", marginTop: 6 }}>
                Connect LinkedIn in Settings →
              </a>
            )}
          </div>
        )}

        {/* Results */}
        {leads.length > 0 && (
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #e8e8ea" }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>
                {job?.status === "completed" ? "Results" : "Live results"}{" "}
                <span style={{ fontWeight: 400, color: "#6b6b70" }}>({leads.length})</span>
              </p>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {job?.source === "linkedin" && (
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, background: "#eff6ff", color: "#1b6fd8", border: "1px solid #bfdbfe" }}>
                    Real LinkedIn profiles
                  </span>
                )}
                {job?.status === "completed" && (
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
                    ✓ Saved to Leads
                  </span>
                )}
              </div>
            </div>
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
                      <td style={{ fontWeight: 500, color: "#0a0a0a", whiteSpace: "nowrap" }}>{lead.name || "—"}</td>
                      <td style={{ color: "#5a5a5e", whiteSpace: "nowrap" }}>{lead.title || "—"}</td>
                      <td style={{ color: "#1a1a1e", whiteSpace: "nowrap" }}>{lead.company || "—"}</td>
                      <td style={{ color: "#6b6b70", whiteSpace: "nowrap" }}>{(lead as any).company_size || "—"}</td>
                      <td>
                        {lead.icp_score ? (
                          <span style={{
                            fontSize: 12, fontWeight: 700, width: 28, height: 28, borderRadius: "50%",
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                            background: (lead.icp_score ?? 0) >= 8 ? "#f0fdf4" : (lead.icp_score ?? 0) >= 5 ? "#fffbeb" : "#fff1f2",
                            color: (lead.icp_score ?? 0) >= 8 ? "#166534" : (lead.icp_score ?? 0) >= 5 ? "#92400e" : "#9f1239",
                          }}>{lead.icp_score}</span>
                        ) : <span style={{ color: "#b0b0b4" }}>—</span>}
                      </td>
                      <td style={{ color: "#6b6b70", fontSize: 12, maxWidth: 240 }}>
                        <span style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } as any}>
                          {lead.score_reason || "—"}
                        </span>
                      </td>
                      <td>
                        {lead.linkedin_url ? (
                          <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer"
                            style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#0077B5", textDecoration: "none", fontWeight: 500, whiteSpace: "nowrap" }}>
                            <svg viewBox="0 0 24 24" fill="currentColor" width={12} height={12}>
                              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                            </svg>
                            View
                          </a>
                        ) : <span style={{ color: "#b0b0b4", fontSize: 12 }}>—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !job && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "80px 0" }}>
            <div style={{ width: 52, height: 52, borderRadius: "50%", background: "#eff6ff", border: "1.5px solid #bfdbfe", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
              <svg viewBox="0 0 24 24" fill="#0077B5" width={26} height={26}>
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
              </svg>
            </div>
            <p style={{ margin: "0 0 6px", fontSize: 14, fontWeight: 500, color: "#0a0a0a" }}>Find real LinkedIn profiles</p>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: "#6b6b70", textAlign: "center", maxWidth: 340 }}>
              Describe who you're looking for. Talon searches real LinkedIn profiles and scores them for your ICP.
            </p>
            <a href="/settings" style={{
              fontSize: 12, fontWeight: 500, color: "#1b6fd8",
              background: "#eff6ff", border: "1.5px solid #bfdbfe",
              padding: "6px 16px", borderRadius: 20, textDecoration: "none",
            }}>
              Make sure LinkedIn is connected →
            </a>
          </div>
        )}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
