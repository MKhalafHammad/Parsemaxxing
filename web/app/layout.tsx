import type { Metadata } from "next";
import { connection } from "next/server";

import "./globals.css";

export const metadata: Metadata = {
  title: "Parsemaxxing",
  description: "Raw sample logs in, a tested CIM-compliant Splunk add-on out.",
};

// Route groups: (auth) for sign-in, MFA and setup (minimal frame); (app) for the signed-in shell.
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection(); // render per request, so Next.js can attach this request's CSP nonce
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-md focus:bg-surface-solid focus:p-2">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
