"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ClawIcon = () => (
  <svg viewBox="0 0 32 32" fill="currentColor" width={18} height={18} aria-hidden>
    <path d="M8 2 L10 2 L4 30 L2 30 Z" />
    <path d="M15 2 L17 2 L11 30 L9 30 Z" />
    <path d="M22 2 L24 2 L18 30 L16 30 Z" />
    <path d="M29 2 L31 2 L25 30 L23 30 Z" />
  </svg>
);

const NAV = [
  {
    section: "Main",
    items: [
      {
        href: "/",
        label: "Home",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h3a1 1 0 001-1v-3h2v3a1 1 0 001 1h3a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" /></svg>,
      },
    ],
  },
  {
    section: "LinkedIn Outreach",
    items: [
      {
        href: "/prospecting",
        label: "Prospect",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" /></svg>,
      },
      {
        href: "/leads",
        label: "Leads",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" /></svg>,
      },
      {
        href: "/outreach",
        label: "Outreach",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path d="M2 5a2 2 0 012-2h7a2 2 0 012 2v4a2 2 0 01-2 2H9l-3 3v-3H4a2 2 0 01-2-2V5z" /><path d="M15 7v2a4 4 0 01-4 4H9.828l-1.766 1.767c.28.149.599.233.938.233h2l3 3v-3h2a2 2 0 002-2V9a2 2 0 00-2-2h-1z" /></svg>,
      },
      {
        href: "/sequences",
        label: "Sequences",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" /></svg>,
      },
    ],
  },
  {
    section: "Account",
    items: [
      {
        href: "/settings",
        label: "Settings",
        icon: <svg viewBox="0 0 20 20" fill="currentColor" width={16} height={16}><path fillRule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clipRule="evenodd" /></svg>,
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
      {/* Logo */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "18px 16px",
        borderBottom: "1px solid #e8e8ea",
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: "#D90429",
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}>
          <ClawIcon />
        </div>
        <span style={{
          fontSize: 20, fontWeight: 800, color: "#D90429",
          letterSpacing: "-0.04em",
        }}>
          talon
        </span>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {NAV.map((group) => (
          <div key={group.section} style={{ marginBottom: 4 }}>
            <p style={{
              padding: "12px 16px 6px",
              fontSize: 10, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.09em",
              color: "#b0b0b4", margin: 0,
            }}>
              {group.section}
            </p>
            {group.items.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    display: "flex", alignItems: "center", gap: 9,
                    padding: "7px 12px",
                    margin: "1px 6px",
                    borderRadius: 7,
                    fontSize: 13,
                    fontWeight: active ? 600 : 400,
                    color: active ? "#D90429" : "#3a3a3c",
                    background: active ? "#fff0f2" : "transparent",
                    textDecoration: "none",
                    transition: "background 0.1s, color 0.1s",
                  }}
                  onMouseOver={e => { if (!active) { e.currentTarget.style.background = "#f5f5f7"; e.currentTarget.style.color = "#0a0a0a"; } }}
                  onMouseOut={e => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#3a3a3c"; } }}
                >
                  <span style={{ color: active ? "#D90429" : "#8a8a8e", flexShrink: 0 }}>
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
