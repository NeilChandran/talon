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
                  accent: { DEFAULT: "#6E56CF", hover: "#5B46B8", light: "#F4F0FF", mid: "#E4DEFF" },
                },
                fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "sans-serif"] },
              }
            }
          }
        ` }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..900;1,14..32,300..900&display=swap" rel="stylesheet" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
      </head>
      <body style={{ minHeight: "100vh", display: "flex", margin: 0 }}>
        <DataPrefetcher />
        <Sidebar />
        <div className="main-frame">
          {children}
        </div>
      </body>
    </html>
  );
}
