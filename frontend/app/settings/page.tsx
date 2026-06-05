"use client";

import { useEffect, useState } from "react";
import { connectLinkedIn, disconnectLinkedIn, getAppSettings, getLinkedInStatus, loginWithLinkedInBrowser, testLinkedInSession, updateAppSettings } from "@/lib/api";
import type { AppSettings } from "@/types";
import { peek, put, invalidate } from "@/lib/cache";
import type { LinkedInSession } from "@/types";

export default function SettingsPage() {
  const [session, setSession] = useState<LinkedInSession | null>(() => peek<LinkedInSession>("li-session") ?? null);
  const [loading, setLoading] = useState(false);
  const [browserLoginStep, setBrowserLoginStep] = useState<"idle" | "opening" | "waiting">("idle");
  const [checking, setChecking] = useState(!peek("li-session"));
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [error, setError] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [liAt, setLiAt] = useState("");
  const [jsessionid, setJsessionid] = useState("");
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [instantlyCampaignId, setInstantlyCampaignId] = useState("");
  const [savingInstantly, setSavingInstantly] = useState(false);

  useEffect(() => {
    getLinkedInStatus()
      .then(s => { setSession(s); put("li-session", s); setError(""); })
      .catch((e: unknown) => {
        setSession({ connected: false });
        const msg = e instanceof Error ? e.message : "";
        if (msg.includes("Connection failed") || msg.includes("Cannot reach")) {
          setError(msg);
        }
      })
      .finally(() => setChecking(false));
    getAppSettings()
      .then((s) => {
        setAppSettings(s);
        setInstantlyCampaignId(s.instantly_campaign_id || "");
      })
      .catch(() => {});
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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
      setBrowserLoginStep("idle");
    }
  };

  const handleConnect = async () => {
    if (!liAt.trim()) { setError("Paste your li_at cookie value."); return; }
    setLoading(true);
    setError("");
    try {
      const result = await connectLinkedIn(
        liAt.trim(),
        jsessionid.trim() || "ajax:0",
        "",
        ""
      );
      setSession(result);
      put("li-session", result);
      if (result.connected) {
        setLiAt("");
        setJsessionid("");
      } else {
        setError((result as any).error || "Could not connect — make sure you're logged into LinkedIn");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect");
    } finally {
      setLoading(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestMsg("");
    setError("");
    try {
      const r = await testLinkedInSession();
      if (r.connected) {
        setSession(r);
        put("li-session", r);
        setTestMsg(r.name ? `API OK — ${r.name}` : "API connection verified");
      } else {
        setTestMsg("");
        setError(r.error || "Session invalid — sign in again");
        setSession({ connected: false });
        put("li-session", { connected: false });
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Test failed — is the backend running on :8000?");
    } finally {
      setTesting(false);
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

        {error && (
          <div style={{ marginBottom: 16, padding: "12px 16px", background: "#F4F0FF", border: "1px solid #E4DEFF", borderRadius: 9, fontSize: 13, color: "#5B46B8" }}>
            {error}
          </div>
        )}

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
                <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
                  <button
                    onClick={handleTest}
                    disabled={testing}
                    style={{ fontSize: 11, fontWeight: 600, padding: "5px 10px", borderRadius: 6, border: "1.5px solid #bbf7d0", background: "#f0fdf4", color: "#166534", cursor: testing ? "wait" : "pointer" }}
                  >
                    {testing ? "Testing..." : "Test API"}
                  </button>
                  <button
                    onClick={handleDisconnect}
                    style={{ fontSize: 12, color: "#b0b0b4", background: "none", border: "none", cursor: "pointer", padding: "4px 6px" }}
                    onMouseOver={e => (e.currentTarget.style.color = "#6E56CF")}
                    onMouseOut={e => (e.currentTarget.style.color = "#b0b0b4")}
                  >
                    Disconnect
                  </button>
                </div>
              </div>
              {testMsg && (
                <p style={{ margin: "12px 0 0", fontSize: 12, color: "#166534", background: "#f0fdf4", padding: "8px 12px", borderRadius: 7, border: "1px solid #bbf7d0" }}>
                  {testMsg}
                </p>
              )}
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
                    background: loading ? "#d0d0d4" : "var(--accent, #6E56CF)",
                      color: "#fff", fontWeight: 700, fontSize: 14,
                      border: "none", borderRadius: 9,
                      cursor: loading ? "not-allowed" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 9,
                      letterSpacing: "-0.01em",
                      boxShadow: loading ? "none" : "0 1px 6px rgba(0,119,181,0.25)",
                      transition: "all 0.1s",
                    }}
                    onMouseOver={e => { if (!loading) e.currentTarget.style.background = "#5B46B8"; }}
                    onMouseOut={e => { if (!loading) e.currentTarget.style.background = "#6E56CF"; }}
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
                    <div style={{ padding: "10px 14px", marginBottom: 12, background: "#fff1f2", border: "1px solid #E4DEFF", borderRadius: 7, fontSize: 13, color: "#9f1239" }}>
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
                        JSESSIONID <span style={{ fontWeight: 400, color: "#8a8a8e", textTransform: "none" }}>(optional — use browser login if connect fails)</span>
                      </label>
                      <input type="password" value={jsessionid} onChange={e => setJsessionid(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && handleConnect()}
                        placeholder={`ajax:1234567890123456789`} className="input"
                        style={{ fontFamily: "monospace", fontSize: 12, marginBottom: 12 }} autoComplete="off" />

                      <button onClick={handleConnect} disabled={loading || !liAt.trim()} style={{
                        width: "100%", padding: "10px 0",
                        background: loading || !liAt.trim() ? "#e0e0e2" : "#0a0a0a",
                        color: loading || !liAt.trim() ? "#a0a0a4" : "#fff",
                        fontWeight: 600, fontSize: 13,
                        border: "none", borderRadius: 7,
                        cursor: loading || !liAt.trim() ? "not-allowed" : "pointer",
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

        <div className="card" style={{ padding: 20, marginBottom: 16 }}>
          <h2 style={{ margin: "0 0 8px", fontSize: 15, fontWeight: 700 }}>Instantly (email outreach)</h2>
          <p style={{ margin: "0 0 12px", fontSize: 12, color: "var(--text-secondary)" }}>
            Set INSTANTLY_CAMPAIGN_ID in backend/.env (preferred) or save here. Leads with emails push via Instantly API.
            {appSettings?.dry_run && " Dry run is ON — no leads will be sent."}
          </p>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)" }}>Instantly campaign ID</label>
          <input
            value={instantlyCampaignId}
            onChange={(e) => setInstantlyCampaignId(e.target.value)}
            placeholder="uuid-from-instantly"
            className="input"
            style={{ marginTop: 6, marginBottom: 10 }}
          />
          <div style={{ display: "flex", gap: 8, fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>
            <span>Serper: {appSettings?.has_serper ? "✓" : "—"}</span>
            <span>Proxycurl: {appSettings?.has_proxycurl ? "✓" : "—"}</span>
            <span>Instantly: {appSettings?.has_instantly ? "✓" : "—"}</span>
            <span>Talon Research: {appSettings?.has_origami ? "✓" : "—"}</span>
          </div>
          <button
            type="button"
            className="btn-secondary"
            disabled={savingInstantly}
            onClick={async () => {
              setSavingInstantly(true);
              try {
                const s = await updateAppSettings({ instantly_campaign_id: instantlyCampaignId });
                setAppSettings(s);
              } catch (e: unknown) {
                setError(e instanceof Error ? e.message : "Save failed");
              } finally {
                setSavingInstantly(false);
              }
            }}
          >
            {savingInstantly ? "Saving…" : "Save Instantly settings"}
          </button>
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
