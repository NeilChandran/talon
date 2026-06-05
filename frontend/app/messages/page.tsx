"use client";

import { useCallback, useEffect, useState } from "react";
import { getAppSettings, updateAppSettings } from "@/lib/api";

function CharCount({ count, max }: { count: number; max?: number }) {
  const over = max != null && count > max;
  return (
    <span className={`hedwig-messages-chars${over ? " over" : ""}`}>
      {count}
      {max != null ? ` / ${max}` : ""}
    </span>
  );
}

export default function MessagesPage() {
  const [connection, setConnection] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const s = await getAppSettings();
      setConnection(s.linkedin_connection_template || "");
      setFollowUp(s.linkedin_follow_up_template || "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not load messages");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await updateAppSettings({
        linkedin_connection_template: connection,
        linkedin_follow_up_template: followUp,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="hedwig-messages">
      <header className="hedwig-messages-head">
        <div>
          <p className="origami-seq-breadcrumb">SEQUENCING</p>
          <h1 className="hedwig-messages-title">Messages</h1>
          <p className="hedwig-messages-sub">
            Default LinkedIn connection request and follow-up DM for all campaigns. Use{" "}
            <code>{"{{first_name}}"}</code> and <code>{"{{company}}"}</code> for personalization.
          </p>
        </div>
        <button
          type="button"
          className="hedwig-messages-save"
          disabled={saving || loading}
          onClick={save}
        >
          {saving ? "Saving…" : saved ? "Saved" : "Save messages"}
        </button>
      </header>

      {error && <p className="hedwig-messages-error">{error}</p>}

      {loading ? (
        <p className="hedwig-messages-loading">Loading…</p>
      ) : (
        <div className="hedwig-messages-body">
          <section className="origami-seq-step origami-seq-step--active hedwig-messages-step">
            <div className="origami-seq-step-head">
              <div className="origami-seq-step-title">
                <span className="origami-seq-step-num">1</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#0A66C2" aria-hidden>
                  <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 114.126 0 2.063 2.063 0 01-2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
                </svg>
                <span>Connection request</span>
              </div>
              <span className="origami-seq-step-badge drafted">Template</span>
            </div>
            <textarea
              className="hedwig-messages-textarea"
              value={connection}
              onChange={(e) => setConnection(e.target.value)}
              rows={7}
              placeholder="Hey {{first_name}}! …"
            />
            <div className="hedwig-messages-foot">
              <CharCount count={connection.length} max={300} />
              <span className="hedwig-messages-hint">Sent with your connection invite · max 300 chars</span>
            </div>
          </section>

          <section className="origami-seq-step hedwig-messages-step">
            <div className="origami-seq-step-head">
              <div className="origami-seq-step-title">
                <span className="origami-seq-step-num">2</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#0A66C2" aria-hidden>
                  <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 114.126 0 2.063 2.063 0 01-2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
                </svg>
                <span>Follow-up message</span>
              </div>
              <span className="origami-seq-step-badge muted">After accept</span>
            </div>
            <textarea
              className="hedwig-messages-textarea"
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              rows={12}
              placeholder="Wanted to follow up here…"
            />
            <div className="hedwig-messages-foot">
              <CharCount count={followUp.length} />
              <span className="hedwig-messages-hint">Sent 1 day after they accept (if no reply)</span>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
