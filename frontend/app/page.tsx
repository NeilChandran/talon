"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getStats, getRecentLeads } from "@/lib/api";
import { peek, put, isStale } from "@/lib/cache";
import type { Stats, Lead } from "@/types";

function LeadRow({ lead }: { lead: Lead }) {
  const initials = (lead.name || "?").split(" ").slice(0, 2).map(n => n[0]).join("").toUpperCase();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: "1px solid #f0f0f2" }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%", background: "#fff0f2",
        border: "1.5px solid #fecdd3", display: "flex", alignItems: "center",
        justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#D90429", flexShrink: 0,
      }}>
        {initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "#0a0a0a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {lead.name}
        </p>
        <p style={{ margin: 0, fontSize: 11, color: "#6b6b70", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {[lead.title, lead.company].filter(Boolean).join(" · ")}
        </p>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        {lead.icp_score != null && (
          <span style={{
            fontSize: 11, fontWeight: 700, width: 26, height: 26, borderRadius: "50%",
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            background: lead.icp_score >= 8 ? "#f0fdf4" : lead.icp_score >= 5 ? "#fffbeb" : "#fff1f2",
            color: lead.icp_score >= 8 ? "#166534" : lead.icp_score >= 5 ? "#92400e" : "#9f1239",
          }}>{lead.icp_score}</span>
        )}
        {lead.linkedin_url ? (
          <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer"
            style={{ fontSize: 11, color: "#0077B5", textDecoration: "none", fontWeight: 500 }}>
            <svg viewBox="0 0 24 24" fill="currentColor" width={14} height={14}>
              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
            </svg>
          </a>
        ) : null}
        <Link href={`/outreach?ids=${lead.id}`}
          style={{ fontSize: 11, color: "#D90429", textDecoration: "none", fontWeight: 600, whiteSpace: "nowrap" }}>
          Message →
        </Link>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(() => peek<Stats>("stats") ?? null);
  const [leads, setLeads] = useState<Lead[]>(() => peek<Lead[]>("home-leads") ?? []);
  const [loading, setLoading] = useState(!peek("stats") || !peek("home-leads"));

  useEffect(() => {
    const stale = isStale("stats") || isStale("home-leads");
    if (!stale) return; // data is fresh, no need to fetch

    Promise.all([getStats(), getRecentLeads(12)])
      .then(([s, l]) => {
        setStats(s); put("stats", s);
        setLeads(l); put("home-leads", l);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Your prospected leads waiting for outreach</p>
        </div>
        <Link href="/prospecting" className="btn-primary">
          <svg viewBox="0 0 20 20" fill="currentColor" width={14} height={14}>
            <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
          </svg>
          Find Leads
        </Link>
      </div>

      <div style={{ padding: "0 36px 36px" }}>
        {/* KPI cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
          {loading && !stats ? Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 90, borderRadius: 10 }} />
          )) : [
            { label: "Total Leads", value: stats?.total_leads ?? 0, sub: "in pipeline" },
            { label: "New This Week", value: stats?.leads_this_week ?? 0, sub: "discovered", accent: true },
            { label: "Messages Sent", value: stats?.emails_sent ?? 0, sub: "all sequences" },
            { label: "Reply Rate", value: `${stats?.reply_rate ?? 0}%`, sub: "of delivered", accent: true },
          ].map(card => (
            <div key={card.label} className="stat-card">
              <p className="stat-label">{card.label}</p>
              <p className={`stat-value${card.accent ? " accent" : ""}`}>{card.value}</p>
              <p style={{ margin: "4px 0 0", fontSize: 11, color: "#8a8a8e" }}>{card.sub}</p>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 20 }}>
          {/* Prospects to reach out to */}
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid #e8e8ea" }}>
              <div>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>People to reach out to</p>
                <p style={{ margin: "2px 0 0", fontSize: 11, color: "#6b6b70" }}>
                  {leads.length > 0 ? `${leads.length} new prospects` : "No new prospects yet"}
                </p>
              </div>
              <Link href="/leads" style={{ fontSize: 12, color: "#D90429", textDecoration: "none", fontWeight: 600 }}>
                All leads →
              </Link>
            </div>
            <div style={{ padding: "0 20px" }}>
              {loading && leads.length === 0 ? Array.from({ length: 6 }).map((_, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: "1px solid #f0f0f2" }}>
                  <div className="skeleton" style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div className="skeleton" style={{ height: 13, width: 140, borderRadius: 4, marginBottom: 5 }} />
                    <div className="skeleton" style={{ height: 11, width: 200, borderRadius: 4 }} />
                  </div>
                </div>
              )) : leads.length === 0 ? (
                <div style={{ padding: "52px 0", textAlign: "center" }}>
                  <p style={{ margin: "0 0 6px", fontSize: 14, fontWeight: 500, color: "#0a0a0a" }}>No new prospects yet</p>
                  <p style={{ margin: "0 0 16px", fontSize: 13, color: "#6b6b70" }}>
                    Find people on LinkedIn and they'll appear here
                  </p>
                  <Link href="/prospecting" style={{ fontSize: 13, color: "#D90429", textDecoration: "none", fontWeight: 600 }}>
                    Start prospecting →
                  </Link>
                </div>
              ) : leads.map(lead => <LeadRow key={lead.id} lead={lead} />)}
            </div>
          </div>

          {/* Right column */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="card" style={{ padding: 20 }}>
              <p style={{ margin: "0 0 14px", fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>Quick Actions</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <Link href="/prospecting" className="btn-primary" style={{ justifyContent: "center" }}>
                  Find Leads on LinkedIn
                </Link>
                <Link href="/outreach" style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  padding: "8px 16px", background: "#fff", border: "1.5px solid #d8d8dc",
                  borderRadius: 7, fontSize: 13, fontWeight: 500, color: "#0a0a0a",
                  textDecoration: "none",
                }}>Generate Messages</Link>
                <Link href="/sequences" style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  padding: "8px 16px", background: "#fff", border: "1.5px solid #d8d8dc",
                  borderRadius: 7, fontSize: 13, fontWeight: 500, color: "#0a0a0a",
                  textDecoration: "none",
                }}>Run Sequences</Link>
                <Link href="/settings" style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  padding: "8px 16px", background: "#fff", border: "1.5px solid #d8d8dc",
                  borderRadius: 7, fontSize: 13, fontWeight: 500, color: "#0a0a0a",
                  textDecoration: "none",
                }}>Connect LinkedIn</Link>
              </div>
            </div>

            <div className="card" style={{ padding: 20 }}>
              <p style={{ margin: "0 0 14px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "#8a8a8e" }}>ICP Score Guide</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {[
                  { range: "10", label: "Founder/CEO at 1–20 person YC/VC startup", bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
                  { range: "7–9", label: "Ops / CoS at startup, fast-moving team", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
                  { range: "4–6", label: "Knowledge worker, uses Notion / Linear", bg: "#f7f7f8", color: "#3a3a3c", border: "#e8e8ea" },
                  { range: "1–3", label: "Enterprise or non-decision-maker role", bg: "#fff1f2", color: "#9f1239", border: "#fecdd3" },
                ].map(row => (
                  <div key={row.range} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 5, background: row.bg, color: row.color, border: `1px solid ${row.border}`, flexShrink: 0, marginTop: 1 }}>
                      {row.range}
                    </span>
                    <p style={{ margin: 0, fontSize: 12, color: "#5a5a5e", lineHeight: 1.5 }}>{row.label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
