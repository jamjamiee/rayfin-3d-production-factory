import { snapshotSchema, type Snapshot } from '../contract';

export interface SnapshotError { kind: 'host' | 'auth' | 'network' | 'server' | 'contract'; message: string }
export type SnapshotLoader = (signal: AbortSignal) => Promise<Snapshot>;

export function validateSnapshot(value: unknown): Snapshot {
  const parsed = snapshotSchema.safeParse(value);
  if (!parsed.success) throw { kind: 'contract', message: 'Snapshot format is invalid. No unverified data has been displayed.' } satisfies SnapshotError;
  return parsed.data;
}

export const loadHttpSnapshot: SnapshotLoader = async (signal) => {
  const response = await fetch('/api/factory/snapshot', {
    headers: { Accept: 'application/json' },
    signal,
    cache: 'no-store',
    credentials: 'same-origin',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { error?: { message?: unknown } } | null;
    throw {
      kind: response.status === 401 || response.status === 403 ? 'auth' : 'server',
      message: typeof body?.error?.message === 'string' ? body.error.message : `Snapshot request failed (HTTP ${response.status}).`,
    } satisfies SnapshotError;
  }
  let body: unknown;
  try { body = await response.json(); }
  catch { throw { kind: 'contract', message: 'The endpoint did not return valid snapshot JSON.' } satisfies SnapshotError; }
  signal.throwIfAborted();
  return validateSnapshot(body);
};

let nativeLoader: Promise<SnapshotLoader> | undefined;
const loadFabricSnapshot: SnapshotLoader = async (signal) => {
  signal.throwIfAborted();
  nativeLoader ??= import('./fabricSnapshot').then(({ createFabricSnapshotLoader }) =>
    createFabricSnapshotLoader<Snapshot>({
      workspaceId: import.meta.env.VITE_RAYFIN_WORKSPACE_ID ?? '',
      appId: import.meta.env.VITE_RAYFIN_ITEM_ID ?? '',
      modelId: import.meta.env.VITE_RAYFIN_MODEL_ID ?? '',
      apiUrl: import.meta.env.VITE_RAYFIN_API_URL ?? '',
      publishableKey: import.meta.env.VITE_RAYFIN_PUBLISHABLE_KEY ?? '',
      parseSnapshot: validateSnapshot,
    }),
  );
  const loader = await nativeLoader;
  signal.throwIfAborted();
  return loader(signal);
};

// Native mode is an explicit build choice; neither path silently falls back to the other.
export const loadSnapshot: SnapshotLoader = import.meta.env.MODE === 'fabric' ? loadFabricSnapshot : loadHttpSnapshot;
