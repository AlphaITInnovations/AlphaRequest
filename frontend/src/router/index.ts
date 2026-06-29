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

    // ── Ticket Overview ────────────────────────────────────────────────────────
    {
      path: '/tickets',
      component: () => import('@/views/TicketOverviewView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'view' },
    },
    {
      path: '/tickets/new',
      component: () => import('@/views/TicketCreateView.vue'),
      meta: { requiresAuth: true },
    },
    {
      // Kein requiresPermission: 'view' – auch involvierte Nutzer ohne globale
      // view-Rolle dürfen IHRE Tickets öffnen. Der Backend-Endpoint prüft den
      // Zugriff pro Ticket (view/manage/admin oder beteiligt).
      path: '/tickets/overview/:id',
      component: () => import('@/views/TicketOverviewDetailView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Generic ticket routes (new) ────────────────────────────────────────────
    // /tickets/new/:type     → create a ticket of a given type
    // /tickets/view/:type/:id → edit (assignment phase) or fachabteilung view (dept-review phase)
    {
      path: '/tickets/new/:type',
      component: () => import('@/views/tickets/TicketCreateView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/view/:type/:id',
      component: () => import('@/views/tickets/TicketDetailView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Settings ───────────────────────────────────────────────────────────────
    {
      path: '/settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'admin' },
    },

    // ── Backend Down ───────────────────────────────────────────────────────────
    {
      path: '/backend-down',
      component: () => import('@/views/BackendDownView.vue'),
      meta: { requiresAuth: false },
    },

    // ── Catch-all (MUSS GANZ AM ENDE STEHEN) ──────────────────────────────────
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true

  const auth = useAuthStore()

  if (!auth.isLoggedIn && !auth.loading) {
    await auth.fetchMe()
  }

  if (!auth.isLoggedIn) {
    return { path: '/login' }
  }

  const requiredPerm = to.meta.requiresPermission as string | undefined
  if (requiredPerm && !auth.hasPermission(requiredPerm)) {
    return { path: '/dashboard' }
  }

  const requiredType = to.meta.requiresTicketType as string | undefined
  if (requiredType && !auth.canCreateTicket(requiredType as any)) {
    return { path: '/dashboard' }
  }

  return true
})

export default router
