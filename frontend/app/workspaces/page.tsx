"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createWorkspace, getWorkspaces, quickStartWorkspace } from "@/lib/api";
import type { Workspace } from "@/types";

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const d = Date.now() - new Date(iso).getTime();
  const days = Math.floor(d / 86400000);
  if (days < 1) return "Updated today";
  if (days === 1) return "Updated yesterday";
  return `Updated ${days} days ago`;
}

export default function WorkspacesPage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getWorkspaces().then(setWorkspaces).catch(console.error).finally(() => setLoading(false));
  }, []);

  const filtered = workspaces.filter((w) =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  const handleCreate = async () => {
    const name = prompt("Workspace name:");
    if (!name?.trim()) return;
    const ws = await createWorkspace(name.trim());
    router.push(`/workspaces/${ws.id}`);
  };

  return (
    <div style={{ flex: 1, padding: "32px 40px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <h1 className="page-title">Workspaces</h1>
          <p style={{ margin: "6px 0 0", fontSize: 14, color: "var(--text-secondary)" }}>
            Create, organize, and manage your workspaces
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={handleCreate}>Create</button>
      </div>

      <div className="toolbar" style={{ margin: "24px 0" }}>
        <div className="search-box" style={{ flex: 1, maxWidth: 360 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3-3"/></svg>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search workspaces" />
        </div>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Sort: Updated</span>
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: 48, textAlign: "center" }}>
          <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>No workspaces yet.</p>
          <button type="button" className="btn-primary" onClick={async () => {
            const { workspace } = await quickStartWorkspace("Find founders on LinkedIn");
            router.push(`/workspaces/${workspace.id}`);
          }}>Start from home prompt</button>
        </div>
      ) : (
        <div className="card" style={{ overflow: "hidden" }}>
          {filtered.map((ws) => (
            <Link key={ws.id} href={`/workspaces/${ws.id}`}
              style={{ display: "flex", alignItems: "center", gap: 16, padding: "18px 24px", borderBottom: "1px solid var(--border-light)", textDecoration: "none", color: "inherit" }}>
              <div style={{ width: 40, height: 40, borderRadius: "50%", background: "#e8e8ea", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, color: "#fff", fontSize: 16, flexShrink: 0 }}>
                {ws.icon_letter}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{ws.name}</p>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
                  {timeAgo(ws.updated_at)} · {ws.list_count} list{ws.list_count !== 1 ? "s" : ""}
                </p>
              </div>
              <span style={{ color: "var(--text-muted)" }}>⋯</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
