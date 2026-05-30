"use client";

import { useEffect, useState } from "react";
import {
  getAnalyticsFunnel,
  getAnalyticsSequences,
  getAnalyticsDailyActivity,
  getAnalyticsSendCap,
} from "@/lib/api";
import type { FunnelData, SequenceStat, DayActivity, SendCapStatus } from "@/types";

// ─── Send cap ring ────────────────────────────────────────────────────────────

function SendCapRing({ cap }: { cap: SendCapStatus }) {
  const radius = 40;
  const circ = 2 * Math.PI * radius;
  const strokeDash = (cap.pct_used / 100) * circ;
  const color = cap.pct_used >= 100 ? "#D90429" : cap.pct_used >= 75 ? "#f59e0b" : "#22c55e";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <div style={{ position: "relative", width: 100, height: 100 }}>
        <svg width={100} height={100} viewBox="0 0 100 100" style={{ transform: "rotate(-90deg)" }}>
          <circle cx={50} cy={50} r={radius} fill="none" stroke="#f0f0f2" strokeWidth={10} />
          <circle
            cx={50} cy={50} r={radius}
            fill="none"
            stroke={color}
            strokeWidth={10}
            strokeDasharray={`${strokeDash} ${circ}`}
            strokeLinecap="round"
            style={{ transition: "stroke-dasharray 0.5s ease" }}
          />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <span style={{ fontSize: 20, fontWeight: 800, color: "#0a0a0a", letterSpacing: "-0.04em", lineHeight: 1 }}>
            {cap.sent_today}
          </span>
          <span style={{ fontSize: 9, color: "#8a8a8e", fontWeight: 600, letterSpacing: "0.04em" }}>/ {cap.daily_cap}</span>
        </div>
      </div>
      <div>
        <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0a0a0a" }}>
          {cap.is_capped ? "Daily limit reached" : `${cap.remaining_today} sends left today`}
        </p>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#6b6b70" }}>
          LinkedIn cap: {cap.daily_cap} connections/day
        </p>
        <div style={{ marginTop: 8, height: 6, width: 180, background: "#f0f0f2", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${Math.min(100, cap.pct_used)}%`, background: color, borderRadius: 3, transition: "width 0.5s" }} />
        </div>
        <p style={{ margin: "4px 0 0", fontSize: 11, color: "#8a8a8e" }}>{cap.pct_used}% used · Resets at midnight UTC</p>
      </div>
    </div>
  );
}

// ─── Funnel ───────────────────────────────────────────────────────────────────

function Funnel({ data }: { data: FunnelData }) {
  const stages = data.funnel;
  const maxCount = stages[0]?.count || 1;
  const colors = ["#D90429", "#f59e0b", "#0077B5", "#22c55e"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {stages.map((s, i) => (
        <div key={s.stage}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%", background: colors[i], display: "inline-block", flexShrink: 0
              }} />
              <span style={{ fontSize: 13, fontWeight: 600, color: "#0a0a0a" }}>{s.stage}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 12, color: "#6b6b70" }}>{s.pct}%</span>
              <span style={{ fontSize: 18, fontWeight: 800, color: "#0a0a0a", letterSpacing: "-0.04em", minWidth: 40, textAlign: "right" }}>
                {s.count.toLocaleString()}
              </span>
            </div>
          </div>
          <div style={{ height: 8, background: "#f0f0f2", borderRadius: 4, overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: `${maxCount > 0 ? (s.count / maxCount) * 100 : 0}%`,
              background: colors[i],
              borderRadius: 4,
              transition: "width 0.6s ease",
            }} />
          </div>
          {i < stages.length - 1 && (
            <div style={{ fontSize: 10, color: "#b0b0b4", marginTop: 3, paddingLeft: 16 }}>
              {stages[i + 1].count > 0 && s.count > 0
                ? `→ ${Math.round(stages[i + 1].count / s.count * 100)}% conversion`
                : "→ 0% conversion"
              }
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Activity bar chart ───────────────────────────────────────────────────────

function ActivityChart({ data }: { data: DayActivity[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  const last14 = data.slice(-14);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 60 }}>
        {last14.map((d) => {
          const h = max > 0 ? (d.count / max) * 60 : 0;
          const today = d.date === new Date().toISOString().split("T")[0];
          return (
            <div key={d.date} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }} title={`${d.date}: ${d.count} sent`}>
              <div style={{
                width: "100%",
                height: Math.max(h, d.count > 0 ? 3 : 0),
                background: today ? "#D90429" : "#e8e8ea",
                borderRadius: "2px 2px 0 0",
                transition: "height 0.5s ease",
                minHeight: d.count > 0 ? 3 : 0,
              }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span style={{ fontSize: 10, color: "#b0b0b4" }}>14 days ago</span>
        <span style={{ fontSize: 10, color: "#b0b0b4" }}>Today</span>
      </div>
    </div>
  );
}

// ─── Sequence table ───────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, { color: string; bg: string; border: string; label: string }> = {
  connection_request: { color: "#1b6fd8", bg: "#eff6ff", border: "#bfdbfe", label: "Connection" },
  follow_up_message:  { color: "#92400e", bg: "#fffbeb", border: "#fde68a", label: "Follow-up" },
  final_message:      { color: "#166534", bg: "#f0fdf4", border: "#bbf7d0", label: "Final" },
};

function SequenceTable({ stats }: { stats: SequenceStat[] }) {
  if (!stats.length) {
    return (
      <div style={{ padding: "32px", textAlign: "center", color: "#8a8a8e", fontSize: 13 }}>
        No sequences run yet. Create a sequence and run it to see stats here.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="talon-table">
        <thead>
          <tr>
            <th>Sequence</th>
            <th>Type</th>
            <th>Sent</th>
            <th>Failed</th>
            <th>Total Runs</th>
            <th>Success Rate</th>
          </tr>
        </thead>
        <tbody>
          {stats.map(s => {
            const meta = TYPE_COLORS[s.type] || { color: "#6b6b70", bg: "#f7f7f8", border: "#e8e8ea", label: s.type };
            return (
              <tr key={s.sequence_id}>
                <td style={{ fontWeight: 600, color: "#0a0a0a" }}>{s.name}</td>
                <td>
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 20, background: meta.bg, color: meta.color, border: `1px solid ${meta.border}` }}>
                    {meta.label}
                  </span>
                </td>
                <td style={{ fontWeight: 700, color: "#166534" }}>{s.sent}</td>
                <td style={{ color: s.failed > 0 ? "#9f1239" : "#8a8a8e" }}>{s.failed}</td>
                <td style={{ color: "#3a3a3c" }}>{s.total}</td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ flex: 1, height: 5, background: "#f0f0f2", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${s.success_rate}%`, background: s.success_rate >= 80 ? "#22c55e" : s.success_rate >= 50 ? "#f59e0b" : "#D90429", borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#0a0a0a", minWidth: 35 }}>{s.success_rate}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [seqStats, setSeqStats] = useState<SequenceStat[]>([]);
  const [activity, setActivity] = useState<DayActivity[]>([]);
  const [sendCap, setSendCap] = useState<SendCapStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getAnalyticsFunnel(),
      getAnalyticsSequences(),
      getAnalyticsDailyActivity(),
      getAnalyticsSendCap(),
    ])
      .then(([f, s, a, c]) => {
        setFunnel(f);
        setSeqStats(s);
        setActivity(a);
        setSendCap(c);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const totalSent = funnel?.total_outreach_sent ?? 0;
  const replyRate = funnel?.reply_rate ?? 0;
  const contactRate = funnel?.contact_rate ?? 0;
  const newThisWeek = funnel?.new_this_week ?? 0;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Analytics</h1>
          <p className="page-subtitle">Hedwig outbound performance</p>
        </div>
        <button
          onClick={() => {
            setLoading(true);
            Promise.all([
              getAnalyticsFunnel(),
              getAnalyticsSequences(),
              getAnalyticsDailyActivity(),
              getAnalyticsSendCap(),
            ]).then(([f, s, a, c]) => {
              setFunnel(f); setSeqStats(s); setActivity(a); setSendCap(c);
            }).finally(() => setLoading(false));
          }}
          className="btn-secondary"
          disabled={loading}
        >
          {loading ? "Refreshing..." : "↻ Refresh"}
        </button>
      </header>

      <div style={{ padding: "0 40px 40px" }}>
        {loading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            {[0,1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 90, borderRadius: 10 }} />)}
          </div>
        ) : (
          <>
            {/* ── Top stats row ── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
              {[
                { label: "Total Sent", value: totalSent, sub: "connection + messages", accent: false },
                { label: "Contact Rate", value: `${contactRate}%`, sub: "prospected → contacted", accent: true },
                { label: "Reply Rate", value: `${replyRate}%`, sub: "contacted → replied", accent: false },
                { label: "New This Week", value: newThisWeek, sub: "leads prospected", accent: true },
              ].map(s => (
                <div key={s.label} className="stat-card">
                  <p className="stat-label">{s.label}</p>
                  <p className={`stat-value${s.accent ? " accent" : ""}`}>{s.value}</p>
                  <p style={{ margin: "4px 0 0", fontSize: 11, color: "#8a8a8e" }}>{s.sub}</p>
                </div>
              ))}
            </div>

            {/* ── Main grid: Funnel + Send Cap ── */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
              {/* Funnel */}
              <div className="card" style={{ padding: 24 }}>
                <p style={{ margin: "0 0 20px", fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>Lead Funnel</p>
                {funnel ? <Funnel data={funnel} /> : (
                  <p style={{ color: "#8a8a8e", fontSize: 13 }}>No data yet</p>
                )}
              </div>

              {/* Send cap + activity */}
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                {/* Daily send cap */}
                <div className="card" style={{ padding: 24 }}>
                  <p style={{ margin: "0 0 16px", fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>LinkedIn Daily Cap</p>
                  {sendCap ? <SendCapRing cap={sendCap} /> : (
                    <p style={{ color: "#8a8a8e", fontSize: 13 }}>Loading...</p>
                  )}
                </div>

                {/* 14-day activity */}
                <div className="card" style={{ padding: 24 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>Outreach Activity</p>
                    <span style={{ fontSize: 11, color: "#8a8a8e" }}>Last 14 days</span>
                  </div>
                  {activity.length > 0 ? (
                    <ActivityChart data={activity} />
                  ) : (
                    <p style={{ color: "#8a8a8e", fontSize: 13, margin: 0 }}>No outreach yet</p>
                  )}
                </div>
              </div>
            </div>

            {/* ── Sequence performance table ── */}
            <div className="card" style={{ overflow: "hidden" }}>
              <div style={{ padding: "16px 20px", borderBottom: "1px solid #e8e8ea" }}>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#0a0a0a" }}>Sequence Performance</p>
                <p style={{ margin: "2px 0 0", fontSize: 11, color: "#6b6b70" }}>All-time stats per sequence</p>
              </div>
              <SequenceTable stats={seqStats} />
            </div>
          </>
        )}
      </div>
    </>
  );
}
