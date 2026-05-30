"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { getLeads, getSequences, getStats, getLinkedInStatus, getRecentLeads } from "@/lib/api";
import { put, isStale } from "@/lib/cache";

// Pre-warm the cache for a given route on hover
function prefetchRoute(href: string) {
  switch (href) {
    case "/":
      if (isStale("stats")) getStats().then(d => put("stats", d)).catch(() => {});
      if (isStale("home-leads")) getRecentLeads(12).then(d => put("home-leads", d)).catch(() => {});
      break;
    case "/leads":
      if (isStale("leads")) getLeads().then(d => put("leads", d)).catch(() => {});
      break;
    case "/sequences":
      if (isStale("sequences")) getSequences().then(d => put("sequences", d)).catch(() => {});
      if (isStale("leads")) getLeads().then(d => put("leads", d)).catch(() => {});
      break;
    case "/outreach":
      if (isStale("leads")) getLeads().then(d => put("leads", d)).catch(() => {});
      break;
    case "/settings":
      if (isStale("li-session")) getLinkedInStatus().then(d => put("li-session", d)).catch(() => {});
      break;
  }
}

const NAV = [
  {
    section: "Main",
    items: [
      {
        href: "/",
        label: "Home",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h3a1 1 0 001-1v-3h2v3a1 1 0 001 1h3a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" /></svg>,
      },
    ],
  },
  {
    section: "Outreach",
    items: [
      {
        href: "/prospecting",
        label: "Prospect",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" /></svg>,
      },
      {
        href: "/leads",
        label: "Leads",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" /></svg>,
      },
      {
        href: "/outreach",
        label: "Outreach",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path d="M2 5a2 2 0 012-2h7a2 2 0 012 2v4a2 2 0 01-2 2H9l-3 3v-3H4a2 2 0 01-2-2V5z" /><path d="M15 7v2a4 4 0 01-4 4H9.828l-1.766 1.767c.28.149.599.233.938.233h2l3 3v-3h2a2 2 0 002-2V9a2 2 0 00-2-2h-1z" /></svg>,
      },
      {
        href: "/sequences",
        label: "Sequences",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" /></svg>,
      },
    ],
  },
  {
    section: "Account",
    items: [
      {
        href: "/settings",
        label: "Settings",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={15} height={15}><path fillRule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clipRule="evenodd" /></svg>,
      },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside style={{
      width: 220,
      minHeight: "100vh",
      background: "#fff",
      borderRight: "1px solid #e8e8ea",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
    }}>
      <style>{`
        @keyframes logo-bg-pulse {
          0%, 100% { background: linear-gradient(135deg, #D90429 0%, #a50020 100%); }
          50% { background: linear-gradient(135deg, #ef0535 0%, #D90429 100%); }
        }
        @keyframes claw-draw {
          0% { stroke-dashoffset: 60; opacity: 0; }
          100% { stroke-dashoffset: 0; opacity: 1; }
        }
        @keyframes logo-shimmer {
          0% { background-position: -300% center; }
          100% { background-position: 300% center; }
        }
        @keyframes glow-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(217, 4, 41, 0); }
          50% { box-shadow: 0 0 16px 2px rgba(217, 4, 41, 0.28); }
        }
        .logo-box {
          animation: logo-bg-pulse 3s ease-in-out infinite, glow-pulse 3s ease-in-out infinite;
        }
        .logo-box:hover {
          animation: none;
          background: linear-gradient(135deg, #ef0535 0%, #a50020 100%) !important;
          box-shadow: 0 0 20px 4px rgba(217, 4, 41, 0.4) !important;
          transform: scale(1.06);
        }
        .logo-claw path {
          stroke-dasharray: 60;
          stroke-dashoffset: 0;
          animation: claw-draw 0.9s ease-out both;
        }
        .logo-claw path:nth-child(2) { animation-delay: 0.08s; }
        .logo-claw path:nth-child(3) { animation-delay: 0.16s; }
        .logo-word {
          background: linear-gradient(90deg, #D90429 0%, #ff2b52 30%, #D90429 60%, #8b0019 80%, #D90429 100%);
          background-size: 300% auto;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          animation: logo-shimmer 4s linear infinite;
        }
        .nav-link { transition: background 0.08s, color 0.08s; }
        .nav-link:hover { background: #f5f5f7 !important; }
      `}</style>

      {/* Logo */}
      <Link href="/" style={{ textDecoration: "none" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 11,
          padding: "16px 16px 16px 14px",
          borderBottom: "1px solid #e8e8ea",
          cursor: "pointer",
        }}>
          {/* Animated icon box */}
          <div className="logo-box" style={{
            width: 34, height: 34, borderRadius: 9,
            background: "linear-gradient(135deg, #D90429 0%, #a50020 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
            transition: "transform 0.15s ease, box-shadow 0.15s ease",
          }}>
            {/* Talon claw icon — 3 curved strokes */}
            <svg className="logo-claw" viewBox="0 0 28 28" fill="none" width={17} height={17} aria-hidden>
              <path
                d="M7 5 C7 5 5.5 11 7.5 17 C9 21 7 24 7 24"
                stroke="white" strokeWidth="2.4" strokeLinecap="round"
              />
              <path
                d="M14 3 C14 3 12.5 10 14.5 17 C16 22 14 26 14 26"
                stroke="white" strokeWidth="2.4" strokeLinecap="round"
              />
              <path
                d="M21 5 C21 5 19.5 11 21.5 17 C23 21 21 24 21 24"
                stroke="white" strokeWidth="2.4" strokeLinecap="round"
              />
            </svg>
          </div>

          {/* Animated wordmark */}
          <span className="logo-word" style={{
            fontSize: 21,
            fontWeight: 900,
            letterSpacing: "-0.05em",
            lineHeight: 1,
          }}>
            talon
          </span>
        </div>
      </Link>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "10px 0" }}>
        {NAV.map((group) => (
          <div key={group.section} style={{ marginBottom: 2 }}>
            <p style={{
              padding: "10px 16px 5px",
              fontSize: 9.5, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.1em",
              color: "#c0c0c4", margin: 0,
            }}>
              {group.section}
            </p>
            {group.items.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  onMouseEnter={() => prefetchRoute(item.href)}
                  className="nav-link"
                  style={{
                    display: "flex", alignItems: "center", gap: 9,
                    padding: "7px 12px",
                    margin: "1px 8px",
                    borderRadius: 7,
                    fontSize: 13,
                    fontWeight: active ? 600 : 400,
                    color: active ? "#D90429" : "#3a3a3c",
                    background: active ? "#fff0f2" : "transparent",
                    textDecoration: "none",
                  }}
                >
                  <span style={{ color: active ? "#D90429" : "#a0a0a4", flexShrink: 0 }}>
                    {item.icon}
                  </span>
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}
