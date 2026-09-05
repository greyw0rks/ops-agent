"use client";

import { createContext, useContext, type ReactNode } from "react";

import { api } from "@/lib/api";
import type { BusinessConfig } from "@/lib/types";
import { usePoll } from "@/lib/use-poll";

import { Shell } from "./shell";

interface ChromeState {
  business: BusinessConfig | null;
  currency: string;
  pendingCount: number;
  refreshChrome: () => void;
}

const ChromeContext = createContext<ChromeState>({
  business: null,
  currency: "NGN",
  pendingCount: 0,
  refreshChrome: () => {},
});

/** Business config and the pending-decision count, so the sidebar badge is right on
 *  every page without each page fetching them again. Config barely changes, so it is
 *  polled slowly; the badge needs to be current, so it is polled at feed speed. */
export function useChrome() {
  return useContext(ChromeContext);
}

export function AppShell({ children }: { children: ReactNode }) {
  const business = usePoll(api.business, 30_000);
  const approvals = usePoll(() => api.approvals("pending"), 5_000);

  const value: ChromeState = {
    business: business.data,
    currency: business.data?.currency ?? "NGN",
    pendingCount: approvals.data?.count ?? 0,
    refreshChrome: () => {
      void approvals.refresh();
    },
  };

  return (
    <ChromeContext.Provider value={value}>
      <Shell
        businessName={business.data?.name}
        pendingCount={value.pendingCount}
        agent={business.data?.agent}
        refreshing={business.refreshing || approvals.refreshing}
      >
        {children}
      </Shell>
    </ChromeContext.Provider>
  );
}
