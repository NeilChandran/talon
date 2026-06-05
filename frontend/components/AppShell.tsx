"use client";

import { usePathname } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import DataPrefetcher from "@/components/DataPrefetcher";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="app-shell">
      <DataPrefetcher />
      <Sidebar />
      <div className="main-frame">{children}</div>
    </div>
  );
}
