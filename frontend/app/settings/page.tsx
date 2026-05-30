"use client";

import { useEffect, useState } from "react";
import { connectLinkedIn, disconnectLinkedIn, getLinkedInStatus, loginWithLinkedInBrowser } from "@/lib/api";
import { peek, put, invalidate } from "@/lib/cache";
import type { LinkedInSession } from "@/types";

export default function SettingsPage() {
  const [session, setSession] = useState<LinkedInSession | null>(() => peek<LinkedInSession>("li-session") ?? null);
  const [loading, setLoading] = useState(false);
  const [browserLoginStep, setBrowserLoginStep] = useState<"idle" | "opening" | "waiting">("idle");
  const [checking, setChecking] = useState(!peek("li-session"));
  const [error, setError] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [liAt, setLiAt] = useState("");
  const [jsessionid, setJsessionid] = useState("");

  useEffect(() => {
    getLinkedInStatus()
      .then(s => { setSession(s); put("li-session", s); })
      .catch(() => setSession({ connected: false }))
      .finally(() => setChecking(false));
  }, []);

  const handleBrowserLogin = async () => {
    setLoading(true);
    setError("");
    setBrowserLoginStep("opening");
    try {
      setBrowserLoginStep("waiting");
      const result = await loginWithLinkedInBrowser();
      if (result.connected) {
        setSession(result);
        put("li-session", result);
      } else {
        setError((result as any).error || "Login failed — please try again");
      }
    } catch (e: any) {
      setError(e.message || "Login failed");
    } finally {
      setLoading(false);
      setBrowserLoginStep("idle");
    }
  };

  const handleConnect = async () => {
    if (!liAt.trim()) { setError("Paste your li_at cookie value."); return; }
    if (!jsessionid.trim()) { setError("Paste your JSESSIONID cookie value too."); return; }
    setLoading(true);
    setError("");
    try {
      const result = await connectLinkedIn(liAt.trim(), jsessionid.trim(), "", "");
      setSession(result);
      put("li-session", result);
      if (result.connected) {
        setLiAt("");
        setJsessionid("");
      } else {
        setError((result as any).error || "Could not connect — make sure you're logged into LinkedIn");
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
        <h1 className="page-title">Settings</h1>
      </header>

      <div style={{ padding: "0 40px", maxWidth: 520 }}>

        {/* LinkedIn card */}
        <div className="card" style={{ overflow: "hidden", marginBottom: 12 }}>

          {/* Card header row */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "18px 20px", borderBottom: "1px solid #f0f0f2" }}>
            <div style={{ width: 34, height: 34, borderRadius: 8, background: "#0077B5", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <svg viewBox="0 0 24 24" fill="white" width={17} height={17}>
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5, color: "#0a0a0a", letterSpacing: "-0.01em" }}>LinkedIn</div>
            </div>
            {checking ? (
              <div style={{ width: 9, height: 9, border: "2px solid #d0d0d4", borderTopColor: "#6b6b70", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
            ) : session?.connected ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, fontWeight: 600, color: "#16a34a", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "3px 9px", borderRadius: 20 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#16a34a", display: "inline-block" }} />
                Connected
              </span>
            ) : (
              <span style={{ fontSize: 11.5, fontWeight: 500, color: "#8a8a8e", background: "#f7f7f8", border: "1px solid #e8e8ea", padding: "3px 9px", borderRadius: 20 }}>Not connected</span>
            )}
          </div>

          {/* Body */}
          {session?.connected ? (
            <div style={{ padding: "18px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
                <div style={{ width: 40, height: 40, borderRadius: "50%", background: "#e8f4fd", border: "1.5px solid #0077B5", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 700, color: "#0077B5", flexShrink: 0 }}>
                  {(session.name || "?")[0].toUpperCase()}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: "#0a0a0a", letterSpacing: "-0.02em" }}>{session.name}</div>
                  {session.headline && <div style={{ fontSize: 12, color: "#6b6b70", marginTop: 2, lineHeight: 1.4 }}>{session.headline}</div>}
                  {session.linkedin_url && (
                    <a href={session.linkedin_url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 11.5, color: "#0077B5", textDecoration: "none", marginTop: 3, display: "block", letterSpacing: "-0.01em" }}>
                      {session.linkedin_url}
                    </a>
                  )}
                </div>
                <button
                  onClick={handleDisconnect}
                  style={{ fontSize: 12, color: "#b0b0b4", background: "none", border: "none", cursor: "pointer", padding: "4px 6px", transition: "color 0.1s" }}
                  onMouseOver={e => (e.currentTarget.style.color = "#D90429")}
                  onMouseOut={e => (e.currentTarget.style.color = "#b0b0b4")}
                >
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            <div style={{ padding: "18px 20px" }}>

              {browserLoginStep === "waiting" ? (
                <div style={{ textAlign: "center", padding: "24px 0" }}>
                  <div style={{ width: 36, height: 36, border: "3px solid #e0e7ff", borderTopColor: "#0077B5", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 16px" }} />
                  <div style={{ fontWeight: 700, fontSize: 14, color: "#0a0a0a", marginBottom: 5, letterSpacing: "-0.02em" }}>Sign in to LinkedIn</div>
                  <div style={{ fontSize: 13, color: "#8a8a8e", lineHeight: 1.6 }}>
                    A browser window opened — sign in there.<br />
                    It will minimize automatically once you're in.
                  </div>
                </div>
              ) : (
                <>
                  <button
                    onClick={handleBrowserLogin}
                    disabled={loading}
                    style={{
                      width: "100%", padding: "12px 0", marginBottom: 14,
                      background: loading ? "#d0d0d4" : "#0077B5",
                      color: "#fff", fontWeight: 700, fontSize: 14,
                      border: "none", borderRadius: 9,
                      cursor: loading ? "not-allowed" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 9,
                      letterSpacing: "-0.01em",
                      boxShadow: loading ? "none" : "0 1px 6px rgba(0,119,181,0.25)",
                      transition: "all 0.1s",
                    }}
                    onMouseOver={e => { if (!loading) e.currentTarget.style.background = "#006aa3"; }}
                    onMouseOut={e => { if (!loading) e.currentTarget.style.background = "#0077B5"; }}
                  >
                    {loading && browserLoginStep === "opening" ? (
                      <>
                        <span style={{ display: "inline-block", width: 15, height: 15, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                        Opening browser...
                      </>
                    ) : (
                      <>
                        <svg viewBox="0 0 24 24" fill="white" width={16} height={16}>
                          <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                        </svg>
                        Sign in with LinkedIn
                      </>
                    )}
                  </button>

                  {error && (
                    <div style={{ padding: "10px 14px", marginBottom: 12, background: "#fff1f2", border: "1px solid #fecdd3", borderRadius: 7, fontSize: 13, color: "#9f1239" }}>
                      {error}
                    </div>
                  )}

                  <button onClick={() => { setShowManual(!showManual); setError(""); }} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    width: "100%", fontSize: 12, fontWeight: 500, color: "#8a8a8e",
                    background: "none", border: "1px solid #ececee",
                    cursor: "pointer", padding: "7px 12px", borderRadius: 7,
                    letterSpacing: "-0.01em",
                  }}>
                    <span>Paste cookies manually</span>
                    <span style={{ fontSize: 10, color: "#c0c0c4" }}>{showManual ? "▲" : "▼"}</span>
                  </button>

                  {showManual && (
                    <div style={{ marginTop: 12, padding: "16px", background: "#fafafa", border: "1px solid #ececee", borderRadius: 8 }}>
                      <p style={{ margin: "0 0 12px", fontSize: 12, color: "#8a8a8e", lineHeight: 1.6 }}>
                        Chrome → DevTools (undocked) → Application → Cookies → linkedin.com
                      </p>

                      <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#5a5a5e", marginBottom: 5, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                        li_at
                      </label>
                      <input type="password" value={liAt} onChange={e => setLiAt(e.target.value)}
                        placeholder="AQEDASfYiuIFNC44..." className="input"
                        style={{ fontFamily: "monospace", fontSize: 12, marginBottom: 10 }} autoComplete="off" />

                      <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#5a5a5e", marginBottom: 5, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                        JSESSIONID
                      </label>
                      <input type="password" value={jsessionid} onChange={e => setJsessionid(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && handleConnect()}
                        placeholder={`"ajax:1234567890123456789"`} className="input"
                        style={{ fontFamily: "monospace", fontSize: 12, marginBottom: 12 }} autoComplete="off" />

                      <button onClick={handleConnect} disabled={loading || !liAt.trim() || !jsessionid.trim()} style={{
                        width: "100%", padding: "10px 0",
                        background: loading || !liAt.trim() || !jsessionid.trim() ? "#e0e0e2" : "#0a0a0a",
                        color: loading || !liAt.trim() || !jsessionid.trim() ? "#a0a0a4" : "#fff",
                        fontWeight: 600, fontSize: 13,
                        border: "none", borderRadius: 7,
                        cursor: loading || !liAt.trim() || !jsessionid.trim() ? "not-allowed" : "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                        letterSpacing: "-0.01em",
                      }}>
                        {loading ? (
                          <><span style={{ display: "inline-block", width: 13, height: 13, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} /> Connecting...</>
                        ) : "Connect"}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Rate limit notice */}
        <div style={{ padding: "12px 16px", background: "#fafafa", border: "1px solid #ececee", borderRadius: 9, display: "flex", gap: 10, alignItems: "flex-start" }}>
          <svg viewBox="0 0 16 16" fill="none" width={14} height={14} style={{ marginTop: 1, flexShrink: 0 }}>
            <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 018 5zm0 6.5a1 1 0 110-2 1 1 0 010 2z" fill="#9a9aa0"/>
          </svg>
          <div>
            <p style={{ fontWeight: 600, fontSize: 12.5, color: "#3a3a3c", margin: 0, marginBottom: 2, letterSpacing: "-0.01em" }}>Use responsibly</p>
            <p style={{ fontSize: 12, color: "#8a8a8e", margin: 0, lineHeight: 1.6 }}>
              LinkedIn limits connection requests to ~100/week. Talon adds delays between actions to stay safe.
            </p>
          </div>
        </div>

      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
