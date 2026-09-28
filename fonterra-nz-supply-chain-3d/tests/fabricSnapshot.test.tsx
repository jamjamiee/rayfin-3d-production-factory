import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeSnapshot } from './fixtures';
import { validateSnapshot } from '../src/services/snapshotLoader';
import { createFabricSnapshotLoader, executeDaxViaFabricHost, FABRIC_BRIDGE_TIMEOUT_MS } from '../src/services/fabricSnapshot';
import { useSnapshot, REQUEST_TIMEOUT_MS, POLL_MS } from '../src/useSnapshot';

const sdk = vi.hoisted(() => ({
  authConstructor: vi.fn(), apiConstructor: vi.fn(), getSession: vi.fn(), initEmbeddedAuth: vi.fn(),
}));
vi.mock('@microsoft/rayfin-auth', () => ({
  Auth: class {
    constructor(...args: unknown[]) { sdk.authConstructor(...args); }
    getSession() { return sdk.getSession(); }
  },
}));
vi.mock('@microsoft/rayfin-lib', () => ({
  ApiClient: class { constructor(...args: unknown[]) { sdk.apiConstructor(...args); } },
}));
vi.mock('@microsoft/rayfin-auth-provider-fabric', () => ({ initEmbeddedAuth: sdk.initEmbeddedAuth }));

const ORIGIN = 'https://app.fabric.microsoft.com';
const CHANNEL = 'fabric-app-data-semantic-model';
const WORKSPACE = '11111111-1111-4111-8111-111111111111';
const APP = '22222222-2222-4222-8222-222222222222';
const MODEL = '33333333-3333-4333-8333-333333333333';
const options = {
  workspaceId: WORKSPACE, appId: APP, modelId: MODEL,
  apiUrl: `https://test.pbidedicated.windows.net/api/workspaces/${WORKSPACE}/appbackends/${APP}/`,
  publishableKey: 'pk-test-only-publishable', parseSnapshot: validateSnapshot,
};

function daxResult() {
  const { orders, lines, activity, ...metadata } = makeSnapshot();
  const row = (Kind: string, RowKey: string, payload: unknown) => ({
    Kind, RowKey, PayloadJson: JSON.stringify(payload), SnapshotId: 'test-consistent-snapshot',
  });
  return { results: [{ tables: [{ rows: [
    row('meta', 'meta', { ...metadata, __rowCounts: { orders: orders.length, lines: lines.length, activity: activity.length } }),
    ...orders.map((order) => row('order', `order:${order.id}`, order)),
    ...lines.map((line) => row('line', `line:${line.id}`, line)),
    ...activity.map((event) => row('activity', `activity:${event.id}`, event)),
  ] }] }] };
}

const parentFrame = { postMessage: vi.fn() };
function request() {
  const calls = parentFrame.postMessage.mock.calls;
  return calls[calls.length - 1][0] as Record<string, unknown>;
}
function respond(data: Record<string, unknown> = {}, event: Partial<MessageEventInit> = {}) {
  window.dispatchEvent(new MessageEvent('message', {
    origin: ORIGIN, source: parentFrame as unknown as Window,
    data: {
      channel: CHANNEL, version: 1, kind: 'response', requestId: request().requestId,
      success: true, result: { data: daxResult() }, ...data,
    },
    ...event,
  }));
}
const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-09-12T07:00:00Z'));
  vi.clearAllMocks();
  vi.stubGlobal('parent', parentFrame);
  vi.spyOn(document, 'referrer', 'get').mockReturnValue(`${ORIGIN}/groups/${WORKSPACE}`);
  sdk.getSession.mockReturnValue({ isAuthenticated: true });
  sdk.initEmbeddedAuth.mockResolvedValue({ isAuthenticated: true });
});
afterEach(() => { vi.unstubAllEnvs(); });

