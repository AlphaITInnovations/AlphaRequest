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
      // Startseite = Dashboard: „was liegt bei MIR an?" (drei Arbeitslisten,
      // bewusst ohne Filterleiste). Das Suchen und Filtern über ALLE Aufträge ist
      // die Aufgabe der Übersicht – zwei Ansichten mit derselben Filterleiste
      // hatten sich gegenseitig die Aussage genommen.
      path: '/dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      // Übersicht: alle Aufträge mit Suche, Filtern und Blätterung.
      path: '/auftraege',
      component: () => import('@/views/OverviewView.vue'),
      meta: { requiresAuth: true },
    },

    // ── Settings ───────────────────────────────────────────────────────────────
    {
      path: '/settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'admin' },
    },

    // ── Prozess-Definitionen ───────────────────────────────────────────────────
    // Editor: nur Admin (die Definitions-Endpunkte sind ebenfalls admin-gated).
    {
      path: '/prozesse/:key/:version',
      component: () => import('@/views/ProcessEditorView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'admin' },
    },

    // ── Prozess-Aufträge ───────────────────────────────────────────────────────
    // Für ALLE Angemeldeten erreichbar. Kein `requiresPermission` – wer was
    // sehen und tun darf, entscheidet der Server pro Auftrag (Aufsicht ·
    // Ersteller:in · Zuständige · Beobachter:innen) und liefert es als
    // `abilities`/`visible_fields` mit. Ein Rechte-Gate an der Route wäre hier
    // falsch: es würde Beteiligte aussperren, die kein Admin sind.
    {
      // Alter Pfad der Auftragsliste → Übersicht. Weiterleitung statt Löschung,
      // damit vorhandene Lesezeichen nicht ins Leere laufen. Greift NUR für den
      // genauen Pfad – die Unterpfade (/neu, /:id) bleiben.
      path: '/prozess-auftraege',
      redirect: '/auftraege',
    },
    {
      // Katalog der veröffentlichten Prozesse („Neues Prozess-Ticket"). Das
      // Basis-Ticket fehlt hier als Kachel – es hat mit „Neues Ticket" einen
      // eigenen Einstieg direkt auf /prozess-auftraege/neu/basis-ticket
      // (lib/basisTicket.ts). Ohne Rechte-Gate: der Katalog zeigt jedem, was es
      // gibt, und markiert deaktiviert, was diese Person nicht anlegen darf
      // (may_create).
      path: '/prozess-auftraege/neu',
      component: () => import('@/views/ProcessCatalogView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/prozess-auftraege/neu/:key',
      component: () => import('@/views/processes/ProcessTicketCreateView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/prozess-auftraege/:id',
      component: () => import('@/views/processes/ProcessTicketDetailView.vue'),
      meta: { requiresAuth: true },
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

  return true
})

export default router
