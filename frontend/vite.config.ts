import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // どのビルドのフロントで動いているかをサーバーのログで確かめるための印（WS接続時に送る）。
  // 開発サーバーは 'dev'、npm run build はビルドした時刻。
  define: {
    __DEF_BUILD__: JSON.stringify(command === 'build' ? new Date().toISOString() : 'dev'),
  },
  // 依存の事前バンドルの置き場所。E2Eの別環境（scripts/e2e_local.py）は node_modules を
  // ジャンクションで共有するため、既定（node_modules/.vite）のままだと、手元で動いている
  // 開発サーバーのキャッシュを作り直してしまう（root が違うとキャッシュを古いとみなす）。
  cacheDir: process.env.DEF_VITE_CACHE_DIR || undefined,
  // ポートとバックエンドの宛先は、E2Eをローカルで別環境に流すとき（scripts/e2e_local.py）だけ
  // 環境変数で変える。普段の開発は既定のまま（3000 → 8511）。
  server: {
    port: Number(process.env.DEF_DEV_PORT) || 3000,
    strictPort: !!process.env.DEF_DEV_PORT,
    proxy: {
      '/api': {
        target: process.env.DEF_API_TARGET || 'http://127.0.0.1:8511',
        changeOrigin: true,
        ws: true,
      },
    },
  },
}))
