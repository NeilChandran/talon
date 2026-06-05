import type { Metadata } from "next";
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Talon — LinkedIn Outreach",
  description: "AI-powered LinkedIn prospecting and outreach automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..900;1,14..32,300..900&display=swap" rel="stylesheet" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              document.addEventListener("click", function (e) {
                var a = e.target && e.target.closest ? e.target.closest("a[data-hard-nav]") : null;
                if (!a || e.defaultPrevented) return;
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                var href = a.getAttribute("href");
                if (!href || href.charAt(0) !== "/") return;
                e.preventDefault();
                e.stopImmediatePropagation();
                window.location.assign(href);
              }, true);
            `,
          }}
        />
      </head>
      <body style={{ minHeight: "100vh", display: "flex", margin: 0 }}>
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
