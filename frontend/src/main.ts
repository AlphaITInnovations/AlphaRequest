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