import { resolve } from 'node:path';
import { normalizePath, type Plugin } from 'vite';

const SDK_TRANSPORT = '/node_modules/@microsoft/rayfin-auth-provider-fabric/dist/PostMessageAuthTransport.js';
const CALL_TARGET = 'target: window.parent,';

export function hardenFabricAuthTransport(code: string, originModule: string): string {
  if (code.split(CALL_TARGET).length !== 2 || code.includes('targetOrigin:')) {
    throw new Error('Pinned Rayfin 1.35.0 auth transport changed. Review exact-origin hardening before building.');
  }
  return `import { fabricParentOrigin as pinnedFabricParentOrigin } from ${JSON.stringify(originModule)};\n` +
    code.replace(CALL_TARGET, `${CALL_TARGET}\n        targetOrigin: pinnedFabricParentOrigin(),`);
}

export function fabricAuthOriginPlugin(): Plugin {
  let hardened = false;
  let originModule = '';
  return {
    name: 'fonterra-exact-fabric-auth-origin',
    enforce: 'pre',
    apply: 'build',
    configResolved(config) { originModule = normalizePath(resolve(config.root, 'src/services/fabricHostOrigin.ts')); },
    transform(code, id) {
      if (!normalizePath(id).endsWith(SDK_TRANSPORT)) return null;
      hardened = true;
      return { code: hardenFabricAuthTransport(code, originModule), map: null };
    },
    buildEnd(error) {
      if (!error && !hardened) this.error('The pinned Fabric auth transport was not hardened. Refusing a native build.');
    },
  };
}
