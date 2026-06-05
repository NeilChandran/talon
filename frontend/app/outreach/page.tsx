"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getInbox, syncInbox, type InboxItem } from "@/lib/api";

type Tab = "all" | "replies";
type StatusFilter = "any" | InboxItem["status"];

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "any", label: "Any" },
  { value: "draft", label: "Draft" },
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "sent", label: "Sent" },
  { value: "replied", label: "Replied" },
  { value: "failed", label: "Failed" },
];

function statusClass(status: InboxItem["status"]) {
  const map: Record<InboxItem["status"], string> = {
    draft: "draft",
    scheduled: "scheduled",
    sent: "sent",
    in_progress: "progress",
    replied: "replied",
    failed: "failed",
    stopped: "stopped",
  };
  return map[status] || "draft";
}

function recipientInitial(item: InboxItem) {
  return (item.recipient[0] || item.name[0] || "?").toUpperCase();
}

export default function InboxPage() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [stats, setStats] = useState({ all: 0, replies: 0, sent_week: 0 });
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("any");
  const [filterOpen, setFilterOpen] = useState(false);
  const [error, setError] = useState("");
  const filterRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (sync = false) => {
    if (sync) setSyncing(true);
    else setLoading(true);
    setError("");
    try {
      const data = await getInbox(sync);
      setItems(data.items);
      setStats(data.stats);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not load inbox");
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setFilterOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      if (tab === "replies" && item.status !== "replied") return false;
      if (statusFilter !== "any" && item.status !== statusFilter) return false;
      if (!q) return true;
      return (
        item.recipient.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        item.campaign_name.toLowerCase().includes(q) ||
        item.search_prompt.toLowerCase().includes(q) ||
        item.connection_note.toLowerCase().includes(q)
      );
    });
  }, [items, tab, statusFilter, query]);

  const itemHref = (item: InboxItem) => {
    if (item.search_id) return `/search/${item.search_id}?campaign=1&lead=${item.lead_id}`;
    if (item.campaign_id) return `/sequencing/campaigns/${item.campaign_id}`;
    return "#";
  };

  return (
    <div className="hedwig-inbox">
      <header className="hedwig-inbox-head">
        <div className="hedwig-inbox-tabs">
          <button
            type="button"
            className={`hedwig-inbox-tab${tab === "replies" ? " active" : ""}`}
            onClick={() => setTab("replies")}
          >
            Replies <span className="hedwig-inbox-count">{stats.replies}</span>
          </button>
          <button
            type="button"
            className={`hedwig-inbox-tab${tab === "all" ? " active" : ""}`}
            onClick={() => setTab("all")}
          >
            All <span className="hedwig-inbox-count">{stats.all}</span>
          </button>
        </div>
        <div className="hedwig-inbox-head-right">
          <span className="hedwig-inbox-meta">
            {stats.sent_week} sent this week · {stats.replies} replied
          </span>
          <button
            type="button"
            className="hedwig-inbox-sync"
            disabled={syncing}
            onClick={() => syncInbox().then(() => load(false))}
          >
            {syncing ? "Syncing…" : "Sync Origami"}
          </button>
        </div>
      </header>

      {error && (
        <p className="hedwig-inbox-empty" style={{ padding: "12px 24px", color: "#b91c1c" }}>
          {error}
        </p>
      )}

      <div className="hedwig-inbox-toolbar">
        <label className="hedwig-inbox-select-all">
          <input type="checkbox" readOnly checked={false} />
          <span>Select all {filtered.length}</span>
        </label>
        <input
          className="hedwig-inbox-search"
          placeholder="Search recipient or campaign"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="hedwig-inbox-filter-wrap" ref={filterRef}>
          <button
            type="button"
            className="hedwig-inbox-filter-btn"
            onClick={() => setFilterOpen(!filterOpen)}
            aria-label="Filter"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M7 12h10M10 18h4" />
            </svg>
          </button>
          {filterOpen && (
            <div className="hedwig-inbox-filter-menu">
              <p className="hedwig-inbox-filter-label">Status</p>
              {STATUS_FILTERS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`hedwig-inbox-filter-opt${statusFilter === opt.value ? " active" : ""}`}
                  onClick={() => {
                    setStatusFilter(opt.value);
                    setFilterOpen(false);
                  }}
                >
                  {opt.label}
                  {opt.value !== "any" && (
                    <span>
                      {items.filter((i) => i.status === opt.value).length}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="hedwig-inbox-list">
        {loading && items.length === 0 ? (
          <p className="hedwig-inbox-empty">Loading inbox…</p>
        ) : filtered.length === 0 ? (
          <p className="hedwig-inbox-empty">
            {tab === "replies"
              ? "No replies yet"
              : statusFilter !== "any"
                ? `No ${statusFilter.replace("_", " ")} messages`
                : "No messages yet — launch a campaign to see drafts and scheduled sends here"}
          </p>
        ) : (
          filtered.map((item) => (
            <Link key={item.id} href={itemHref(item)} className="hedwig-inbox-row">
              <span className="hedwig-inbox-avatar">{recipientInitial(item)}</span>
              <div className="hedwig-inbox-row-main">
                <div className="hedwig-inbox-row-top">
                  <span className="hedwig-inbox-recipient">{item.recipient}</span>
                  <span className="hedwig-inbox-campaign">{item.campaign_name}</span>
                </div>
                {item.connection_note && (
                  <p className="hedwig-inbox-preview">{item.connection_note}</p>
                )}
              </div>
              <span className={`hedwig-inbox-status ${statusClass(item.status)}`}>
                {item.status_label}
              </span>
              <span className="hedwig-inbox-time">{item.activity_label || "—"}</span>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
