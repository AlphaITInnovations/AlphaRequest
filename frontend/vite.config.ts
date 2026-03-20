import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.VITE_BACKEND_URL ?? 'https://ai-ms-01.dom.local:5000'
  const isDev = mode === 'development'

  const httpsConfig = isDev && fs.existsSync('../data/cert/key.pem')
    ? { key: fs.readFileSync('../data/cert/key.pem'), cert: fs.readFileSync('../data/cert/cert.pem') }
    : undefined

  return {
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '0.0.0.0',
      https: httpsConfig,
      hmr: isDev ? { host: 'ai-ms-01.dom.local', port: 5173 } : undefined,
      proxy: {
        '/api':        { target: backendUrl, changeOrigin: true, secure: false },
        '/logout':     { target: backendUrl, changeOrigin: true, secure: false },
        '/start-auth': { target: backendUrl, changeOrigin: true, secure: false },
        '/auth':       { target: backendUrl, changeOrigin: true, secure: false },
        '/static':     { target: backendUrl, changeOrigin: true, secure: false },
      },
    },
  }
})