"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { getLeads, updateLeadStatus, deleteLead, deleteAllLeads } from "@/lib/api";
import { peek, put } from "@/lib/cache";
import type { Lead, LeadStatus } from "@/types";


const STATUS_OPTIONS: LeadStatus[] = ["new", "contacted", "replied", "closed"];

const STATUS_STYLE: Record<LeadStatus, { bg: string; color: string; border: string }> = {
  new:       { bg: "#eff6ff", color: "#1b6fd8", border: "#bfdbfe" },
  contacted: { bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  replied:   { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
  closed:    { bg: "#f9fafb", color: "#4b5563", border: "#e5e7eb" },
};

function StatusSelect({ leadId, current, onChange }: {
  leadId: string; current: LeadStatus; onChange: (id: string, s: LeadStatus) => void;
}) {
  const [updating, setUpdating] = useState(false);
  const s = STATUS_STYLE[current];
  return (
    <select
      value={current}
      onChange={async e => {
        const v = e.target.value as LeadStatus;
        setUpdating(true);
        try { await updateLeadStatus(leadId, v); onChange(leadId, v); }
        finally { setUpdating(false); }
      }}
      disabled={updating}
      style={{
        fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 20,
        background: s.bg, color: s.color, border: `1px solid ${s.border}`,
        cursor: "pointer", appearance: "none" as any, outline: "none",
        opacity: updating ? 0.6 : 1,
      }}
    >
      {STATUS_OPTIONS.map(v => <option key={v} value={v}>{v}</option>)}
    </select>
  );
}

type SortKey = "name" | "company" | "icp_score" | "status" | "created_at";

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>(() => peek<Lead[]>("leads") ?? []);
  const [loading, setLoading] = useState(!peek("leads"));
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "">("");
  const [minScore, setMinScore] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const isFiltered = !!(search || statusFilter || minScore);
  const isFirstRender = useRef(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const fetchLeads = useCallback(async () => {
    const hasCached = !isFiltered && !!peek("leads");
    if (!hasCached) setLoading(true);
    try {
      const data = await getLeads({
        status: statusFilter || undefined,
        min_score: minScore ? Number(minScore) : undefined,
        search: search || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setLeads(data);
      if (!isFiltered) put("leads", data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [search, statusFilter, minScore, sortBy, sortOrder, isFiltered]);

  // Single effect: immediate on first render, debounced on filter/sort changes
  useEffect(() => {
    const delay = isFirstRender.current ? 0 : 280;
    isFirstRender.current = false;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(fetchLeads, delay);
    return () => clearTimeout(debounceRef.current);
  }, [fetchLeads]);

  const handleSort = (col: SortKey) => {
    if (sortBy === col) setSortOrder(p => p === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortOrder("desc"); }
  };

  const liCount = leads.filter(l => l.linkedin_profile_id).length;

  return (
    <>
      <header className="page-header">
        <h1 className="page-title">Leads</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {selected.size > 0 && (
            <Link href={`/outreach?ids=${Array.from(selected).join(",")}`} className="btn-primary">
              Generate Messages ({selected.size})
            </Link>
          )}
          {leads.length > 0 && (
            <button
              onClick={async () => {
                if (!confirm(`Delete all ${leads.length} leads? This cannot be undone.`)) return;
                await deleteAllLeads();
                setLeads([]);
                setSelected(new Set());
                put("leads", []);
                put("home-leads", []);
              }}
              style={{ fontSize: 12, color: "#8a8a8e", background: "none", border: "1.5px solid #e0e0e2", borderRadius: 7, cursor: "pointer", padding: "7px 12px" }}
              onMouseOver={e => { e.currentTarget.style.color = "#D90429"; e.currentTarget.style.borderColor = "#fecdd3"; }}
              onMouseOut={e => { e.currentTarget.style.color = "#8a8a8e"; e.currentTarget.style.borderColor = "#e0e0e2"; }}
            >
              Clear all
            </button>
          )}
        </div>
      </header>

      <div style={{ padding: "0 40px 40px" }}>
        {/* Filters */}
        <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: 1, minWidth: 200 }}>
            <svg style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }} viewBox="0 0 20 20" fill="#8a8a8e" width={15} height={15}>
              <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
            </svg>
            <input
              type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search name, company..."
              className="input" style={{ paddingLeft: 34 }}
            />
          </div>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as LeadStatus | "")} className="input" style={{ width: 140 }}>
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={minScore} onChange={e => setMinScore(e.target.value)} className="input" style={{ width: 120 }}>
            <option value="">Min score</option>
            {[7, 8, 9, 10].map(n => <option key={n} value={n}>Score ≥ {n}</option>)}
          </select>
        </div>

        {/* Table */}
        <div className="card" style={{ overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="talon-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <input type="checkbox"
                      checked={selected.size === leads.length && leads.length > 0}
                      onChange={() => { if (selected.size === leads.length) setSelected(new Set()); else setSelected(new Set(leads.map(l => l.id))); }}
                      style={{ accentColor: "#D90429" }} />
                  </th>
                  {(["name","title","company","icp_score","status","LinkedIn",""] as const).map((col, i) => (
                    <th key={i}
                      onClick={() => ["name","company","icp_score","status"].includes(col) ? handleSort(col as SortKey) : undefined}
                      style={{ cursor: ["name","company","icp_score","status"].includes(col) ? "pointer" : "default" }}
                    >
                      {col === "" ? "Actions" : col === "icp_score" ? "Score" : col.charAt(0).toUpperCase() + col.slice(1)}
                      {["name","company","icp_score","status"].includes(col) && sortBy === col && (
                        <span style={{ color: "#D90429", marginLeft: 4 }}>{sortOrder === "desc" ? "↓" : "↑"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && leads.length === 0 ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>{Array.from({ length: 8 }).map((_, j) => <td key={j}><div className="skeleton" style={{ height: 14, maxWidth: 100, borderRadius: 4 }} /></td>)}</tr>
                )) : leads.length === 0 ? (
                  <tr><td colSpan={8} style={{ textAlign: "center", padding: "60px 0", color: "#8a8a8e" }}>
                    No leads found. <Link href="/prospecting" style={{ color: "#D90429" }}>Start prospecting →</Link>
                  </td></tr>
                ) : leads.map(lead => (
                  <tr key={lead.id} style={{ background: selected.has(lead.id) ? "#fff5f6" : undefined }}>
                    <td><input type="checkbox" checked={selected.has(lead.id)} onChange={() => { const n = new Set(selected); n.has(lead.id) ? n.delete(lead.id) : n.add(lead.id); setSelected(n); }} style={{ accentColor: "#D90429" }} /></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#fff0f2", border: "1.5px solid #fecdd3", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#D90429", flexShrink: 0 }}>
                          {(lead.name || "?").split(" ").slice(0,2).map(n => n[0]).join("").toUpperCase()}
                        </div>
                        <span style={{ fontWeight: 500, color: "#0a0a0a", whiteSpace: "nowrap" }}>{lead.name}</span>
                      </div>
                    </td>
                    <td style={{ color: "#5a5a5e", whiteSpace: "nowrap" }}>{lead.title || "—"}</td>
                    <td style={{ color: "#1a1a1e", whiteSpace: "nowrap" }}>
                      {lead.company || "—"}
                      {lead.company_size && <span style={{ color: "#8a8a8e", fontSize: 11, marginLeft: 4 }}>({lead.company_size})</span>}
                    </td>
                    <td>
                      {lead.icp_score ? (
                        <span style={{
                          fontSize: 12, fontWeight: 700, width: 28, height: 28, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center",
                          background: lead.icp_score >= 8 ? "#f0fdf4" : lead.icp_score >= 5 ? "#fffbeb" : "#fff1f2",
                          color: lead.icp_score >= 8 ? "#166534" : lead.icp_score >= 5 ? "#92400e" : "#9f1239",
                        }}>{lead.icp_score}</span>
                      ) : <span style={{ color: "#b0b0b4" }}>—</span>}
                    </td>
                    <td>
                      <StatusSelect leadId={lead.id} current={lead.status}
                        onChange={(id, s) => {
                          setLeads(p => p.map(l => l.id === id ? { ...l, status: s } : l));
                          put("leads", leads.map(l => l.id === id ? { ...l, status: s } : l));
                        }} />
                    </td>
                    <td>
                      {lead.linkedin_url ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer"
                            style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#0077B5", textDecoration: "none", fontWeight: 500 }}>
                            <svg viewBox="0 0 24 24" fill="currentColor" width={12} height={12}>
                              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                            </svg>
                            Profile
                          </a>
                          {lead.linkedin_profile_id && <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#16a34a", display: "inline-block" }} title="Ready for automation" />}
                        </div>
                      ) : <span style={{ color: "#b0b0b4", fontSize: 12 }}>—</span>}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 10 }}>
                        <Link href={`/outreach?ids=${lead.id}`} style={{ fontSize: 12, color: "#D90429", textDecoration: "none", fontWeight: 500 }}>Message</Link>
                        <button onClick={async () => {
                          if (!confirm("Delete?")) return;
                          await deleteLead(lead.id);
                          const next = leads.filter(l => l.id !== lead.id);
                          setLeads(next);
                          put("leads", next);
                        }}
                          style={{ fontSize: 12, color: "#8a8a8e", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                          onMouseOver={e => e.currentTarget.style.color = "#D90429"}
                          onMouseOut={e => e.currentTarget.style.color = "#8a8a8e"}
                        >Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
