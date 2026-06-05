"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { deleteSearch, getRecentSearches, type RecentSearch } from "@/lib/api";
import { hardNavigateClick } from "@/lib/navigation";
import { workspaceStatusLabel } from "@/lib/searchStatus";
import { notifyWorkspaceDeleted } from "@/lib/workspaceEvents";

function formatRelative(iso: string | null): string {
  if (!iso) return "Recently";
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return "Recently";
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "Just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? "" : "s"} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.floor(hr / 24);
  if (day < 14) return `${day} day${day === 1 ? "" : "s"} ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatCreated(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

type SortKey = "updated" | "name";

export default function WorkspacesPage() {
  const router = useRouter();
  const [recent, setRecent] = useState<RecentSearch[]>([]);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("updated");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const load = () =>
    getRecentSearches()
      .then(setRecent)
      .catch(() => {})
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuId(null);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const filtered = recent
    .filter((r) => r.prompt.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sort === "name") return a.prompt.localeCompare(b.prompt);
      const ta = new Date(a.created_at || 0).getTime();
      const tb = new Date(b.created_at || 0).getTime();
      return tb - ta;
    });

  const handleDelete = async (id: string) => {
    setMenuId(null);
    if (!confirm("Delete this workspace permanently? All leads and data will be removed.")) return;
    setDeletingId(id);
    try {
      await deleteSearch(id);
      setRecent((prev) => prev.filter((r) => r.id !== id));
      notifyWorkspaceDeleted(id);
      if (window.location.pathname === `/search/${id}`) {
        router.replace("/workspaces");
      }
    } catch {
      alert("Could not delete workspace");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="ws-page">
      <header className="ws-header">
        <div>
          <h1 className="ws-title">Workspaces</h1>
          <p className="ws-subtitle">Create, organize, and manage your workspaces.</p>
        </div>
      </header>

      <div className="ws-toolbar">
        <div className="ws-search">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3-3" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search workspaces"
          />
        </div>
        <div className="ws-toolbar-right">
          <label className="ws-sort">
            <span>Sort:</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="updated">Updated</option>
              <option value="name">Name</option>
            </select>
          </label>
          <a href="/" data-hard-nav className="ws-create-btn" onClick={hardNavigateClick("/")}>
            Create
          </a>
        </div>
      </div>

      {loading ? (
        <p className="ws-empty-hint">Loading…</p>
      ) : filtered.length === 0 ? (
        <div className="ws-empty">
          <p>No workspaces yet.</p>
          <a href="/" data-hard-nav className="ws-create-btn" onClick={hardNavigateClick("/")}>
            Create workspace
          </a>
        </div>
      ) : (
        <ul className="ws-list">
          {filtered.map((s) => (
            <li key={s.id} className="ws-row">
              <a
                href={`/search/${s.id}`}
                data-hard-nav
                className="ws-row-link"
                onClick={hardNavigateClick(`/search/${s.id}`)}
              >
                <span className="ws-avatar">{s.prompt.charAt(0).toUpperCase()}</span>
                <span className="ws-row-text">
                  <span className="ws-row-title">
                    {s.prompt}
                    {s.status === "running" && <span className="ws-badge">Live</span>}
                  </span>
                  <span className={`ws-row-meta${s.status === "failed" ? " ws-row-meta-error" : ""}`}>
                    {s.status === "completed" && s.lead_count > 0
                      ? `${s.lead_count} leads · `
                      : `${workspaceStatusLabel(s)} · `}
                    Updated {formatRelative(s.created_at)} · Created {formatCreated(s.created_at)}
                  </span>
                </span>
                <span className="ws-owner">
                  <span className="ws-owner-avatar">T</span>
                  Talon
                </span>
              </a>

              <div className="ws-row-menu" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                <div className="ws-menu-wrap" ref={menuId === s.id ? menuRef : undefined}>
                  <button
                    type="button"
                    className="ws-menu-btn"
                    aria-label="Workspace options"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setMenuId(menuId === s.id ? null : s.id);
                    }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <circle cx="12" cy="5" r="1.5" />
                      <circle cx="12" cy="12" r="1.5" />
                      <circle cx="12" cy="19" r="1.5" />
                    </svg>
                  </button>
                  {menuId === s.id && (
                    <div className="ws-dropdown">
                      <button
                        type="button"
                        className="ws-dropdown-item"
                        onClick={() => {
                          setMenuId(null);
                          window.location.href = `/search/${s.id}`;
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                          <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        Open workspace
                      </button>
                      <button
                        type="button"
                        className="ws-dropdown-item ws-dropdown-danger"
                        disabled={deletingId === s.id}
                        onClick={() => handleDelete(s.id)}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
                        </svg>
                        {deletingId === s.id ? "Deleting…" : "Delete"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
