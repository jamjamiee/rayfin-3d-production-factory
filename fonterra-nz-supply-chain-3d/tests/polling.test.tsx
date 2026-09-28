import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { POLL_MS, REQUEST_TIMEOUT_MS, useSnapshot } from '../src/useSnapshot';
import { makeSnapshot } from './fixtures';

describe('read-only snapshot polling', () => {
  const now = new Date('2026-09-12T07:00:00Z');
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); });
  async function settle() { await act(async () => { await Promise.resolve(); }); }

  it('accepts an independent Snapshot-returning adapter without HTTP or UI changes', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    const loader = vi.fn(async (_signal: AbortSignal) => makeSnapshot());
    const { result, unmount } = renderHook(() => useSnapshot(loader));
    await settle();
    expect(result.current.snapshot?.orders).toHaveLength(6);
    expect(fetcher).not.toHaveBeenCalled();
    expect(loader).toHaveBeenCalledWith(expect.any(AbortSignal));
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(loader).toHaveBeenCalledTimes(2);
    const signal = loader.mock.calls[1][0];
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('requests JSON without browser tokens and polls after 5 seconds', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(makeSnapshot())));
    vi.stubGlobal('fetch', fetcher);
    const { result } = renderHook(useSnapshot);
    expect(result.current.snapshot).toBeNull();
    await settle();
    expect(fetcher).toHaveBeenCalledWith('/api/factory/snapshot', expect.objectContaining({ headers: { Accept: 'application/json' }, cache: 'no-store', signal: expect.any(AbortSignal) }));
    expect(result.current.snapshot?.orders).toHaveLength(6);
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('permits one request in flight including manual retries, and aborts on unmount', async () => {
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal as AbortSignal;
      return new Promise<Response>(() => {});
    });
    vi.stubGlobal('fetch', fetcher);
    const { result, unmount } = renderHook(useSnapshot);
    act(() => { result.current.retry(); result.current.retry(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS * 2); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS * 3); });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('retains last good data on failures, marks it stale and recovers', async () => {
    const snapshot = makeSnapshot();
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot)))
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValue(new Response(JSON.stringify(snapshot)));
    vi.stubGlobal('fetch', fetcher);
    const { result } = renderHook(useSnapshot);
    await settle();
    expect(result.current.stale).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(result.current.error?.kind).toBe('network');
    expect(result.current.snapshot?.orders).toHaveLength(6);
    expect(result.current.stale).toBe(true);
    await act(async () => { result.current.retry(); });
    expect(result.current.error).toBeNull();
    expect(result.current.stale).toBe(false);
  });

  it.each([401, 403])('reports HTTP %i as authentication, without fake data', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'AUTH_REQUIRED', message: 'Sign in required.' } }), { status })));
    const { result } = renderHook(useSnapshot);
    await settle();
    expect(result.current.error).toEqual({ kind: 'auth', message: 'Sign in required.' });
    expect(result.current.snapshot).toBeNull();
  });

  it('handles non-JSON server errors and malformed success payloads', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('Bad gateway', { status: 502 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ orders: [] })))
      .mockResolvedValueOnce(new Response('<html>Sign in</html>'));
    vi.stubGlobal('fetch', fetcher);
    const { result } = renderHook(useSnapshot);
    await settle();
    expect(result.current.error?.kind).toBe('server');
    await act(async () => { result.current.retry(); });
    expect(result.current.error?.kind).toBe('contract');
    await act(async () => { result.current.retry(); });
    expect(result.current.error?.message).toContain('valid snapshot JSON');
    expect(result.current.snapshot).toBeNull();
  });

  it('times out a hung endpoint and retries after the timed-out request settles', async () => {
    const fetcher = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    vi.stubGlobal('fetch', fetcher);
    const { result } = renderHook(useSnapshot);
    await act(async () => { await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS); });
    expect(result.current.error?.message).toContain('timed out');
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('marks old server-generated snapshots stale despite successful polling', async () => {
    const snapshot = makeSnapshot(new Date(now.getTime() - 60_000).toISOString());
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot))));
    const { result } = renderHook(useSnapshot);
    await settle();
    expect(result.current.stale).toBe(true);
    expect(result.current.error).toBeNull();
  });
});
