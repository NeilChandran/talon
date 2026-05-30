import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import DataPrefetcher from "@/components/DataPrefetcher";

export const metadata: Metadata = {
  title: "Talon — LinkedIn Outreach",
  description: "AI-powered LinkedIn prospecting and outreach automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Tailwind via CDN — avoids PostCSS JIT file scan which hangs on iCloud Desktop */}
        <script src="https://cdn.tailwindcss.com" />
        <script dangerouslySetInnerHTML={{ __html: `
          tailwind.config = {
            theme: {
              extend: {
                colors: {
                  talon: { red: "#D90429", "red-hover": "#B8031F", "red-light": "#FFF0F2", "red-mid": "#FFD6DC" },
                  surface: { DEFAULT: "#F5F5F7", white: "#FFFFFF", hover: "#F0F0F2", active: "#E8E8EB", border: "#E2E2E6", "border-dark": "#C8C8CE" },
                  ink: { DEFAULT: "#1D1D1F", 2: "#3D3D40", 3: "#6E6E73", 4: "#98989D", 5: "#C7C7CC" },
                },
                fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "sans-serif"] },
              }
            }
          }
        ` }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..900;1,14..32,300..900&display=swap" rel="stylesheet" />
      </head>
      <body className="bg-surface text-ink" style={{ minHeight: "100vh", display: "flex" }}>
        <DataPrefetcher />
        <Sidebar />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: "100vh", background: "#fff" }}>
          {children}
        </div>
      </body>
    </html>
  );
}
