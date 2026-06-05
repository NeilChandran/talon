/** User-facing copy — Talon-native, no third-party vendor names. */

export function talonMessage(msg?: string | null): string {
  if (!msg) return "";
  let out = msg;
  const swaps: [string, string][] = [
    [
      "Origami concurrent agent limit (1 on your plan). Wait for the current run to finish, then retry.",
      "Research queue was busy — click Continue search to retry.",
    ],
    ["Origami concurrent agent limit — wait and retry", "Research queue was busy — try again."],
    ["Origami working…", "Talon researching…"],
    ["Answering Origami questions…", "Answering research questions…"],
    [
      "Server error — restart with ./scripts/start.sh (check backend terminal for details)",
      "Something hiccuped — your lead list in the table is still usable.",
    ],
  ];
  for (const [a, b] of swaps) out = out.replace(a, b);
  out = out.replace(/Origami/gi, "Talon");
  if (/RATE_LIMIT|rate limit|429/i.test(out)) {
    return "Research is temporarily busy — wait a moment, then click Try again.";
  }
  if (/poll failed|AGENT_NOT_FOUND|agent not found/i.test(out)) {
    return "Background research stopped early — use the leads already in your table.";
  }
  return out;
}

/** One-line explanation when a search fails before any leads land. */
export function searchFailHint(msg?: string | null, hasList = false): string {
  const friendly = talonMessage(msg);
  if (hasList) {
    return friendly || "Research stopped early — your leads in the table are still usable.";
  }
  if (/busy|429|rate limit|queue/i.test(friendly + (msg || ""))) {
    return "Talon’s research queue is busy right now — nothing wrong with your search. Wait ~30 seconds, then click Try again.";
  }
  return friendly || "Couldn't finish building your list — click Try again.";
}

/** Chat/API errors — never show raw JSON or restart commands when a list exists. */
export function friendlyChatError(msg: string, hasList: boolean): string {
  const friendly = talonMessage(msg);
  if (hasList) {
    if (/server error|restart|ECONNREFUSED|500|429|rate limit/i.test(msg)) {
      return "Couldn't reach research right now — your table below still has your leads. Click a row to preview drafted notes.";
    }
    return friendly || "Something didn't sync — your leads in the table are still good.";
  }
  return friendly || msg;
}
