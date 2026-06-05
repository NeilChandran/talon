"use client";

import { useEffect, useRef } from "react";
import { getSupabase, type LeadRow } from "@/lib/supabase";
import type { SearchDetail, SearchLead } from "@/lib/api";
import { buildLeadFromRow } from "@/lib/searchLeadMapper";

type Options = {
  searchId: string;
  search: SearchDetail | null;
  setSearch: React.Dispatch<React.SetStateAction<SearchDetail | null>>;
  /** Full reload from API (status/progress), less frequent */
  reload: () => Promise<SearchDetail | null | void>;
};

/**
 * Subscribe to Supabase Realtime on `leads` + `searches` for a search workspace.
 * New lead inserts stream into the table without polling the full lead list.
 */
export function useSearchRealtime({ searchId, search, setSearch, reload }: Options) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  useEffect(() => {
    const supa = getSupabase();
    if (!supa || !searchId) return;

    const mergeLead = (row: LeadRow, event: "INSERT" | "UPDATE") => {
      setSearch((prev) => {
        if (!prev) return prev;
        const mapped = buildLeadFromRow(row, prev);
        const leads = [...(prev.leads ?? [])];
        const idx = leads.findIndex((l) => l.id === mapped.id);
        if (idx >= 0) {
          leads[idx] = { ...leads[idx], ...mapped };
        } else if (event === "INSERT") {
          leads.push(mapped);
        }
        const lead_count = Math.max(prev.lead_count ?? 0, leads.length);
        return { ...prev, leads, lead_count };
      });
    };

    const channel = supa
      .channel(`search-${searchId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "leads",
          filter: `search_id=eq.${searchId}`,
        },
        (payload) => mergeLead(payload.new as LeadRow, "INSERT")
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "leads",
          filter: `search_id=eq.${searchId}`,
        },
        (payload) => mergeLead(payload.new as LeadRow, "UPDATE")
      )
      .on(
        "postgres_changes",
        {
          event: "DELETE",
          schema: "public",
          table: "leads",
          filter: `search_id=eq.${searchId}`,
        },
        (payload) => {
          const id = (payload.old as { id?: string })?.id;
          if (!id) return;
          setSearch((prev) => {
            if (!prev) return prev;
            const leads = (prev.leads ?? []).filter((l) => l.id !== id);
            return { ...prev, leads, lead_count: leads.length };
          });
        }
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "searches",
          filter: `id=eq.${searchId}`,
        },
        () => {
          reloadRef.current();
        }
      )
      .subscribe();

    return () => {
      supa.removeChannel(channel);
    };
  }, [searchId, setSearch]);

  // Poll search status while Origami is working (leads stream via Realtime)
  useEffect(() => {
    if (!search || !["running", "needs_input"].includes(search.status)) return;
    reloadRef.current();
    const t = setInterval(() => reloadRef.current(), 3000);
    return () => clearInterval(t);
  }, [search?.status, searchId]);
}
