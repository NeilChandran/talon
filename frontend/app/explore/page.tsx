"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  addExploreEnrichment,
  createExploreSession,
  exploreExportUrl,
  getExploreSession,
  refineExploreSession,
  setExploreFilters,
  updateExploreRow,
} from "@/lib/api";
import type { EnrichmentColumnType, ExploreRow, ExploreSession } from "@/types";

const EXAMPLE_ICP =
  "B2B SaaS companies in the US with 10-50 employees using Stripe, hiring sales roles";

const BASE_COLUMNS = [
  { key: "company_name", label: "Company", editable: true },
  { key: "website", label: "Website", editable: true },
  { key: "industry", label: "Industry", editable: true },
  { key: "headcount", label: "Headcount", editable: true },
  { key: "location", label: "Location", editable: true },
  { key: "source", label: "Source", editable: false },
  { key: "signals", label: "Signals", editable: false },
  { key: "fit_score", label: "Fit Score", editable: false },
] as const;

const ENRICH_OPTIONS: { type: EnrichmentColumnType; label: string; key: string }[] = [
  { type: "work_email", label: "Work email", key: "work_email" },
  { type: "phone", label: "Phone", key: "phone" },
  { type: "tech_stack", label: "Tech stack", key: "tech_stack" },
  { type: "funding", label: "Funding", key: "funding" },
  { type: "decision_maker_linkedin", label: "Decision maker", key: "decision_maker_linkedin" },
];

const SCRAPER_LABELS: Record<string, string> = {
  linkedin: "LinkedIn (Playwright)",
  google_maps: "Google Maps (Playwright)",
  crunchbase: "Crunchbase",
  jobs: "Job boards",
  shopify: "Shopify",
  news: "News",
};

function scoreColor(score: number) {
  if (score >= 75) return "#166534";
  if (score >= 50) return "#6E56CF";
  return "#9a9a9a";
}

function EnrichCell({ cell }: { cell?: { value?: string; status?: string } }) {
  if (!cell || cell.status === "loading") {
    return (
      <span className="explore-cell-spinner" aria-label="Loading">
        <span className="explore-spinner" />
      </span>
    );
  }
  if (cell.status === "error") return <span style={{ color: "#b91c1c" }}>Error</span>;
  return <span>{cell.value || "—"}</span>;
}

