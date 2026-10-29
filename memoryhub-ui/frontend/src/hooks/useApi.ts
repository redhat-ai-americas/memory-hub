import { useCallback, useEffect, useRef, useState } from 'react';

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** Re-run the request. Keeps the previous data visible while refreshing. */
  reload: () => void;
  setData: (data: T) => void;
}

/**
 * Load data for a screen. `deps` re-run the request; `pollMs` re-runs it on
 * an interval (used for the "waiting for the first memory" state).
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = [], pollMs?: number | null): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetcherRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, token]);

  useEffect(() => {
    if (!pollMs) return undefined;
    const id = window.setInterval(() => setToken((t) => t + 1), pollMs);
    return () => window.clearInterval(id);
  }, [pollMs]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}
