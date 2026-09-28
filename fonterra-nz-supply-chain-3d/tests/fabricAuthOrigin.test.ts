// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { hardenFabricAuthTransport } from '../build/fabricAuthOrigin';

describe('pinned SDK authentication origin hardening', () => {
  it('adds an exact parent origin to the installed 1.35.0 SDK handoff without changing its protocol', () => {
    const original = readFileSync('node_modules\\@microsoft\\rayfin-auth-provider-fabric\\dist\\PostMessageAuthTransport.js', 'utf8');
    const hardened = hardenFabricAuthTransport(original, '/src/services/fabricHostOrigin.ts');
    expect(hardened).toContain('targetOrigin: pinnedFabricParentOrigin(),');
    expect(hardened).toContain("channel: 'fabric-auth'");
    expect(hardened).toContain("kind: 'auth.requestHandoff'");
    expect(hardened).not.toContain("targetOrigin: '*'");
    expect(hardened).not.toContain('targetOrigin: "*"');
  });

  it('executes the hardened SDK handoff with the exact origin and unchanged PKCE payload', async () => {
    const original = readFileSync('node_modules\\@microsoft\\rayfin-auth-provider-fabric\\dist\\PostMessageAuthTransport.js', 'utf8');
    const hardened = hardenFabricAuthTransport(original, '/src/services/fabricHostOrigin.ts')
      .replace(/^import[\s\S]*?;\r?\n/gm, '')
      .replace('export function requestHandoff', 'function requestHandoff');
    const sendBridgeRequest = vi.fn().mockResolvedValue({ handoffCode: 'test-only', state: 'test-state' });
    const parent = {};
    const requestHandoff = new Function('sendBridgeRequest', 'BridgeError', 'AuthError', 'window', 'pinnedFabricParentOrigin',
      `${hardened}\nreturn requestHandoff;`)(sendBridgeRequest, Error, Error, { parent }, () => 'https://app.fabric.microsoft.com');
    await requestHandoff({ callbackUrl: 'https://app.example', codeChallenge: 'test-challenge', codeChallengeMethod: 'S256', state: 'test-state', timeoutMs: 30000 });
    expect(sendBridgeRequest).toHaveBeenCalledWith({
      target: parent, targetOrigin: 'https://app.fabric.microsoft.com', channel: 'fabric-auth', kind: 'auth.requestHandoff',
      payload: { callbackUrl: 'https://app.example', codeChallenge: 'test-challenge', codeChallengeMethod: 'S256', state: 'test-state' },
      timeoutMs: 30000,
    });
  });

  it.each([
    'sendBridgeRequest({ target: window.top });',
    'target: window.parent,\ntarget: window.parent,',
    'target: window.parent,\ntargetOrigin: "*",',
  ])('fails closed when SDK source no longer matches the pinned transport', (source) => {
    expect(() => hardenFabricAuthTransport(source, '/src/services/fabricHostOrigin.ts')).toThrow('auth transport changed');
  });
});
