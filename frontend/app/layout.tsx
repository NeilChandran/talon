import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Talon — LinkedIn Outreach",
  description: "AI-powered LinkedIn prospecting and outreach automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-surface text-ink" style={{ minHeight: "100vh", display: "flex" }}>
        <Sidebar />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: "100vh", background: "#fff" }}>
          {children}
        </div>
      </body>
    </html>
  );
}
