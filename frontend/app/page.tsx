"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createSearch, getRecentSearches, type RecentSearch } from "@/lib/api";
import TalonLogo from "@/components/TalonLogo";

const PLACEHOLDER = "Find VPs of Sales at SaaS companies that just raised Series B.";

const EXAMPLES = [
  "Find YC W26 founders on LinkedIn who are building B2B SaaS",
  "Find VPs of Sales at SaaS companies that just raised Series B",
  "Find boutique VC firms with 2–10 partners in the US",
];

export default function HomePage() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<RecentSearch[]>([]);

  useEffect(() => {
    getRecentSearches().then(setRecent).catch(() => {});
  }, []);

  const submit = async (text?: string) => {
    const q = (text ?? prompt).trim();
    if (!q || loading) return;
    setLoading(true);
    setError("");
    try {
      const s = await createSearch(q);
      router.push(`/search/${s.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start search");
      setLoading(false);
    }
  };

  return (
    <div className="hedwig-home">
      <div className="hedwig-home-top">
        <Link href="/">Get advice</Link>
        <Link href="/settings">Settings</Link>
      </div>

      <div className="hedwig-home-center">
        <div className="hedwig-home-logo">
          <TalonLogo variant="lockup" size={40} />
        </div>
        <h1>How can I find your perfect customers?</h1>
        <p className="hedwig-home-sub">
          Origami finds your leads — you send and track everything from Talon (LinkedIn + email), without leaving the app.
        </p>

        <div className="hedwig-home-prompt">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={PLACEHOLDER}
            rows={4}
          />
          <div className="hedwig-home-prompt-foot">
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Shift+Enter for new line</span>
            <button type="button" className="hedwig-home-send" onClick={() => submit()} disabled={loading || !prompt.trim()}>
              {loading ? "Starting…" : "Send"}
            </button>
          </div>
        </div>

        {error && <p style={{ color: "#b91c1c", fontSize: 13, marginTop: 16 }}>{error}</p>}

        {recent.length > 0 && (
          <div style={{ width: "100%", marginTop: 36 }}>
            <p style={{ margin: "0 0 10px", fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)" }}>
              RECENT WORKSPACES
            </p>
            <div className="hedwig-recent-card">
              {recent.map((s) => (
                <Link key={s.id} href={`/search/${s.id}`} className="hedwig-recent-row">
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>{s.prompt}</p>
                  <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
                    {s.lead_count} leads · {s.status_message || s.status}
                  </p>
                </Link>
              ))}
            </div>
          </div>
        )}

        {recent.length === 0 && (
          <div style={{ display: "grid", gap: 10, width: "100%", marginTop: 24 }}>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => submit(ex)}
                disabled={loading}
                style={{
                  textAlign: "left",
                  padding: "14px 16px",
                  background: "#fff",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  cursor: "pointer",
                  fontSize: 13,
                  fontFamily: "inherit",
                }}
              >
                {ex}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
