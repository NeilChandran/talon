"use client";

import Link from "next/link";

export default function ScheduledPage() {
  return (
    <div className="page-content">
      <h1 className="page-title">Scheduled</h1>
      <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>
        Scheduled outreach is coming soon.
      </p>
      <Link href="/sequencing/campaigns" style={{ fontSize: 13, fontWeight: 600 }}>
        View campaigns →
      </Link>
    </div>
  );
}
