import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { setupInterceptors, checkBackendHealth } from '@/api/client'
import './style.css'

const pinia = createPinia()
const app   = createApp(App)

app.use(pinia)
app.use(router)
setupInterceptors(router)

// ── Selbstheilung nach Deploys ──────────────────────────────────────────────
// Jede View/jedes Formular ist ein eigener, gehashter Lazy-Chunk. Nach einem
// neuen Build existieren die alten Hashes nicht mehr; ein offener Tab, der dann
// einen alten Chunk nachladen will, bekommt vom Server die index.html
// (text/html) statt JavaScript → "Failed to fetch dynamically imported module".
// In dem Fall einmalig neu laden, damit der Browser die frische index.html mit
// den neuen Chunk-Hashes holt. sessionStorage-Guard verhindert Reload-Schleifen,
// falls ein Chunk dauerhaft fehlt (kaputter Deploy).
function reloadOnceForStaleChunk() {
  const KEY = 'chunk-reload-ts'
  const last = Number(sessionStorage.getItem(KEY) || '0')
  if (Date.now() - last < 10_000) return
  sessionStorage.setItem(KEY, String(Date.now()))
  window.location.reload()
}

window.addEventListener('vite:preloadError', reloadOnceForStaleChunk)
router.onError((err) => {
  if (/dynamically imported module|module script failed|Failed to fetch/i.test(String(err?.message))) {
    reloadOnceForStaleChunk()
  }
})

// App sofort mounten – Vue rendert, bevor der Check fertig ist
app.mount('#app')

// Health-Check danach – navigiert bei Bedarf auf /backend-down
checkBackendHealth().then(ok => {
  if (!ok) {
    router.replace('/backend-down')
  }

  // Guard für alle weiteren Navigationen
  router.beforeEach((to) => {
    if (!ok && to.path !== '/backend-down') {
      return { path: '/backend-down' }
    }
    if (ok && to.path === '/backend-down') {
      return { path: '/' }
    }
  })
})