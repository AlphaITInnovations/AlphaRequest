<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'

const { showToast } = useToast()

interface ApprovalInfo {
  active: boolean
  keySource: 'db' | 'file'
  publicKey: string
  baseUrl: string
  issuer: string
  audience: string
  hasApiKey: boolean
  maxPickupDelay: number
  canRegenerate: boolean
}
interface Probe { ok: boolean; status?: number | null; latencyMs?: number | null; error?: string | null }
interface TestResult { baseUrl: string; health: Probe; auth: Probe }

const loading = ref(true)
const info = ref<ApprovalInfo | null>(null)
const testing = ref(false)
const test = ref<TestResult | null>(null)
const rotating = ref(false)

const envLine = computed(() =>
  info.value ? `APPROVE_PUBLIC_KEY=${info.value.publicKey}` : '')

async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/settings/approval')
    info.value = data.data
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message ?? e?.response?.data?.detail ?? 'Laden fehlgeschlagen', false)
  } finally {
    loading.value = false
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(envLine.value)
    showToast('In die Zwischenablage kopiert')
  } catch {
    showToast('Kopieren nicht möglich', false)
  }
}

async function runTest() {
  testing.value = true
  test.value = null
  try {
    const { data } = await client.post('/settings/approval/test')
    test.value = data.data
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message ?? e?.response?.data?.detail ?? 'Test fehlgeschlagen', false)
  } finally {
    testing.value = false
  }
}

async function rotateKey() {
  if (!confirm('Neuen Signierschlüssel erzeugen?\n\nAlle bereits verschickten Freigabe-Links werden damit ungültig. '
    + 'Danach den neuen Public Key in AlphaApprove hinterlegen.')) return
  rotating.value = true
  try {
    const { data } = await client.post('/settings/approval/regenerate-key')
    if (info.value) info.value.publicKey = data.data.publicKey
    test.value = null
    showToast('Neuer Schlüssel erzeugt – Public Key in AlphaApprove aktualisieren')
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message ?? e?.response?.data?.detail ?? 'Rotation fehlgeschlagen', false)
  } finally {
    rotating.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <h2 class="section-title">Externe Freigabe (AlphaApprove)</h2>

    <div v-if="loading" class="card-section text-sm text-gray-500">Lädt…</div>

    <div v-else-if="info" class="space-y-6">
      <!-- Status -->
      <div class="card-section space-y-3">
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-200">Externer Weg</span>
          <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                :class="info.active
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                  : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'">
            {{ info.active ? 'aktiv' : 'nicht konfiguriert' }}
          </span>
        </div>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Ist der externe Weg aktiv, enthalten Freigabe-Mails Links auf AlphaApprove; sonst
          die internen Links (nur im Intranet). Der Schalter greift, sobald Basis-URL, API-Key,
          Issuer und Audience gesetzt sind.
        </p>
        <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Basis-URL</dt>
            <dd class="font-mono text-xs text-right break-all">{{ info.baseUrl || '—' }}</dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">API-Key</dt>
            <dd>
              <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="info.hasApiKey
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                      : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'">
                {{ info.hasApiKey ? 'gesetzt' : 'fehlt' }}
              </span>
            </dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Issuer</dt>
            <dd class="font-mono text-xs text-right break-all">{{ info.issuer || '—' }}</dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Audience</dt>
            <dd class="font-mono text-xs text-right break-all">{{ info.audience || '—' }}</dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Abhol-Fenster</dt>
            <dd class="font-mono text-xs">{{ info.maxPickupDelay }} s</dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Schlüssel-Quelle</dt>
            <dd class="font-mono text-xs">{{ info.keySource === 'file' ? 'Datei (Override)' : 'Datenbank' }}</dd>
          </div>
        </dl>
      </div>

      <!-- Public Key -->
      <div class="card-section space-y-3">
        <label class="lbl">Public Key für AlphaApprove</label>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Diese Zeile auf der AlphaApprove-VM hinterlegen (<code class="font-mono text-xs">/etc/alphaapprove/alphaapprove.env</code>).
          Nur der <strong>Public</strong> Key verlässt das interne System – der private Signierschlüssel bleibt hier.
        </p>
        <div class="flex items-start gap-2">
          <code class="flex-1 font-mono text-xs break-all rounded-xl border border-gray-200 dark:border-white/10
                       bg-gray-50 dark:bg-[#263040] px-3.5 py-2.5 text-gray-800 dark:text-gray-100">{{ envLine }}</code>
          <button @click="copyKey" class="btn-secondary flex-shrink-0">Kopieren</button>
        </div>
      </div>

      <!-- Verbindungstest -->
      <div class="card-section space-y-4">
        <div class="flex items-center justify-between gap-3">
          <label class="lbl mb-0">Verbindungstest</label>
          <button @click="runTest" :disabled="testing" class="btn-primary disabled:opacity-60">
            {{ testing ? 'Prüft…' : 'Verbindung testen' }}
          </button>
        </div>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Prüft vom Server aus die Erreichbarkeit von <code class="font-mono text-xs">/health</code> und den API-Key
          gegen <code class="font-mono text-xs">/pending</code> (liest nur, verbraucht nichts).
        </p>
        <div v-if="test" class="space-y-2">
          <div class="flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
               :class="test.health.ok
                 ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
                 : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
            <span>/health erreichbar</span>
            <span class="font-mono text-xs">
              {{ test.health.ok ? '✓' : '✗' }}
              <template v-if="test.health.status"> · HTTP {{ test.health.status }}</template>
              <template v-if="test.health.latencyMs != null"> · {{ test.health.latencyMs }} ms</template>
            </span>
          </div>
          <p v-if="test.health.error" class="text-xs text-red-600 dark:text-red-300 break-all px-1">{{ test.health.error }}</p>

          <div class="flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
               :class="test.auth.ok
                 ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
                 : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
            <span>API-Key akzeptiert (/pending)</span>
            <span class="font-mono text-xs">
              {{ test.auth.ok ? '✓' : '✗' }}
              <template v-if="test.auth.status"> · HTTP {{ test.auth.status }}</template>
              <template v-if="test.auth.latencyMs != null"> · {{ test.auth.latencyMs }} ms</template>
            </span>
          </div>
          <p v-if="test.auth.error" class="text-xs text-red-600 dark:text-red-300 break-all px-1">{{ test.auth.error }}</p>
        </div>
      </div>

      <!-- Rotation -->
      <div class="card-section space-y-3">
        <label class="lbl">Schlüssel neu erzeugen</label>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Erzeugt ein neues Schlüsselpaar. <strong>Alle bereits verschickten Freigabe-Links werden ungültig</strong>,
          und der neue Public Key muss in AlphaApprove hinterlegt werden.
        </p>
        <button v-if="info.canRegenerate" @click="rotateKey" :disabled="rotating"
                class="px-4 py-2 rounded-xl text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-60">
          {{ rotating ? 'Erzeugt…' : 'Neuen Schlüssel erzeugen' }}
        </button>
        <p v-else class="text-xs text-gray-500 dark:text-gray-400">
          Der Schlüssel kommt aus einer Datei (<code class="font-mono">APPROVAL_PRIVATE_KEY_PATH</code>) – Rotation dort vornehmen.
        </p>
      </div>
    </div>
  </section>
</template>
