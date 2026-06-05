/** Notify sidebar / tabs when a workspace is permanently deleted. */
export const WORKSPACE_DELETED = "talon:workspace-deleted";

export function notifyWorkspaceDeleted(id: string) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(WORKSPACE_DELETED, { detail: { id } }));
  }
}
