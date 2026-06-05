import type { RecentSearch } from "@/lib/api";
import { talonMessage } from "@/lib/brand";

/** Human-readable workspace status — never claim "ready" until completed with leads. */
export function workspaceStatusLabel(s: RecentSearch): string {
  const count = s.lead_count ?? 0;
  if (s.status === "completed") {
    if (count > 0) return `${count} lead${count === 1 ? "" : "s"} ready`;
    return "Completed — no leads found";
  }
  if (s.status === "running") return talonMessage(s.status_message) || "Finding leads…";
  if (s.status === "failed") return talonMessage(s.status_message)?.slice(0, 80) || "Failed";
  if (s.status === "needs_input") return "Needs input";
  return talonMessage(s.status_message) || s.status;
}
