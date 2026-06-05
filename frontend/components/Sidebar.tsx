"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getRecentSearches, type RecentSearch } from "@/lib/api";
import TalonLogo from "@/components/TalonLogo";
import { hardNavigateClick } from "@/lib/navigation";
import { WORKSPACE_DELETED } from "@/lib/workspaceEvents";

const MAIN_NAV = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/workspaces", label: "All Workspaces", icon: "layers" },
];

const SEQ_NAV = [
  { href: "/sequencing/campaigns", label: "Campaigns" },
  { href: "/messages", label: "Messages" },
  { href: "/outreach", label: "Inbox" },
  { href: "/settings", label: "Senders" },
];

function NavIcon({ name }: { name: string }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 2 };
  if (name === "home") return <svg viewBox="0 0 24 24" {...p}><path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1h-5v-7H9v7H4a1 1 0 01-1-1V9.5z"/></svg>;
  if (name === "layers") return <svg viewBox="0 0 24 24" {...p}><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>;
  if (name === "clock") return <svg viewBox="0 0 24 24" {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
  return <svg viewBox="0 0 24 24" {...p}><circle cx="12" cy="12" r="2"/></svg>;
}

export default function Sidebar() {
  const pathname = usePathname();
  const [recent, setRecent] = useState<RecentSearch[]>([]);
  const [seqOpen, setSeqOpen] = useState(true);

  const refreshRecent = () => {
    getRecentSearches().then(setRecent).catch(() => {});
  };

  useEffect(() => {
    refreshRecent();
  }, [pathname]);

  useEffect(() => {
    const onDeleted = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id;
      if (id) setRecent((prev) => prev.filter((w) => w.id !== id));
      refreshRecent();
    };
    window.addEventListener(WORKSPACE_DELETED, onDeleted);
    return () => window.removeEventListener(WORKSPACE_DELETED, onDeleted);
  }, []);

  const active = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");

  const activeSearch = (id: string) => pathname === `/search/${id}`;

  return (
    <aside className="hedwig-sidebar">
      <a href="/" data-hard-nav className="hedwig-brand" aria-label="Talon home" onClick={hardNavigateClick("/")}>
        <TalonLogo variant="lockup" size={30} />
      </a>

      <nav className="hedwig-nav">
        {MAIN_NAV.map((item) => (
          <a
            key={item.href}
            href={item.href}
            data-hard-nav
            className={`hedwig-nav-link${active(item.href) ? " active" : ""}`}
            onClick={hardNavigateClick(item.href)}
          >
            <NavIcon name={item.icon} />
            <span>{item.label}</span>
          </a>
        ))}

        <button type="button" className="hedwig-nav-link hedwig-nav-btn" onClick={() => setSeqOpen(!seqOpen)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={18} height={18}>
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          <span>Sequencing</span>
          <span className="hedwig-chevron">{seqOpen ? "▾" : "▸"}</span>
        </button>
        {seqOpen && SEQ_NAV.map((item) => (
          <a
            key={item.href}
            href={item.href}
            data-hard-nav
            className={`hedwig-nav-link nested${active(item.href) ? " active" : ""}`}
            onClick={hardNavigateClick(item.href)}
          >
            {item.label}
          </a>
        ))}

        <div className="hedwig-section-label">
          <span>RECENT WORKSPACES</span>
          <a href="/" data-hard-nav className="hedwig-plus" title="New search" onClick={hardNavigateClick("/")}>+</a>
        </div>
        {recent.map((w) => (
          <a
            key={w.id}
            href={`/search/${w.id}`}
            data-hard-nav
            className={`hedwig-workspace-link${activeSearch(w.id) ? " active" : ""}`}
            onClick={hardNavigateClick(`/search/${w.id}`)}
          >
            <span className="hedwig-ws-icon">{w.prompt.charAt(0).toUpperCase()}</span>
            <span className="hedwig-ws-name">{w.prompt}</span>
          </a>
        ))}
      </nav>

      <div className="hedwig-sidebar-foot">
        <a href="/" data-hard-nav className="hedwig-foot-link" onClick={hardNavigateClick("/")}>Learn</a>
        <a href="/settings" data-hard-nav className={`hedwig-foot-link${active("/settings") ? " active" : ""}`} onClick={hardNavigateClick("/settings")}>Settings</a>
        <div className="hedwig-user">
          <span className="hedwig-user-avatar">T</span>
          <span className="hedwig-user-name" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
            Talon
          </span>
        </div>
      </div>
    </aside>
  );
}
