"use client";

import { useEffect, useState } from "react";
import { connectLinkedIn, disconnectLinkedIn, getLinkedInStatus } from "@/lib/api";
import { peek, put, invalidate } from "@/lib/cache";
import type { LinkedInSession } from "@/types";

export default function SettingsPage() {
  const [session, setSession] = useState<LinkedInSession | null>(() => peek<LinkedInSession>("li-session") ?? null);
  const [liAt, setLiAt] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(!peek("li-session"));
  const [error, setError] = useState("");
  const [showInstructions, setShowInstructions] = useState(false);

  useEffect(() => {
    getLinkedInStatus()
      .then(s => { setSession(s); put("li-session", s); })
      .catch(() => setSession({ connected: false }))
      .finally(() => setChecking(false));
  }, []);

  const handleConnect = async () => {
    if (!liAt.trim()) {
      setError("Paste your li_at cookie value.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await connectLinkedIn(liAt.trim());
      setSession(result);
      put("li-session", result);
      if (!result.connected) {
        setError(result.error || "Session invalid — try copying the cookie again");
      } else {
        setLiAt("");
      }
    } catch (e: any) {
      setError(e.message || "Failed to connect");
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect LinkedIn account?")) return;
    await disconnectLinkedIn();
    const disconnected = { connected: false };
    setSession(disconnected);
    put("li-session", disconnected);
    invalidate("sequences");
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Connect your LinkedIn account to enable outreach automation</p>
        </div>
      </header>

      <div style={{ padding: "0 36px", maxWidth: 560 }}>

        {/* LinkedIn card */}
        <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
          {/* Card header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "16px 20px",
            borderBottom: "1px solid #e8e8ea",
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: "#0077B5",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <svg viewBox="0 0 24 24" fill="white" width={18} height={18}>
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 14, color: "#0a0a0a" }}>LinkedIn Account</div>
              <div style={{ fontSize: 12, color: "#6b6b70", marginTop: 1 }}>Used to find real profiles and send connection requests</div>
            </div>
            {checking ? (
              <div style={{
                width: 10, height: 10, border: "2px solid #d0d0d4",
                borderTopColor: "#6b6b70", borderRadius: "50%",
                animation: "spin 0.8s linear infinite",
              }} />
            ) : session?.connected ? (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                fontSize: 12, fontWeight: 600, color: "#16a34a",
                background: "#f0fdf4", border: "1px solid #bbf7d0",
                padding: "4px 10px", borderRadius: 20,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#16a34a", display: "inline-block" }} />
                Connected
              </span>
            ) : (
              <span style={{
                fontSize: 12, fontWeight: 500, color: "#6b6b70",
                background: "#f7f7f8", border: "1px solid #e0e0e2",
                padding: "4px 10px", borderRadius: 20,
              }}>
                Not connected
              </span>
            )}
          </div>

          {/* Card body */}
          {session?.connected ? (
            <div style={{ padding: "20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                  width: 44, height: 44, borderRadius: "50%",
                  background: "#e8f4fd", border: "2px solid #0077B5",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 18, fontWeight: 700, color: "#0077B5", flexShrink: 0,
                }}>
                  {(session.name || "?")[0].toUpperCase()}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: "#0a0a0a" }}>{session.name}</div>
                  {session.headline && (
                    <div style={{ fontSize: 12, color: "#5a5a5e", marginTop: 2 }}>{session.headline}</div>
                  )}
                  {session.linkedin_url && (
                    <a href={session.linkedin_url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 12, color: "#0077B5", textDecoration: "none", marginTop: 2, display: "block" }}>
                      {session.linkedin_url}
                    </a>
                  )}
                </div>
                <button onClick={handleDisconnect}
                  style={{ fontSize: 12, color: "#8a8a8e", background: "none", border: "none", cursor: "pointer", padding: "4px 8px" }}
                  onMouseOver={e => (e.currentTarget.style.color = "#D90429")}
                  onMouseOut={e => (e.currentTarget.style.color = "#8a8a8e")}
                >
                  Disconnect
                </button>
              </div>

              <div style={{
                marginTop: 16, padding: "12px 16px",
                background: "#f0fdf4", border: "1px solid #bbf7d0",
                borderRadius: 8,
                fontSize: 13, color: "#166534",
              }}>
                ✓ LinkedIn connected — you can now prospect and automate outreach
              </div>
            </div>
          ) : (
            <div style={{ padding: "20px" }}>
              <p style={{ fontSize: 13, color: "#3a3a3c", marginBottom: 16, lineHeight: 1.6 }}>
                Paste your <code style={{ background: "#f0f0f2", padding: "1px 5px", borderRadius: 4, fontSize: 12, color: "#D90429", fontWeight: 600 }}>li_at</code> cookie from your LinkedIn session. Talon uses this to search real profiles and send outreach on your behalf — one cookie, done.
              </p>

              <button
                onClick={() => setShowInstructions(!showInstructions)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  fontSize: 12, fontWeight: 500, color: "#5a5a5e",
                  background: "none", border: "none", cursor: "pointer", padding: 0,
                  marginBottom: 16,
                }}
              >
                <span style={{ fontSize: 10 }}>{showInstructions ? "▼" : "▶"}</span>
                How to get your li_at cookie
              </button>

              {showInstructions && (
                <div style={{
                  background: "#f7f7f8", border: "1px solid #e8e8ea",
                  borderRadius: 8, padding: "14px 16px",
                  marginBottom: 16,
                }}>
                  <p style={{ fontSize: 12, fontWeight: 600, color: "#0a0a0a", marginBottom: 8 }}>Steps (takes 30 seconds):</p>
                  <ol style={{ margin: 0, paddingLeft: 20, fontSize: 12, color: "#3a3a3c", lineHeight: 2.2 }}>
                    <li>Open <strong>linkedin.com</strong> and make sure you are signed in</li>
                    <li>Press <code style={{ background: "#e8e8ea", padding: "1px 5px", borderRadius: 4 }}>F12</code> to open DevTools (or right-click → Inspect)</li>
                    <li>Click <strong>Application</strong> tab → <strong>Cookies</strong> in the left sidebar → <strong>https://www.linkedin.com</strong></li>
                    <li>Find the cookie named <code style={{ color: "#D90429", fontWeight: 700 }}>li_at</code></li>
                    <li>Click on it and copy the full <strong>Value</strong> (it starts with <code>AQE...</code>)</li>
                    <li>Paste it below and click Connect</li>
                  </ol>
                  <p style={{ margin: "10px 0 0", fontSize: 11, color: "#8a8a8e" }}>
                    That's the only cookie you need. JSESSIONID is derived automatically.
                  </p>
                </div>
              )}

              <div style={{ marginBottom: 16 }}>
                <label className="label">li_at cookie value</label>
                <input
                  type="password"
                  value={liAt}
                  onChange={e => setLiAt(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && handleConnect()}
                  placeholder="AQEDAxxxxxxxx..."
                  className="input"
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
              </div>

              {error && (
                <div style={{
                  padding: "10px 14px", marginBottom: 14,
                  background: "#fff1f2", border: "1px solid #fecdd3",
                  borderRadius: 7, fontSize: 13, color: "#9f1239",
                }}>
                  {error}
                </div>
              )}

              <button
                onClick={handleConnect}
                disabled={loading || !liAt.trim()}
                style={{
                  width: "100%", padding: "11px 0",
                  background: loading || !liAt.trim() ? "#d0d0d4" : "#0077B5",
                  color: "#fff",
                  fontWeight: 600, fontSize: 14,
                  border: "none", borderRadius: 8,
                  cursor: loading ? "wait" : !liAt.trim() ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                  transition: "background 0.12s",
                }}
              >
                {loading ? (
                  <>
                    <span style={{ display: "inline-block", width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                    Connecting...
                  </>
                ) : "Connect LinkedIn"}
              </button>
            </div>
          )}
        </div>

        {/* Warning */}
        <div style={{
          background: "#fffbeb", border: "1px solid #fde68a",
          borderRadius: 10, padding: "14px 16px",
          display: "flex", gap: 12,
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>⚠️</span>
          <div>
            <p style={{ fontWeight: 600, fontSize: 13, color: "#92400e", margin: 0, marginBottom: 4 }}>Use responsibly</p>
            <p style={{ fontSize: 12, color: "#78350f", margin: 0, lineHeight: 1.6 }}>
              LinkedIn limits connection requests to ~100/week. Talon adds 4–10 second delays between actions. Sending too many too fast can cause a temporary account restriction.
            </p>
          </div>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
