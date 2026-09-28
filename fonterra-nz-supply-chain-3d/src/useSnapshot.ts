import { useEffect, useRef, useState } from 'react';
import type { Snapshot } from './contract';
import { loadSnapshot, type SnapshotError, type SnapshotLoader } from './services/snapshotLoader';

export type { SnapshotError } from './services/snapshotLoader';
export const POLL_MS = 5_000;
export const REQUEST_TIMEOUT_MS = 15_000;

export function useSnapshot(loader: SnapshotLoader = loadSnapshot) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<SnapshotError | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [now, setNow] = useState(Date.now);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const retryRef = useRef<() => void>(() => {});

  useEffect(() => {
    let disposed = false;
    let inFlight = false;
    let nextPoll: ReturnType<typeof setTimeout>;
    let controller: AbortController | null = null;
    const clock = setInterval(() => setNow(Date.now()), 1_000);

    async function poll() {
      if (disposed || inFlight) return;
      clearTimeout(nextPoll);
      inFlight = true;
      setRefreshing(true);
      controller = new AbortController();
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; controller?.abort(); }, REQUEST_TIMEOUT_MS);
      try {
        const nextSnapshot = await loader(controller.signal);
        controller.signal.throwIfAborted();
        if (!disposed) {
          setSnapshot(nextSnapshot);
          setError(null);
          setLastSuccessAt(Date.now());
          setNow(Date.now());
        }
      } catch (failure) {
        if (!disposed) {
          const known = failure && typeof failure === 'object' && 'kind' in failure;
          setError(known ? failure as SnapshotError : {
            kind: 'network',
            message: timedOut ? 'Snapshot request timed out. Retrying automatically.' : 'Cannot reach the snapshot service. Check your connection.',
          });
        }
      } finally {
        clearTimeout(timeout);
        inFlight = false;
        if (!disposed) {
          setRefreshing(false);
          nextPoll = setTimeout(poll, POLL_MS);
        }
      }
    }
    retryRef.current = () => { void poll(); };
    void poll();
    return () => {
      disposed = true;
      controller?.abort();
      clearInterval(clock);
      clearTimeout(nextPoll);
      retryRef.current = () => {};
    };
  }, [loader]);

  const stale = !!snapshot && (!!error || now - Date.parse(snapshot.generatedAt) > 30_000);
  return { snapshot, error, refreshing, now, lastSuccessAt, stale, retry: () => retryRef.current() };
}
