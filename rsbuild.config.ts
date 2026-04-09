import { defineConfig } from '@rsbuild/core';
import { pluginVue } from '@rsbuild/plugin-vue';

import { resolveApiProxyTarget } from './src/lib/dev-proxy';

export default defineConfig({
  plugins: [pluginVue()],
  html: {
    title: 'Architecture Workbench',
    template: './index.html'
  },
  source: {
    entry: {
      index: './src/main.ts'
    }
  },
  server: {
    proxy: {
      '/api': {
        target: resolveApiProxyTarget(),
        changeOrigin: true
      }
    }
  }
});
