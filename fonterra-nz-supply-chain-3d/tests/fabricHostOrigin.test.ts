import { afterEach, describe, expect, it, vi } from 'vitest';
import { fabricParentOrigin, resolveFabricHost } from '../src/services/fabricHostOrigin';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('Fabric hosting diagnostics', () => {
  it.each(['https://app.fabric.microsoft.com', 'https://app.powerbi.com'])('keeps the verified immediate parent %s working', (origin) => {
    vi.stubGlobal('parent', {});
    vi.stubGlobal('location', { ancestorOrigins: [origin] });
    expect(fabricParentOrigin()).toBe(origin);
  });

  it('resolves the extension separately from the outer Fabric portal', () => {
    vi.stubGlobal('parent', {});
    vi.stubGlobal('location', { ancestorOrigins: ['https://extension.test', 'https://app.fabric.microsoft.com'] });
    expect(resolveFabricHost()).toMatchObject({
      parentOrigin: 'https://extension.test', portalOrigin: 'https://app.fabric.microsoft.com',
    });
  });

  it.each([
    ['https://extension.test', 'https://untrusted.example'],
    ['https://app.fabric.microsoft.com', 'https://untrusted.example'],
    ['https://extension.test', 'https://app.fabric.microsoft.com.attacker.example'],
    ['http://extension.test', 'https://app.fabric.microsoft.com'],
    ['null', 'https://app.fabric.microsoft.com'],
  ])('rejects an untrusted/opaque/insecure enclosing hierarchy: %j', (...ancestors) => {
    vi.stubGlobal('parent', {});
    vi.stubGlobal('location', { ancestorOrigins: ancestors });
    expect(resolveFabricHost).toThrow();
  });

  it('rejects disagreement between native ancestry and the referrer', () => {
    vi.stubGlobal('parent', {});
    vi.stubGlobal('location', { ancestorOrigins: ['https://extension.test', 'https://app.fabric.microsoft.com'] });
    vi.spyOn(document, 'referrer', 'get').mockReturnValue('https://different.example/path');
    expect(resolveFabricHost).toThrow('frame changed');
  });

  it('never exposes referrer paths, query values or fragments in diagnostics', () => {
    vi.stubGlobal('parent', {});
    vi.stubGlobal('location', { ancestorOrigins: [] });
    vi.spyOn(document, 'referrer', 'get').mockReturnValue('https://unverified.example/private/path?token=test-only-secret#private-fragment');
    let failure: unknown;
    try { fabricParentOrigin(); } catch (error) { failure = error; }
    expect(failure).toMatchObject({ kind: 'host', message: expect.stringContaining('Edge or Chrome') });
    expect(failure).not.toMatchObject({ message: expect.stringContaining('test-only-secret') });
    expect(failure).not.toMatchObject({ message: expect.stringContaining('/private/path') });
    expect(failure).not.toMatchObject({ message: expect.stringContaining('private-fragment') });
  });
});
