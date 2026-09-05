import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AppShell } from "@/components/app-shell";

import "./globals.css";

// Inter specifically: the type scale is solved from its measured x-height ratio, so
// substituting a different sans would make the 18px body size arbitrary rather than
// derived. JetBrains Mono carries identifiers — references, run ids, tool names.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono-face",
});

export const metadata: Metadata = {
  title: "Ops Agent",
  description:
    "The owner's view of an autonomous operations agent: what it did, what it needs you to decide, and the limits it works within.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
