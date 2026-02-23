import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AegisChain — Cognitive Supply Chain Immune System",
  description:
    "Autonomous multi-agent supply chain threat detection, rerouting, and auditing powered by Elasticsearch and ES|QL.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://api.mapbox.com/mapbox-gl-js/v3.9.0/mapbox-gl.css"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
