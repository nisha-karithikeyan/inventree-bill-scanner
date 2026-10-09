/// <reference types="vitest" />
import { defineConfig } from 'vite';
import { viteExternalsPlugin } from 'vite-plugin-externals';

// InvenTree exposes these as window globals for plugins (see src/frontend/src/main.tsx).
// Using them instead of bundling copies keeps the React context shared.
const externals = {
  react: 'React',
  'react-dom': 'ReactDOM',
  '@mantine/core': 'MantineCore',
  '@mantine/notifications': 'MantineNotifications'
};

export default defineConfig(({ mode }) => ({
  plugins: mode === 'test' ? [] : [viteExternalsPlugin(externals)],
  esbuild: {
    jsx: 'transform',
    jsxFactory: 'React.createElement',
    jsxFragment: 'React.Fragment'
  },
  build: {
    outDir: '../bill_scanner/static',
    emptyOutDir: true,
    sourcemap: true,
    lib: {
      entry: 'src/BillScanner.tsx',
      formats: ['es'],
      fileName: () => 'BillScanner.js'
    },
    rollupOptions: { external: Object.keys(externals) }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['tests/setup.ts']
  }
}));