export default function ExplorePage() {
  const [phase, setPhase] = useState<"input" | "results">("input");
  const [icp, setIcp] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [session, setSession] = useState<ExploreSession | null>(null);
  const [error, setError] = useState("");
  const [refine, setRefine] = useState("");
  const [refining, setRefining] = useState(false);
  const [sortKey, setSortKey] = useState<string>("fit_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [filterMinScore, setFilterMinScore] = useState("");
  const [filterMinHeadcount, setFilterMinHeadcount] = useState("");
  const [filterTech, setFilterTech] = useState("");
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const refresh = useCallback(async (id: string) => {
    try {
      const s = await getExploreSession(id);
      setSession(s);
      setError("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load session");
    }
  }, []);

  useEffect(() => {
    if (!session?.id || session.status !== "running") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(() => refresh(session.id), 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [session?.id, session?.status, refresh]);

  const handleSubmit = async () => {
    const prompt = icp.trim();
    if (!prompt) return;
    setSubmitting(true);
    setError("");
    try {
      const s = await createExploreSession(prompt);
      setSession(s);
      setPhase("results");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start search");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRefine = async () => {
    if (!session?.id || !refine.trim() || refining) return;
    setRefining(true);
    try {
      const s = await refineExploreSession(session.id, refine.trim());
      setSession(s);
      setRefine("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Refinement failed");
    } finally {
      setRefining(false);
    }
  };

  const applyFilters = async () => {
    if (!session?.id) return;
    const rules: Array<{ field: string; op: string; value: string }> = [];
    if (filterMinScore) rules.push({ field: "fit_score_min", op: "gte", value: filterMinScore });
    if (filterMinHeadcount) rules.push({ field: "headcount_min", op: "gte", value: filterMinHeadcount });
    if (filterTech) rules.push({ field: "must_use", op: "contains", value: filterTech });
    const s = await setExploreFilters(session.id, rules);
    setSession(s);
  };

  const handleCellEdit = async (row: ExploreRow, key: string, value: string) => {
    if (!session?.id) return;
    await updateExploreRow(session.id, row.id, { [key]: value } as Parameters<typeof updateExploreRow>[2]);
    refresh(session.id);
  };

  const visibleRows = (session?.rows ?? []).filter((r) => !r.hidden);
  const sortedRows = [...visibleRows].sort((a, b) => {
    const av = a[sortKey as keyof ExploreRow] ?? "";
    const bv = b[sortKey as keyof ExploreRow] ?? "";
    const cmp = sortKey === "fit_score"
      ? (a.fit_score ?? 0) - (b.fit_score ?? 0)
      : String(av).localeCompare(String(bv));
    return sortDir === "asc" ? cmp : -cmp;
  });

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "fit_score" ? "desc" : "asc");
    }
  };

  if (phase === "input") {
    return (
      <div className="explore-hero">
        <div className="explore-hero-inner">
          <h1 className="explore-hero-title">Who do you want to reach?</h1>
          <p className="explore-hero-sub">
            Describe your ideal customer in plain English. Talon runs real Playwright scrapers (Google Maps + LinkedIn). Connect LinkedIn in Settings first for company results.
          </p>
          <textarea
            className="explore-icp-input"
            value={icp}
            onChange={(e) => setIcp(e.target.value)}
            placeholder={EXAMPLE_ICP}
            rows={5}
            autoFocus
          />
          <div className="explore-hero-actions">
            <button
              type="button"
              className="btn-primary explore-submit"
              onClick={handleSubmit}
              disabled={submitting || !icp.trim()}
            >
              {submitting ? "Starting agents…" : "Find companies"}
            </button>
            <button type="button" className="btn-ghost" onClick={() => setIcp(EXAMPLE_ICP)}>
              Use example
            </button>
          </div>
          {error && <p className="explore-error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="explore-results">
      <header className="explore-results-header">
        <div>
          <h1 className="page-title">Explore</h1>
          <p className="explore-icp-preview">{session?.icp_prompt}</p>
        </div>
        <div className="explore-header-actions">
          <a
            href={session?.id ? exploreExportUrl(session.id) : "#"}
            className="btn-primary"
            download
            style={{ textDecoration: "none" }}
          >
            Export CSV
          </a>
          <button type="button" className="btn-secondary" onClick={() => { setPhase("input"); setSession(null); }}>
            New search
          </button>
        </div>
      </header>

      {error && <div className="explore-banner-error">{error}</div>}

      {session?.status === "running" && (
        <div className="explore-scraper-status">
          {Object.entries(session.scraper_status || {}).map(([name, st]) => (
            <span key={name} className={`explore-scraper-pill explore-scraper-${st.status}`}>
              {SCRAPER_LABELS[name] || name}: {st.status}
              {st.count > 0 ? ` (${st.count})` : ""}
              {st.error ? ` — ${st.error.slice(0, 40)}` : ""}
            </span>
          ))}
          <span className="explore-scraper-pill">Rows: {visibleRows.length}</span>
        </div>
      )}

      <div className="explore-toolbar">
        <div className="explore-filters">
          <input
            type="number"
            placeholder="Min fit score"
            value={filterMinScore}
            onChange={(e) => setFilterMinScore(e.target.value)}
            className="explore-filter-input"
          />
          <input
            type="number"
            placeholder="Min employees"
            value={filterMinHeadcount}
            onChange={(e) => setFilterMinHeadcount(e.target.value)}
            className="explore-filter-input"
          />
          <input
            placeholder="Must use (e.g. Shopify)"
            value={filterTech}
            onChange={(e) => setFilterTech(e.target.value)}
            className="explore-filter-input"
          />
          <button type="button" className="btn-secondary" onClick={applyFilters}>
            Apply filters
          </button>
        </div>
        <select
          className="explore-enrich-select"
          defaultValue=""
          onChange={async (e) => {
            const opt = ENRICH_OPTIONS.find((o) => o.key === e.target.value);
            if (!opt || !session?.id) return;
            e.target.value = "";
            const s = await addExploreEnrichment(session.id, opt.key, opt.type);
            setSession(s);
          }}
        >
          <option value="">+ Add enrichment column</option>
          {ENRICH_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="explore-table-wrap">
        <table className="explore-table">
          <thead>
            <tr>
              {BASE_COLUMNS.map((c) => (
                <th key={c.key}>
                  <button type="button" className="explore-th-btn" onClick={() => toggleSort(c.key)}>
                    {c.label}
                    {sortKey === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </button>
                </th>
              ))}
              {(session?.enrichment_columns ?? []).map((c) => (
                <th key={c.key}>{c.label || c.key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={BASE_COLUMNS.length + (session?.enrichment_columns?.length ?? 0)} className="explore-empty">
                  {session?.status === "running"
                    ? "Searching… rows appear as each source returns results."
                    : "No matching companies. Try refining your prompt or loosening filters."}
                </td>
              </tr>
            ) : (
              sortedRows.map((row) => (
                <tr key={row.id}>
                  {BASE_COLUMNS.map((col) => (
                    <td key={col.key}>
                      {col.key === "fit_score" ? (
                        <span style={{ fontWeight: 700, color: scoreColor(row.fit_score) }}>{row.fit_score}</span>
                      ) : col.key === "signals" ? (
                        <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                          {(row.raw_data?.signals ?? []).join(", ") || "—"}
                        </span>
                      ) : col.editable ? (
                        <input
                          className="explore-cell-input"
                          defaultValue={String(row[col.key as keyof ExploreRow] ?? "")}
                          onBlur={(e) => {
                            const v = e.target.value;
                            if (v !== String(row[col.key as keyof ExploreRow] ?? "")) {
                              handleCellEdit(row, col.key, v);
                            }
                          }}
                        />
                      ) : (
                        <span className="explore-source-tag">{row.source}</span>
                      )}
                    </td>
                  ))}
                  {(session?.enrichment_columns ?? []).map((c) => (
                    <td key={c.key}>
                      <EnrichCell cell={row.enrichment?.[c.key]} />
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="explore-refine">
        <div className="explore-chat-history">
          {(session?.messages ?? []).slice(-6).map((m) => (
            <div key={m.id} className={`explore-chat-msg ${m.role}`}>
              <strong>{m.role === "user" ? "You" : "Talon"}:</strong> {m.content}
            </div>
          ))}
        </div>
        <div className="explore-refine-row">
          <input
            className="explore-refine-input"
            value={refine}
            onChange={(e) => setRefine(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRefine()}
            placeholder='e.g. "find CTOs at these companies" or "filter to HubSpot users only"'
            disabled={refining}
          />
          <button type="button" className="btn-primary" onClick={handleRefine} disabled={refining || !refine.trim()}>
            {refining ? "…" : "Refine"}
          </button>
        </div>
      </div>
    </div>
  );
}
