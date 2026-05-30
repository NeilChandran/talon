"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getStats, getRecentLeads } from "@/lib/api";
import { peek, put, isStale } from "@/lib/cache";
import type { Stats, Lead } from "@/types";

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub: string; accent?: boolean }) {
  return (
    <div className="stat-card">
      <p className="stat-label">{label}</p>
      <p className={`stat-value${accent ? " accent" : ""}`}>{value}</p>
      <p style={{ margin: "4px 0 0", fontSize: 11, color: "#8a8a8e" }}>{sub}</p>
    </div>
  );
}

function LeadRow({ lead }: { lead: Lead }) {
  const initials = (lead.name || "?").split(" ").slice(0, 2).map((n: string) => n[0]).join("").toUpperCase();
  const scoreColor = lead.icp_score >= 8 ? "#166534" : lead.icp_score >= 5 ? "#92400e" : "#9f1239";
  const scoreBg = lead.icp_score >= 8 ? "#f0fdf4" : lead.icp_score >= 5 ? "#fffbeb" : "#fff1f2";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 20px", borderBottom: "1px solid #f0f0f2" }}>
      <div style={{
        width: 34, height: 34, borderRadius: "50%", background: "#fff0f2",
        border: "1.5px solid #fecdd3", display: "flex", alignItems: "center",
        justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#D90429", flexShrink: 0,
      }}>
        {initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {lead.name}
        </p>
        <p style={{ margin: 0, fontSize: 11, color: "#6b6b70", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {[lead.title, lead.company].filter(Boolean).join(" · ")}
        </p>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        {lead.icp_score != null && (
          <span style={{ fontSize: 11, fontWeight: 700, width: 26, height: 26, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", background: scoreBg, color: scoreColor }}>
            {lead.icp_score}
          </span>
        )}
        {lead.linkedin_url && (
          <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer"
            style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#0077B5", textDecoration: "none", fontWeight: 500 }}>
            <svg viewBox="0 0 24 24" fill="currentColor" width={13} height={13}>
              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
            </svg>
          </a>
        )}
        <Link href={`/outreach?ids=${lead.id}`}
          style={{ fontSize: 11, color: "#D90429", textDecoration: "none", fontWeight: 600, background: "#fff0f2", padding: "4px 10px", borderRadius: 5 }}>
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
    if (!stale) { setLoading(false); return; }
    Promise.all([getStats(), getRecentLeads(12)])
      .then(([s, l]) => {
        setStats(s); put("stats", s);
        setLeads(l); put("home-leads", l);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const hasLeads = leads.length > 0;

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Home</h1>
        <Link href="/prospecting" className="btn-primary">
          <svg viewBox="0 0 20 20" fill="currentColor" width={14} height={14}>
            <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
          </svg>
          Find Leads
        </Link>
      </div>

      <div style={{ padding: "0 40px 40px" }}>

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
          {loading && !stats ? Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 90, borderRadius: 10 }} />
          )) : (
            <>
              <StatCard label="Total Leads" value={stats?.total_leads ?? 0} sub="in pipeline" />
              <StatCard label="New This Week" value={stats?.leads_this_week ?? 0} sub="discovered" accent />
              <StatCard label="Messages Sent" value={stats?.emails_sent ?? 0} sub="all sequences" />
              <StatCard label="Reply Rate" value={`${stats?.reply_rate ?? 0}%`} sub="of delivered" accent />
            </>
          )}
        </div>

        {hasLeads ? (
          /* ── Leads list (real prospected leads only) ── */
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid #e8e8ea" }}>
              <div>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>People to reach out to</p>
                <p style={{ margin: "2px 0 0", fontSize: 11, color: "#6b6b70" }}>{leads.length} new prospect{leads.length !== 1 ? "s" : ""} waiting</p>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <Link href="/sequences" style={{ fontSize: 12, color: "#0a0a0a", textDecoration: "none", fontWeight: 500, padding: "6px 12px", background: "#f5f5f7", border: "1.5px solid #e0e0e2", borderRadius: 7 }}>
                  Run Sequence
                </Link>
                <Link href="/leads" style={{ fontSize: 12, color: "#D90429", textDecoration: "none", fontWeight: 600 }}>
                  All leads →
                </Link>
              </div>
            </div>
            {leads.map(lead => <LeadRow key={lead.id} lead={lead} />)}
          </div>
        ) : (
          /* ── Empty state: guide to getting started ── */
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ padding: "56px 40px", textAlign: "center" }}>
              <div style={{ width: 52, height: 52, borderRadius: 14, background: "#fff0f2", border: "2px solid #fecdd3", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
                <svg viewBox="0 0 24 24" fill="#D90429" width={24} height={24}>
                  <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                </svg>
              </div>
              <h2 style={{ margin: "0 0 8px", fontSize: 17, fontWeight: 700, color: "#0a0a0a" }}>No leads yet</h2>
              <p style={{ margin: "0 0 32px", fontSize: 13, color: "#6b6b70", maxWidth: 380, marginLeft: "auto", marginRight: "auto" }}>
                Find real LinkedIn profiles and they'll appear here ready for outreach.
              </p>

              {/* 3-step flow */}
              <div style={{ display: "flex", gap: 0, justifyContent: "center", marginBottom: 36 }}>
                {[
                  { step: "1", label: "Connect LinkedIn", sub: "Sign in once in Settings — stays connected", href: "/settings", cta: "Settings" },
                  { step: "2", label: "Prospect", sub: "Search for founders, operators, or any ICP", href: "/prospecting", cta: "Find Leads" },
                  { step: "3", label: "Send Outreach", sub: "Run a sequence — connection + follow-up", href: "/sequences", cta: "View Sequences" },
                ].map((s, i) => (
                  <div key={s.step} style={{ display: "flex", alignItems: "stretch" }}>
                    <div style={{ width: 220, padding: "20px 20px", textAlign: "left" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                        <span style={{ width: 22, height: 22, borderRadius: "50%", background: "#D90429", color: "#fff", fontSize: 11, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          {s.step}
                        </span>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>{s.label}</span>
                      </div>
                      <p style={{ margin: "0 0 14px", fontSize: 12, color: "#6b6b70", lineHeight: 1.6 }}>{s.sub}</p>
                      <Link href={s.href} style={{ fontSize: 12, color: "#D90429", fontWeight: 600, textDecoration: "none" }}>{s.cta} →</Link>
                    </div>
                    {i < 2 && (
                      <div style={{ display: "flex", alignItems: "center", padding: "0 4px" }}>
                        <svg viewBox="0 0 20 20" fill="#d0d0d4" width={16} height={16}>
                          <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
                        </svg>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <Link href="/prospecting" className="btn-primary" style={{ display: "inline-flex" }}>
                <svg viewBox="0 0 20 20" fill="currentColor" width={14} height={14}>
                  <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
                </svg>
                Start Prospecting
              </Link>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
