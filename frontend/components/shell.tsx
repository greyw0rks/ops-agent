"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Today" },
  { href: "/decisions", label: "Decisions" },
  { href: "/activity", label: "Activity" },
  { href: "/operations", label: "Operations" },
  { href: "/rules", label: "Rules" },
];

export function Shell({
  children,
  businessName,
  pendingCount,
  agent,
  refreshing,
}: {
  children: ReactNode;
  businessName?: string;
  pendingCount?: number;
  agent?: { provider: string; model_id: string };
  refreshing?: boolean;
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen md:grid md:grid-cols-[216px_1fr]">
      {/* Sidebar. Collapses to a horizontal strip on a phone, which is where an
          owner reads this between jobs. */}
      <aside className="border-b bg-card md:sticky md:top-0 md:h-screen md:border-r md:border-b-0">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <span
            aria-hidden
            className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-[15px] font-bold text-primary-foreground"
          >
            O
          </span>
          <div className="min-w-0">
            <p className="text-[14px] font-semibold leading-tight">
              {businessName ?? "Ops Agent"}
            </p>
            <p className="text-[12px] leading-tight text-muted-foreground">Operations agent</p>
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
          {NAV.map((item) => {
            const active = pathname === item.href;
            const badge = item.href === "/decisions" ? pendingCount : undefined;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[14px] transition-colors duration-150",
                  active
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.label}
                {badge ? (
                  <span className="tnum ml-auto rounded-sm border border-wait-border bg-wait-surface px-1.5 text-[12px] font-semibold text-wait-text">
                    {badge}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>

        {agent && (
          <div className="hidden border-t px-5 py-3 md:block">
            <p className="text-[12px] text-muted-foreground">Reasoning with</p>
            <p className="ident mt-0.5 break-all text-foreground">{agent.model_id}</p>
            <p className="ident mt-0.5 text-muted-foreground">via {agent.provider}</p>
          </div>
        )}
      </aside>

      <main className="min-w-0">
        <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
          {children}
          <footer className="mt-10 flex items-center gap-2 border-t pt-4 text-[12px] text-muted-foreground">
            <span
              aria-hidden
              className={cx(
                "h-1.5 w-1.5 rounded-full transition-colors duration-300",
                refreshing ? "bg-primary" : "bg-border-strong",
              )}
            />
            {refreshing ? "Checking for new work…" : "Up to date"}
          </footer>
        </div>
      </main>
    </div>
  );
}

export function PageTitle({ title, lede }: { title: string; lede?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-[26px] font-semibold leading-tight tracking-tight">{title}</h1>
      {lede && <p className="mt-1.5 max-w-2xl text-[16px] leading-relaxed text-muted-foreground">{lede}</p>}
    </header>
  );
}
