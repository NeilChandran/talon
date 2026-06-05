"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getRecentSearches, type RecentSearch } from "@/lib/api";
import TalonLogo from "@/components/TalonLogo";

const MAIN_NAV = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/workspaces", label: "All Workspaces", icon: "layers" },
  { href: "/scheduled", label: "Scheduled", icon: "clock", beta: true },
];

const SEQ_NAV = [
  { href: "/sequencing/campaigns", label: "Campaigns" },
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

  useEffect(() => {
    getRecentSearches().then(setRecent).catch(() => {});
  }, [pathname]);

  const active = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");

  const activeSearch = (id: string) => pathname === `/search/${id}`;

  return (
    <aside className="hedwig-sidebar">
      <Link href="/" className="hedwig-brand" aria-label="Talon home">
        <TalonLogo variant="lockup" size={30} />
      </Link>

      <nav className="hedwig-nav">
        {MAIN_NAV.map((item) => (
          <Link key={item.href} href={item.href} className={`hedwig-nav-link${active(item.href) ? " active" : ""}`}>
            <NavIcon name={item.icon} />
            <span>{item.label}</span>
            {item.beta && <span className="hedwig-badge-beta">BETA</span>}
          </Link>
        ))}

        <button type="button" className="hedwig-nav-link hedwig-nav-btn" onClick={() => setSeqOpen(!seqOpen)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={18} height={18}>
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          <span>Sequencing</span>
          <span className="hedwig-chevron">{seqOpen ? "▾" : "▸"}</span>
        </button>
        {seqOpen && SEQ_NAV.map((item) => (
          <Link key={item.href} href={item.href} className={`hedwig-nav-link nested${active(item.href) ? " active" : ""}`}>
            {item.label}
          </Link>
        ))}

        <div className="hedwig-section-label">
          <span>RECENT WORKSPACES</span>
          <Link href="/" className="hedwig-plus" title="New search">+</Link>
        </div>
        {recent.map((w) => (
          <Link
            key={w.id}
            href={`/search/${w.id}`}
            className={`hedwig-workspace-link${activeSearch(w.id) ? " active" : ""}`}
          >
            <span className="hedwig-ws-icon">{w.prompt.charAt(0).toUpperCase()}</span>
            <span className="hedwig-ws-name">{w.prompt}</span>
          </Link>
        ))}
      </nav>

      <div className="hedwig-sidebar-foot">
        <Link href="/" className="hedwig-foot-link">Learn</Link>
        <Link href="/settings" className={`hedwig-foot-link${active("/settings") ? " active" : ""}`}>Settings</Link>
        <div className="hedwig-user">
          <span className="hedwig-user-avatar">N</span>
          <span className="hedwig-user-name">You</span>
        </div>
      </div>
    </aside>
  );
}
