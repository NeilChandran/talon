import TopBar from "@/components/TopBar";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
      <TopBar />
      {children}
    </div>
  );
}
