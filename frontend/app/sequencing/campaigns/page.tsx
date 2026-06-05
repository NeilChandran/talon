"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getCampaigns } from "@/lib/api";
import type { Campaign } from "@/types";

export default function CampaignsListPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);

  useEffect(() => {
    getCampaigns().then(setCampaigns).catch(console.error);
  }, []);

  return (
    <div style={{ padding: "32px 40px" }}>
      <h1 className="page-title">Campaigns</h1>
      <p style={{ margin: "6px 0 24px", fontSize: 14, color: "var(--text-secondary)" }}>
        LinkedIn outreach sequences — connection request + follow-up DM
      </p>
      <div className="card" style={{ overflow: "hidden" }}>
        {campaigns.length === 0 ? (
          <p style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
            No campaigns yet. Launch from a workspace list via <strong>Send & export</strong>.
          </p>
        ) : (
          campaigns.map((c) => (
            <Link key={c.id} href={`/sequencing/campaigns/${c.id}`}
              style={{ display: "flex", justifyContent: "space-between", padding: "18px 24px", borderBottom: "1px solid var(--border-light)", textDecoration: "none", color: "inherit" }}>
              <span style={{ fontWeight: 600 }}>{c.name}</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{c.enrollment_count} sequences</span>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
