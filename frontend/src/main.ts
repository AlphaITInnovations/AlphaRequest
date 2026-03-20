import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import { setupInterceptors } from './api/client'
import App from './App.vue'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

setupInterceptors(router)

app.mount('#app')