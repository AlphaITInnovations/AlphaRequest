import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/login',
      component: () => import('@/views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/new/zugang-beantragen',
      component: () => import('@/views/tickets/ZugangCreateView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/edit/zugang-beantragen/:id',
      component: () => import('@/views/tickets/ZugangEditView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/:type/:id',
      component: () => import('@/views/tickets/ZugangViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
  ],
})

// Navigation Guard – läuft vor jeder Seitennavigation
router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true

  const auth = useAuthStore()

  // Noch nicht geladen → einmal abrufen
  if (!auth.isLoggedIn && !auth.loading) {
    await auth.fetchMe()
  }

  // Nicht eingeloggt → Vue Login-Seite
  if (!auth.isLoggedIn) {
    return { path: '/login' }
  }

  // Admin-Route aber kein Admin
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/dashboard' }
  }

  return true
})

export default router