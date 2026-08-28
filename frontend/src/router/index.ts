import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import type { Permission } from '@/types/api'

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
      // Persönliches Archiv: alle Aufträge, an denen man je beteiligt war (jeder
      // Status). Für ALLE – kein Rechte-Gate: der Server entscheidet je Auftrag,
      // was sichtbar ist (may_view / archive_involved), und die Liste trägt keine
      // Feldwerte.
      path: '/archiv',
      component: () => import('@/views/ArchiveView.vue'),
      meta: { requiresAuth: true },
    },
    {
      // Übersicht: alle Aufträge mit Suche, Filtern und Blätterung. NUR für die
      // Aufsichts-Rollen (Alt-System-Regel): viewer liest, manager darf
      // zusätzlich archivieren, admin alles. Alle anderen arbeiten über die
      // Startseite (/dashboard). Das Gate hier ist Komfort – die Daten schützt
      // der Server ohnehin pro Auftrag (may_view), die Liste zeigte einem
      // normalen User nie mehr als seine eigenen.
      path: '/auftraege',
      component: () => import('@/views/OverviewView.vue'),
      meta: { requiresAuth: true, requiresPermission: ['view', 'manage', 'admin'] },
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
      // Bestätigungsseite aus der Lösch-Mail. Admin-gated: der Link ist der ZWEITE
      // Kanal, nicht die Berechtigung – eine weitergeleitete Mail darf keinen
      // Prozess samt Aufträgen löschen können. Steht VOR /prozesse/:key/:version,
      // sonst würde „loeschen" als Prozess-Key gelesen.
      path: '/prozesse/loeschen',
      component: () => import('@/views/ProcessDeleteConfirmView.vue'),
      meta: { requiresAuth: true, requiresPermission: 'admin' },
    },
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
      // Das Basis-Ticket („Neues Ticket") hat ein EIGENES, festes Formular im
      // Layout des Alt-Systems – nicht das generische, aus der Definition
      // gerenderte. Statische Route vor der :key-Route.
      path: '/prozess-auftraege/neu/basis-ticket',
      component: () => import('@/views/processes/BasisTicketCreateView.vue'),
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

  // Einzelne Berechtigung ODER Liste („eine davon genügt").
  const requiredPerm = to.meta.requiresPermission as Permission | Permission[] | undefined
  if (requiredPerm) {
    const erlaubt = Array.isArray(requiredPerm)
      ? requiredPerm.some((p) => auth.hasPermission(p))
      : auth.hasPermission(requiredPerm)
    if (!erlaubt) return { path: '/dashboard' }
  }

  return true
})

export default router
