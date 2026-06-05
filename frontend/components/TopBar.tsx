"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getLinkedInStatus } from "@/lib/api";
import type { LinkedInSession } from "@/types";

export default function TopBar() {
  const [session, setSession] = useState<LinkedInSession | null>(null);

  useEffect(() => {
    getLinkedInStatus().then(setSession).catch(() => setSession({ connected: false }));
  }, []);

  const connected = session?.connected ?? false;
  const step = connected ? 2 : 1;

  return (
    <header className="topbar">
      <div className="topbar-prompt">
        <span>Get instant LinkedIn outreach</span>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
          <circle cx="8" cy="8" r="7" stroke="#9a9a9a" strokeWidth="1.2" />
          <path d="M8 7v4M8 5.5v.5" stroke="#9a9a9a" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      </div>

      <div className="topbar-stepper">
        <div className={`stepper-item ${step >= 1 ? (step === 1 ? "active" : "done") : ""}`}>
          <span className="stepper-dot">1</span>
          <span>LinkedIn</span>
        </div>
        <div className={`stepper-line ${step > 1 ? "done" : ""}`} />
        <div className={`stepper-item ${step >= 2 ? (step === 2 ? "active" : "done") : ""}`}>
          <span className="stepper-dot">2</span>
          <span>Leads</span>
        </div>
        <div className={`stepper-line ${step > 2 ? "done" : ""}`} />
        <div className={`stepper-item ${step >= 3 ? "active" : ""}`}>
          <span className="stepper-dot">3</span>
          <span>Launch</span>
        </div>
      </div>

      {connected ? (
        <Link href="/workspace" className="btn-secondary">
          Open workspace
        </Link>
      ) : (
        <Link href="/settings" className="btn-primary">
          Connect LinkedIn
        </Link>
      )}
    </header>
  );
}
