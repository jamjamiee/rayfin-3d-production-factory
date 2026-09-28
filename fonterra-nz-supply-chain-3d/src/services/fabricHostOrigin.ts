const PORTAL_ORIGINS = new Set(['https://app.fabric.microsoft.com', 'https://app.powerbi.com']);

export interface FabricHost {
  parentFrame: Window;
  parentOrigin: string;
  portalOrigin: string;
}

function rejectOrigin(message: string): never {
  throw Object.assign(new Error(message), { kind: 'host' });
}

function httpsOrigin(value: string): string {
  let url: URL;
  try { url = new URL(value); }
  catch { return rejectOrigin('The Fabric frame identity is unavailable. Reopen the app from its workspace.'); }
  if (url.protocol !== 'https:') rejectOrigin('Open this app inside the secure Fabric portal.');
  return url.origin;
}

export function resolveFabricHost(): FabricHost {
  if (window.parent === window) {
    rejectOrigin('Open this app inside the Fabric portal to use its authenticated data connection. A separate Rayfin account is not required.');
  }
  const ancestors = Array.from(window.location.ancestorOrigins ?? []);
  if (ancestors.length) {
    const origins = ancestors.map(httpsOrigin);
    const parentOrigin = origins[0];
    const portalOrigin = origins[origins.length - 1];
    if (!PORTAL_ORIGINS.has(portalOrigin)) rejectOrigin('Open this app from its workspace in the Fabric portal.');
    if (document.referrer && httpsOrigin(document.referrer) !== parentOrigin) {
      rejectOrigin('The Fabric frame changed. Reload the app from its workspace.');
    }
    // Fabric hosts the app below an extension frame. The browser supplies this
    // ancestry; the SDK must still establish a PKCE-backed session before DAX.
    return { parentFrame: window.parent, parentOrigin, portalOrigin };
  }
  if (!document.referrer) rejectOrigin('Fabric frame identity is unavailable. Open the app in Microsoft Edge or Chrome through Fabric.');
  const origin = httpsOrigin(document.referrer);
  if (!PORTAL_ORIGINS.has(origin)) {
    rejectOrigin('This browser cannot verify the nested Fabric frame. Open the app in Microsoft Edge or Chrome through Fabric.');
  }
  return { parentFrame: window.parent, parentOrigin: origin, portalOrigin: origin };
}

export const fabricParentOrigin = () => resolveFabricHost().parentOrigin;

export const sameFabricHost = (left: FabricHost, right: FabricHost) =>
  left.parentFrame === right.parentFrame && left.parentOrigin === right.parentOrigin && left.portalOrigin === right.portalOrigin;