describe('exact native semantic-model envelope', () => {
  it('sends the documented outer method and fixed DAX to the exact trusted origin', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const payload = request();
    expect(parentFrame.postMessage).toHaveBeenCalledWith({
      channel: CHANNEL, version: 1, kind: 'request',
      method: 'semanticModel.executeDaxJson', requestId: expect.any(String),
      payload: { workspaceId: WORKSPACE, modelId: MODEL, query: 'EVALUATE FactorySnapshotRows' },
    }, ORIGIN);
    expect(payload.payload).not.toHaveProperty('method');
    expect(parentFrame.postMessage.mock.calls[0][1]).not.toBe('*');
    respond();
    await expect(pending).resolves.toEqual(daxResult());
  });

  it('ignores wrong source, origin, requestId and channel until an exactly matching response', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const settled = vi.fn();
    void pending.then(settled);
    respond({}, { source: window });
    respond({}, { origin: 'https://app.powerbi.com' });
    respond({}, { origin: 'https://app.fabric.microsoft.com.attacker.example' });
    respond({ requestId: 'unrelated-request' });
    respond({ channel: 'other-channel' });
    window.dispatchEvent(new MessageEvent('message', { origin: ORIGIN, source: parentFrame as unknown as Window, data: null }));
    await flush();
    expect(settled).not.toHaveBeenCalled();
    respond();
    await pending;
    expect(settled).toHaveBeenCalledOnce();
  });

  it.each([
    { version: 2 }, { kind: 'request' }, { success: 'invalid' },
    { result: null }, { result: { data: null } }, { result: { data: [] } },
  ])('rejects a correlated malformed response: %j', async (response) => {
    const remove = vi.spyOn(window, 'removeEventListener');
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const rejected = expect(pending).rejects.toMatchObject({ kind: 'contract' });
    respond(response);
    await rejected;
    expect(remove).toHaveBeenCalledWith('message', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
  });

  it('accepts the reference host result when optional response metadata is omitted', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    respond({ version: undefined, kind: undefined, success: undefined });
    await expect(pending).resolves.toEqual(daxResult());
  });

  it('rejects an explicit host error even when success is omitted', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const rejected = expect(pending).rejects.toMatchObject({ kind: 'server', message: 'Query failed.' });
    respond({ success: undefined, error: { message: 'Query failed.' } });
    await rejected;
  });

  it('propagates a correlated host error without reading incomplete data', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const rejected = expect(pending).rejects.toMatchObject({ kind: 'server', message: 'Model access denied.' });
    respond({ success: false, error: { message: 'Model access denied.' }, result: undefined });
    await rejected;
  });

  it('uses a safe message for an invalid error object', async () => {
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const rejected = expect(pending).rejects.toMatchObject({ kind: 'server', message: 'Fabric could not execute the semantic-model query.' });
    respond({ success: false, error: '<invalid>' });
    await rejected;
  });

  it('times out, removes its listener, and ignores a late response', async () => {
    const remove = vi.spyOn(window, 'removeEventListener');
    const pending = executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL);
    const rejected = expect(pending).rejects.toMatchObject({ kind: 'network', message: expect.stringContaining('timed out') });
    await vi.advanceTimersByTimeAsync(FABRIC_BRIDGE_TIMEOUT_MS);
    await rejected;
    expect(remove).toHaveBeenCalledWith('message', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
    respond();
  });

  it('cleans up when postMessage throws', async () => {
    parentFrame.postMessage.mockImplementationOnce(() => { throw new Error('Host unavailable'); });
    await expect(executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL)).rejects.toThrow('Host unavailable');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects wildcard/untrusted origins, top-level pages, and malformed model identifiers', async () => {
    await expect(executeDaxViaFabricHost('*', WORKSPACE, MODEL)).rejects.toMatchObject({ kind: 'host' });
    await expect(executeDaxViaFabricHost('https://untrusted.example', WORKSPACE, MODEL)).rejects.toMatchObject({ kind: 'host' });
    await expect(executeDaxViaFabricHost(ORIGIN, WORKSPACE, 'not-a-model-id')).rejects.toMatchObject({ kind: 'contract' });
    vi.stubGlobal('parent', window);
    await expect(executeDaxViaFabricHost(ORIGIN, WORKSPACE, MODEL)).rejects.toMatchObject({ kind: 'host' });
    expect(parentFrame.postMessage).not.toHaveBeenCalled();
  });
});

