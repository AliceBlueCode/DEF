import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // どのビルドのフロントで動いているかをサーバーのログで確かめるための印（WS接続時に送る）。
  // 開発サーバーは 'dev'、npm run build はビルドした時刻。
  define: {
    __DEF_BUILD__: JSON.stringify(command === 'build' ? new Date().toISOString() : 'dev'),
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8511',
        changeOrigin: true,
        ws: true,
      },
    },
  },
}))
