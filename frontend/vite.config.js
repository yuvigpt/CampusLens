import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// `strictPort` keeps the dev server on 5173. The backend's CORS allow-list only
// contains http://localhost:5173 and http://127.0.0.1:5173, so silently moving
// to 5174 would break every request - better to fail loudly instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: true,
  },
  preview: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
