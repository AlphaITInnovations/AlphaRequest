<script setup lang="ts">
/**
 * Wartungsmodus verwalten.
 *
 * Ist er aktiv, dürfen sich nur noch Admins anmelden; normale Konten werden am
 * Login abgewiesen (Durchsetzung im Backend, api/v1/auth.auth_callback). Der
 * Hinweistext und das geplante Ende werden ausschließlich auf dem Login-
 * Bildschirm angezeigt. Der Modus endet NIE von selbst – er muss hier bewusst
 * wieder beendet werden (so bleibt die Sperre, falls sich die Wartung hinzieht).
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'

const { showToast } = useToast()

interface Maintenance {
  active: boolean
  message: string | null
  planned_end: string | null
  since: string | null
  by: string | null
}

const loading = ref(true)
const saving = ref(false)
const current = ref<Maintenance | null>(null)

const form = reactive({ active: false, message: '', plannedEnd: '' })

const dirty = computed(() =>
  !!current.value && (
    form.active !== current.value.active ||
    (form.message || '') !== (current.value.message || '') ||
    (form.plannedEnd || '') !== (current.value.planned_end || '')
  ))

function fill(m: Maintenance) {
  current.value = m
  form.active = m.active
  form.message = m.message || ''
  form.plannedEnd = m.planned_end || ''
}

function formatStamp(raw: string | null): string {
  if (!raw) return '—'
  const d = new Date(raw)
  if (isNaN(d.getTime())) return raw
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) + ' Uhr'
}

async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/settings/maintenance')
    fill(data.data)
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message ?? 'Laden fehlgeschlagen', false)
  } finally {
    loading.value = false
  }
}

async function persist() {
  saving.value = true
  try {
    const { data } = await client.put('/settings/maintenance', {
      active: form.active,
      message: form.message.trim() || null,
      planned_end: form.plannedEnd.trim() || null,
    })
    fill(data.data)
    showToast(data.data.active ? 'Wartungsmodus aktiv' : 'Wartungsmodus beendet')
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message ?? 'Speichern fehlgeschlagen', false)
  } finally {
    saving.value = false
  }
}

async function save() {
  // Beim AKTIVIEREN einmal nachfragen – es sperrt alle Nicht-Admins aus.
  if (form.active && !current.value?.active) {
    if (!confirm('Wartungsmodus aktivieren?\n\n'
      + 'Normale Nutzende können sich dann nicht mehr anmelden – nur Admins. '
      + 'Der Modus bleibt bestehen, bis er hier wieder beendet wird.')) return
  }
  await persist()
}

async function endMaintenance() {
  form.active = false
  await persist()
}

onMounted(load)
</script>

<template>
  <section>
    <h2 class="section-title">Wartungsmodus</h2>

    <div v-if="loading" class="card-section text-sm text-gray-500">Lädt…</div>

    <div v-else class="space-y-6">
      <!-- Status -->
      <div class="card-section space-y-3">
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-200">Status</span>
          <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                :class="current?.active
                  ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                  : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'">
            {{ current?.active ? 'Wartung aktiv' : 'Normalbetrieb' }}
          </span>
        </div>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Ist die Wartung aktiv, können sich <strong>nur Administrator:innen</strong> anmelden.
          Bereits angemeldete Nutzende bleiben angemeldet – spätestens mit dem Neustart beim
          Update werden ihre Sitzungen beendet und sie kommen dann nicht mehr hinein.
          Hinweistext und geplantes Ende sieht man nur auf dem Login-Bildschirm.
        </p>
        <dl v-if="current?.active" class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Aktiv seit</dt>
            <dd class="text-right">{{ formatStamp(current.since) }}</dd>
          </div>
          <div class="flex justify-between gap-3 border-b border-gray-100 dark:border-white/5 py-1">
            <dt class="text-gray-500">Aktiviert von</dt>
            <dd class="text-right break-all">{{ current.by || '—' }}</dd>
          </div>
        </dl>
      </div>

      <!-- Hinweis beim Aktivsein: muss manuell beendet werden -->
      <div v-if="current?.active"
           class="rounded-2xl border border-amber-300/60 dark:border-amber-500/30
                  bg-amber-50 dark:bg-amber-900/20 px-4 py-3 flex items-start justify-between gap-3">
        <p class="text-sm text-amber-900 dark:text-amber-100">
          Die Wartung endet nicht automatisch. Nach dem Update hier wieder auf Normalbetrieb schalten.
        </p>
        <button @click="endMaintenance" :disabled="saving"
                class="flex-shrink-0 px-3 py-1.5 rounded-xl text-sm font-medium text-white
                       bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60">
          Wartung beenden
        </button>
      </div>

      <!-- Formular -->
      <div class="card-section space-y-4">
        <label class="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" v-model="form.active"
                 class="h-4 w-4 rounded border-gray-300 text-[#3EAAB8] focus:ring-[#3EAAB8]" />
          <span class="text-sm font-medium text-gray-700 dark:text-gray-200">
            Wartungsmodus aktivieren (nur Admins können sich anmelden)
          </span>
        </label>

        <div>
          <label class="lbl">Hinweistext (optional)</label>
          <p class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
            Wird auf dem Login-Bildschirm angezeigt – z. B. der Grund der Wartung.
          </p>
          <textarea v-model="form.message" rows="3" maxlength="2000"
                    placeholder="z. B. Wir spielen ein Update ein. Die Anwendung ist in Kürze wieder verfügbar."
                    class="w-full rounded-xl border border-gray-200 dark:border-white/10
                           bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                           px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
        </div>

        <div>
          <label class="lbl">Geplantes Ende (optional)</label>
          <p class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
            Nur zur Information auf dem Login – die Wartung endet trotzdem erst, wenn sie hier
            wieder beendet wird.
          </p>
          <input type="datetime-local" v-model="form.plannedEnd"
                 class="rounded-xl border border-gray-200 dark:border-white/10
                        bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                        px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
        </div>

        <div class="flex items-center gap-3 pt-1">
          <button @click="save" :disabled="saving || !dirty" class="btn-primary disabled:opacity-60">
            {{ saving ? 'Speichert…' : 'Speichern' }}
          </button>
          <span v-if="dirty" class="text-xs text-gray-500 dark:text-gray-400">
            Ungespeicherte Änderungen
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
