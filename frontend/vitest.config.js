import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The React plugin is applied to BOTH the app and the test transforms, so a
// .jsx test file compiles with the automatic JSX runtime exactly like the app.
export default defineConfig({
  plugins: [react()],
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.{js,jsx}'],
  },
});
