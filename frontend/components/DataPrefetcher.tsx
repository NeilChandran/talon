"use client";

/**
 * Invisible component mounted once in the root layout.
 * Pre-warms all page caches in the background so every navigation is instant.
 */
import { useEffect } from "react";
import { getLeads, getSequences, getStats, getLinkedInStatus, getRecentLeads } from "@/lib/api";
import { put, isStale } from "@/lib/cache";

export default function DataPrefetcher() {
  useEffect(() => {
    // Fire all fetches in parallel — no await, runs silently in background
    const warm = () => {
      if (isStale("leads"))
        getLeads().then(d => put("leads", d)).catch(() => {});
      if (isStale("sequences"))
        getSequences().then(d => put("sequences", d)).catch(() => {});
      if (isStale("stats"))
        getStats().then(d => put("stats", d)).catch(() => {});
      if (isStale("home-leads"))
        getRecentLeads(12).then(d => put("home-leads", d)).catch(() => {});
      if (isStale("li-session"))
        getLinkedInStatus().then(d => put("li-session", d)).catch(() => {});
    };

    warm();
    // Re-warm every 90 seconds so cache never goes cold
    const interval = setInterval(warm, 90_000);
    return () => clearInterval(interval);
  }, []);

  return null;
}
