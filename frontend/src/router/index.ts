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
      path: '/tickets/overview/:id',
      component: () => import('@/views/TicketOverviewDetailView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'view' },
    },

    // ── Fachabteilung Views (pro Ticket-Typ) ──────────────────────────────────
    {
      path: '/tickets/group/zugang-beantragen/:id',
      component: () => import('@/views/tickets/ZugangBeantragenViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/hardware/:id',
      component: () => import('@/views/tickets/HardwareViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/zugang-sperren/:id',
      component: () => import('@/views/tickets/ZugangSperrenViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/niederlassung-anmelden/:id',
      component: () => import('@/views/tickets/NiederlassungAnmeldenViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/niederlassung-umzug/:id',
      component: () => import('@/views/tickets/NiederlassungUmzugViewView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/niederlassung-schliessen/:id',
      component: () => import('@/views/tickets/NiederlassungSchliessenViewView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Zugang beantragen ──────────────────────────────────────────────────────
    {
      path: '/tickets/new/zugang-beantragen',
      component: () => import('@/views/tickets/ZugangBeantragenCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'zugang-beantragen' },
    },
    {
      path: '/tickets/edit/zugang-beantragen/:id',
      component: () => import('@/views/tickets/ZugangBeantragenEditView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/tickets/group/zugang-beantragen/:id',
      component: () => import('@/views/tickets/ZugangBeantragenViewView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Hardware ───────────────────────────────────────────────────────────────
    {
      path: '/tickets/new/hardware',
      component: () => import('@/views/tickets/HardwareCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'hardware' },
    },
    {
      path: '/tickets/edit/hardware/:id',
      component: () => import('@/views/tickets/HardwareEditView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Zugang sperren ─────────────────────────────────────────────────────────
    {
      path: '/tickets/new/zugang-sperren',
      component: () => import('@/views/tickets/ZugangSperrenCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'zugang-sperren' },
    },
    {
      path: '/tickets/edit/zugang-sperren/:id',
      component: () => import('@/views/tickets/ZugangSperrenEditView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Niederlassung anmelden ─────────────────────────────────────────────────
    {
      path: '/tickets/new/niederlassung-anmelden',
      component: () => import('@/views/tickets/NiederlassungAnmeldenCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'niederlassung-anmelden' },
    },
    {
      path: '/tickets/edit/niederlassung-anmelden/:id',
      component: () => import('@/views/tickets/NiederlassungAnmeldenEditView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Niederlassung Umzug ────────────────────────────────────────────────────
    {
      path: '/tickets/new/niederlassung-umzug',
      component: () => import('@/views/tickets/NiederlassungUmzugCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'niederlassung-umzug' },
    },
    {
      path: '/tickets/edit/niederlassung-umzug/:id',
      component: () => import('@/views/tickets/NiederlassungUmzugEditView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Niederlassung schließen ────────────────────────────────────────────────
    {
      path: '/tickets/new/niederlassung-schliessen',
      component: () => import('@/views/tickets/NiederlassungSchliessenCreateView.vue'),
      meta: { requiresAuth: true, requiresTicketType: 'niederlassung-schliessen' },
    },
    {
      path: '/tickets/edit/niederlassung-schliessen/:id',
      component: () => import('@/views/tickets/NiederlassungSchliessenEditView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Settings ───────────────────────────────────────────────────────────────
    {
      path: '/settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'admin' },
    },

    // ── Catch-all ──────────────────────────────────────────────────────────────
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

  // Permission-Check (view, manage, admin)
  const requiredPerm = to.meta.requiresPermission as string | undefined
  if (requiredPerm && !auth.hasPermission(requiredPerm)) {
    return { path: '/dashboard' }
  }

  // Ticket-Type-Check (create_*)
  const requiredType = to.meta.requiresTicketType as string | undefined
  if (requiredType && !auth.canCreateTicket(requiredType as any)) {
    return { path: '/dashboard' }
  }

  return true
})

export default router