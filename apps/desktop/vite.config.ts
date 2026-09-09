import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron/simple';

const webOnly = process.env.FORGECAD_WEB_ONLY === '1';

export default defineConfig({
  plugins: [
    react(),
    ...(!webOnly ? [electron({
      main: { entry: 'electron/main.ts' },
      preload: { input: 'electron/preload.ts' },
    })] : []),
  ],
  server: {
    host: '127.0.0.1',
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