describe('authenticated native Snapshot loader', () => {
  it('authenticates through the portal before sending DAX to its nested extension frame', async () => {
    const extension = 'https://extension.test';
    vi.stubGlobal('location', { origin: 'https://test-app.example', ancestorOrigins: [extension, ORIGIN] });
    vi.spyOn(document, 'referrer', 'get').mockReturnValue(`${extension}/app-view`);
    let finishSignIn: ((value: { isAuthenticated: boolean }) => void) | undefined;
    sdk.initEmbeddedAuth.mockImplementationOnce(() => new Promise((resolve) => { finishSignIn = resolve; }));
    const pending = createFabricSnapshotLoader(options)(new AbortController().signal);
    await flush();
    expect(parentFrame.postMessage).not.toHaveBeenCalled();
    expect(sdk.initEmbeddedAuth).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ fabricPortalUrl: ORIGIN }));
    finishSignIn?.({ isAuthenticated: true });
    await flush();
    expect(parentFrame.postMessage).toHaveBeenCalledWith(expect.objectContaining({ method: 'semanticModel.executeDaxJson' }), extension);
    respond({}, { origin: ORIGIN });
    respond({ version: undefined, kind: undefined, success: undefined }, { origin: extension });
    await expect(pending).resolves.toEqual(makeSnapshot());
  });

  it('does not query a nested frame if SDK authentication fails', async () => {
    vi.stubGlobal('location', { origin: 'https://test-app.example', ancestorOrigins: ['https://extension.test', ORIGIN] });
    vi.spyOn(document, 'referrer', 'get').mockReturnValue('https://extension.test/app-view');
    sdk.initEmbeddedAuth.mockResolvedValueOnce(null);
    await expect(createFabricSnapshotLoader(options)(new AbortController().signal)).rejects.toMatchObject({ kind: 'auth' });
    expect(parentFrame.postMessage).not.toHaveBeenCalled();
  });

  it('does not reuse an authenticated session after its parent origin changes', async () => {
    const loader = createFabricSnapshotLoader(options);
    const first = loader(new AbortController().signal);
    await flush();
    respond();
    await first;
    vi.spyOn(document, 'referrer', 'get').mockReturnValue('https://app.powerbi.com/groups/test');
    await expect(loader(new AbortController().signal)).rejects.toMatchObject({ kind: 'host' });
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(1);
  });

  it('uses memory-only SDK authentication and reconstructs the validated shared snapshot', async () => {
    const loader = createFabricSnapshotLoader(options);
    const pending = loader(new AbortController().signal);
    await flush();
    expect(sdk.authConstructor).toHaveBeenCalledWith(expect.anything(), { storage: false, persistSession: false, multiTabSync: false });
    expect(sdk.initEmbeddedAuth).toHaveBeenCalledWith(expect.anything(), {
      workspaceId: WORKSPACE, projectId: APP, fabricPortalUrl: ORIGIN,
      returnOrigin: window.location.origin, fabricEmbedded: true,
    });
    respond();
    await expect(pending).resolves.toEqual(makeSnapshot());
  });

  it('coalesces callers and retains the physical host request when a subscriber is aborted', async () => {
    const loader = createFabricSnapshotLoader(options);
    const controller = new AbortController();
    const first = loader(controller.signal);
    const cancelled = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const second = loader(new AbortController().signal);
    await flush();
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(1);
    controller.abort();
    await cancelled;
    const third = loader(new AbortController().signal);
    await flush();
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(1);
    expect(sdk.initEmbeddedAuth).toHaveBeenCalledTimes(1);
    respond();
    await expect(second).resolves.toEqual(makeSnapshot());
    await expect(third).resolves.toEqual(makeSnapshot());
    const fourth = loader(new AbortController().signal);
    await flush();
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(2);
    expect(sdk.initEmbeddedAuth).toHaveBeenCalledTimes(1);
    respond();
    await fourth;
  });

  it('keeps polling single-flight across its 15-second abort and a 30-second host timeout', async () => {
    const loader = createFabricSnapshotLoader(options);
    const { result, unmount } = renderHook(() => useSnapshot(loader));
    await act(flush);
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + POLL_MS); });
    expect(result.current.error?.kind).toBe('network');
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(FABRIC_BRIDGE_TIMEOUT_MS - REQUEST_TIMEOUT_MS); });
    expect(parentFrame.postMessage).toHaveBeenCalledTimes(2);
    await act(async () => { respond(); await flush(); });
    expect(result.current.snapshot?.orders).toHaveLength(6);
    unmount();
  });

  it('rejects pre-aborted callers before authentication or host work', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(createFabricSnapshotLoader(options)(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(sdk.authConstructor).not.toHaveBeenCalled();
    expect(parentFrame.postMessage).not.toHaveBeenCalled();
  });

  it.each([false, 'reject'])('reports failed authentication separately (%s)', async (failure) => {
    if (failure === false) sdk.initEmbeddedAuth.mockResolvedValueOnce({ isAuthenticated: false });
    else sdk.initEmbeddedAuth.mockRejectedValueOnce(new Error('SDK failure'));
    await expect(createFabricSnapshotLoader(options)(new AbortController().signal)).rejects.toMatchObject({ kind: 'auth' });
    expect(parentFrame.postMessage).not.toHaveBeenCalled();
  });

  it.each([
    { apiUrl: 'https://untrusted.example/api' },
    { apiUrl: options.apiUrl.replace(APP, MODEL) },
    { apiUrl: options.apiUrl.replace(WORKSPACE, MODEL) },
    { apiUrl: options.apiUrl.replace('https:', 'http:') },
    { publishableKey: 'not-a-publishable-key' },
  ])('rejects mismatched native endpoint configuration (%j)', async (override) => {
    await expect(createFabricSnapshotLoader({ ...options, ...override })(new AbortController().signal)).rejects.toMatchObject({ kind: 'contract' });
    expect(sdk.authConstructor).not.toHaveBeenCalled();
  });

  it('rejects inconsistent SnapshotId rows and incomplete row counts instead of replacing data', async () => {
    for (const inconsistentId of [true, false]) {
      const loader = createFabricSnapshotLoader(options);
      const pending = loader(new AbortController().signal);
      const rejected = expect(pending).rejects.toMatchObject({ kind: 'contract' });
      await flush();
      const data = daxResult();
      const rows = data.results[0].tables[0].rows;
      if (inconsistentId) rows[1].SnapshotId = 'different-snapshot';
      else rows.pop();
      respond({ result: { data } });
      await rejected;
    }
  });

  it('rejects embedded DAX errors and invalid reconstructed Snapshot shapes', async () => {
    for (const invalidShape of [true, false]) {
      const pending = createFabricSnapshotLoader(options)(new AbortController().signal);
      const rejected = expect(pending).rejects.toMatchObject({ kind: 'contract' });
      await flush();
      const data = daxResult();
      if (invalidShape) {
        const metadata = JSON.parse(data.results[0].tables[0].rows[0].PayloadJson);
        metadata.totals.salesNZD = 'invalid-money';
        data.results[0].tables[0].rows[0].PayloadJson = JSON.stringify(metadata);
        respond({ result: { data } });
      } else respond({ result: { data: { error: { message: 'DAX rejected' } } } });
      await rejected;
    }
  });
});

describe('explicit build transport selection', () => {
  it.each(['development', 'production'])('keeps %s mode on local HTTP', async (mode) => {
    vi.stubEnv('MODE', mode);
    vi.resetModules();
    const loaders = await import('../src/services/snapshotLoader');
    expect(loaders.loadSnapshot).toBe(loaders.loadHttpSnapshot);
  });

  it('selects native only in fabric mode and never falls back to HTTP outside the portal', async () => {
    vi.stubEnv('MODE', 'fabric');
    vi.stubGlobal('parent', window);
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    vi.resetModules();
    const loaders = await import('../src/services/snapshotLoader');
    expect(loaders.loadSnapshot).not.toBe(loaders.loadHttpSnapshot);
    await expect(loaders.loadSnapshot(new AbortController().signal)).rejects.toMatchObject({ kind: 'host' });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
