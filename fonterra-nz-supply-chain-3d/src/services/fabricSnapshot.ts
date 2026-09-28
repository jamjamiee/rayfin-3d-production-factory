import { Auth } from "@microsoft/rayfin-auth";
import { initEmbeddedAuth } from "@microsoft/rayfin-auth-provider-fabric";
import { ApiClient } from "@microsoft/rayfin-lib";
import { reconstructSnapshot, rowsFromDaxResult } from "./snapshotRows";
import { resolveFabricHost, sameFabricHost, type FabricHost } from "./fabricHostOrigin";
import type { SnapshotError } from "./snapshotLoader";

export interface FabricSnapshotOptions<T> {
  workspaceId: string;
  appId: string;
  modelId: string;
  apiUrl: string;
  publishableKey: string;
  parseSnapshot: (value: unknown) => T;
}

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CHANNEL = "fabric-app-data-semantic-model";
export const FABRIC_BRIDGE_TIMEOUT_MS = 30_000;

class FabricSnapshotError extends Error {
  constructor(readonly kind: SnapshotError["kind"], message: string) {
    super(message);
    this.name = "FabricSnapshotError";
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function executeDaxViaFabricHost(origin: string, workspaceId: string, modelId: string): Promise<unknown> {
  let host: FabricHost;
  try { host = resolveFabricHost(); }
  catch (error) { return Promise.reject(error); }
  if (origin !== host.parentOrigin) {
    return Promise.reject(new FabricSnapshotError("host", "The Fabric frame changed. Reload the app from its workspace."));
  }
  if (![workspaceId, modelId].every((id) => GUID.test(id))) {
    return Promise.reject(new FabricSnapshotError("contract", "The Fabric workspace and semantic-model identifiers are invalid."));
  }
  const parentFrame = host.parentFrame;
  return new Promise((resolve, reject) => {
    const requestId = crypto.randomUUID();
    const cleanup = () => {
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
    };
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== parentFrame || event.origin !== origin || !object(event.data)) return;
      const response = event.data;
      if (response.requestId !== requestId || response.channel !== CHANNEL) return;
      cleanup();
      try {
        if (!sameFabricHost(host, resolveFabricHost())) {
          throw new FabricSnapshotError("host", "The Fabric frame changed during the query. Reload the app.");
        }
      } catch (error) { reject(error); return; }
      if ((response.version !== undefined && response.version !== 1)
          || (response.kind !== undefined && response.kind !== "response")
          || (response.success !== undefined && typeof response.success !== "boolean")) {
        reject(new FabricSnapshotError("contract", "Fabric returned an unsupported semantic-model bridge response."));
      } else if (response.success === false || response.error != null) {
        const message = object(response.error) && typeof response.error.message === "string"
          ? response.error.message : "Fabric could not execute the semantic-model query.";
        reject(new FabricSnapshotError("server", message));
      } else if (object(response.result) && object(response.result.data)) {
        resolve(response.result.data);
      } else {
        reject(new FabricSnapshotError("contract", "Fabric returned an incomplete semantic-model result."));
      }
    };
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new FabricSnapshotError("network", "Fabric's semantic-model bridge timed out. Confirm the app is open in Fabric and model access is enabled."));
    }, FABRIC_BRIDGE_TIMEOUT_MS);
    window.addEventListener("message", onMessage);
    try {
      // The semantic-model protocol requires an outer method field; the generic SDK
      // sendBridgeRequest helper cannot encode this request (Microsoft's data-app template).
      parentFrame.postMessage({
        channel: CHANNEL, version: 1, kind: "request",
        method: "semanticModel.executeDaxJson", requestId,
        payload: { workspaceId, modelId, query: "EVALUATE FactorySnapshotRows" },
      }, origin);
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}

function waitForSnapshot<T>(pending: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(new DOMException("Snapshot request cancelled.", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    pending.then(
      (snapshot) => { signal.removeEventListener("abort", onAbort); if (!signal.aborted) resolve(snapshot); },
      (error) => { signal.removeEventListener("abort", onAbort); reject(error); },
    );
    if (signal.aborted) onAbort();
  });
}

export function createFabricSnapshotLoader<T>(options: FabricSnapshotOptions<T>): (signal: AbortSignal) => Promise<T> {
  let auth: Auth | undefined;
  let initialized = false;
  let authenticatedHost: FabricHost | undefined;
  let pending: Promise<T> | undefined;

  async function query(): Promise<T> {
    const host = resolveFabricHost();
    if (authenticatedHost && !sameFabricHost(authenticatedHost, host)) {
      throw new FabricSnapshotError("host", "The Fabric frame changed after sign-in. Reload the app from its workspace.");
    }
    if (![options.workspaceId, options.appId, options.modelId].every((id) => GUID.test(id))) {
      throw new FabricSnapshotError("contract", "The new app's Fabric workspace, app and semantic-model identifiers must be configured.");
    }
    let apiUrl: URL;
    try { apiUrl = new URL(options.apiUrl); }
    catch { throw new FabricSnapshotError("contract", "The configured Rayfin endpoint is invalid."); }
    if (apiUrl.protocol !== "https:" || !apiUrl.hostname.endsWith(".pbidedicated.windows.net")
        || apiUrl.username || apiUrl.password || apiUrl.search || apiUrl.hash
        || !apiUrl.pathname.endsWith(`/workspaces/${options.workspaceId}/appbackends/${options.appId}/`)
        || !options.publishableKey.startsWith("pk-")) {
      throw new FabricSnapshotError("contract", "The configured Rayfin endpoint does not match this new app.");
    }
    auth ??= new Auth(new ApiClient({ baseUrl: options.apiUrl, publishableKey: options.publishableKey }), {
      storage: false, persistSession: false, multiTabSync: false,
    });
    if (!initialized || !auth.getSession().isAuthenticated) {
      let session;
      try {
        session = await initEmbeddedAuth(auth, {
          workspaceId: options.workspaceId, projectId: options.appId, fabricPortalUrl: host.portalOrigin,
          returnOrigin: window.location.origin, fabricEmbedded: true,
        });
      } catch {
        throw new FabricSnapshotError("auth", "Fabric sign-in failed. Reopen the app from its workspace and confirm access.");
      }
      if (!session?.isAuthenticated) throw new FabricSnapshotError("auth", "Fabric sign-in did not establish an authenticated app session.");
      if (!sameFabricHost(host, resolveFabricHost())) {
        throw new FabricSnapshotError("host", "The Fabric frame changed during sign-in. Reload the app.");
      }
      authenticatedHost = host;
      initialized = true;
    }
    const result = await executeDaxViaFabricHost(host.parentOrigin, options.workspaceId, options.modelId);
    try { return options.parseSnapshot(reconstructSnapshot(rowsFromDaxResult(result))); }
    catch (error) {
      const message = object(error) && typeof error.message === "string" ? error.message : "Fabric returned an invalid snapshot.";
      throw new FabricSnapshotError("contract", message);
    }
  }

  return async (signal: AbortSignal): Promise<T> => {
    if (signal.aborted) throw new DOMException("Snapshot request cancelled.", "AbortError");
    // The host has no query-cancellation transport; retain the promise to prevent overlap.
    pending ??= query().finally(() => { pending = undefined; });
    return waitForSnapshot(pending, signal);
  };
}
