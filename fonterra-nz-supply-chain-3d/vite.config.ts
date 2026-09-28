import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { fabricAuthOriginPlugin } from './build/fabricAuthOrigin';

export default defineConfig(({ mode, command, isPreview }) => {
  if (mode === 'fabric' && command === 'serve' && !isPreview) {
    throw new Error('Fabric mode requires build:fabric, then preview:fabric. Native dev serving would bypass SDK origin hardening.');
  }
  return {
  plugins: [react(), ...(mode === 'fabric' ? [fabricAuthOriginPlugin()] : []), viteSingleFile()],
  build: { target: 'es2022', sourcemap: false, outDir: mode === 'fabric' ? 'dist-fabric' : 'dist' },
  server: {
    host: '127.0.0.1',
    proxy: { '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8787', changeOrigin: false } },
  },
  };
});
