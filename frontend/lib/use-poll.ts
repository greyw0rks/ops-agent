"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** True while a background refresh is in flight and we already have data. */
  refreshing: boolean;
  refresh: () => Promise<void>;
}

/** Poll a fetcher on an interval.
 *
 *  An agent run takes 20–50 seconds and finishes without telling the browser, so the
 *  dashboard polls rather than pretending to be realtime. Deliberately kept as a hook
 *  over a data library: one fewer dependency, and the only behaviour needed is "keep
 *  showing the last good value while the next request is in flight" — a spinner that
 *  replaces the feed every few seconds is worse than slightly stale numbers.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs = 4000): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Keeps the interval from closing over a stale fetcher without restarting it.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const mounted = useRef(true);

  const run = useCallback(async (background: boolean) => {
    if (background) setRefreshing(true);
    try {
      const next = await fetcherRef.current();
      if (!mounted.current) return;
      setData(next);
      setError(null);
    } catch (exc) {
      if (!mounted.current) return;
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void run(false);

    const id = setInterval(() => {
      // Don't poll a tab nobody is looking at.
      if (document.visibilityState === "visible") void run(true);
    }, intervalMs);

    const onVisible = () => {
      if (document.visibilityState === "visible") void run(true);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      mounted.current = false;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [run, intervalMs]);

  const refresh = useCallback(() => run(true), [run]);

  return { data, error, loading, refreshing, refresh };
}
