import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'

function proxyWithFallback(target: string) {
  return {
    target,
    changeOrigin: true,
    secure: false,
    configure: (proxy: any) => {
      proxy.on('error', (_err: Error, _req: IncomingMessage, res: ServerResponse) => {
        res.writeHead(503, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ detail: 'Backend not reachable' }))
      })
    },
  }
}

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
        '/api':        proxyWithFallback(backendUrl),
        '/logout':     proxyWithFallback(backendUrl),
        '/start-auth': proxyWithFallback(backendUrl),
        '/auth':       proxyWithFallback(backendUrl),
        '/static':     proxyWithFallback(backendUrl),
      },
    },
  }
})