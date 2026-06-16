<script setup lang="ts">
import { ref } from 'vue'
import { jsPDF } from 'jspdf'
import HotelbuchungContentPanel from '@/components/tickets/HotelbuchungContentPanel.vue'

const props = defineProps<{
  description: any
  ownerName?: string
  createdAt?: string
}>()
const emit = defineEmits<{ exported: [] }>()

const ANLASS_LABEL: Record<string, string> = {
  kundentermin:         'Kundentermin',
  besuch_niederlassung: 'Besuch Niederlassung',
  sonstiges:            'Sonstiges',
}

const exporting = ref(false)

function exportPdf() {
  exporting.value = true
  try {
    const b = props.description?.buchung ?? {}
    const doc = new jsPDF({ unit: 'mm', format: 'a4' })
    const left = 16
    const pageH = doc.internal.pageSize.getHeight()
    let y = 18

    const ensure = (h = 7) => { if (y + h > pageH - 16) { doc.addPage(); y = 18 } }
    const heading = (t: string) => {
      ensure(12); y += 3
      doc.setFontSize(12); doc.setFont('helvetica', 'bold'); doc.setTextColor(40)
      doc.text(t, left, y); y += 6
      doc.setDrawColor(200); doc.line(left, y - 3, 196, y - 3)
    }
    const row = (label: string, val: any) => {
      const v = (val === undefined || val === null || val === '') ? '—' : String(val)
      ensure()
      doc.setFontSize(10); doc.setFont('helvetica', 'bold'); doc.setTextColor(110)
      doc.text(`${label}:`, left, y)
      doc.setFont('helvetica', 'normal'); doc.setTextColor(30)
      const lines = doc.splitTextToSize(v, 120) as string[]
      doc.text(lines, left + 52, y)
      y += 6 * lines.length
    }

    // Titel
    doc.setFontSize(17); doc.setFont('helvetica', 'bold'); doc.setTextColor(20)
    doc.text('Hotelbuchung – Antrag', left, y); y += 8
    doc.setFontSize(9); doc.setFont('helvetica', 'normal'); doc.setTextColor(120)
    doc.text(`Beantragt von ${props.ownerName ?? '—'}  ·  Erstellt am ${props.createdAt ?? '—'}`, left, y)
    y += 4

    heading('Antragsteller')
    row('Name', b.antragsteller_name)
    row('E-Mail', b.antragsteller_email)
    row('Niederlassung', b.niederlassung)
    row('Telefonnummer', b.telefonnummer)
    row('Kostenstelle', b.kostenstelle)

    heading('Reisedaten')
    row('Anreise', b.anreisedatum)
    row('Abreise', b.abreisedatum)
    row('Übernachtungen', b.anzahl_naechte)

    heading('Reiseziel')
    row('Ort / Stadt', b.ort_stadt)
    row('Partner-Hotel', b.partner_hotel)
    row('Hotelwunsch', b.hotelwunsch)

    heading('Reiseanlass')
    row('Art', ANLASS_LABEL[b.reiseanlass] ?? b.reiseanlass)
    if (b.reiseanlass === 'kundentermin') {
      row('Kundenname', b.kunde_name)
      row('Anschrift', b.kunde_anschrift)
      row('Grund', b.kunde_grund)
    } else if (b.reiseanlass === 'besuch_niederlassung') {
      row('Niederlassung', b.besuch_niederlassung)
      row('Begründung', b.besuch_begruendung)
    } else if (b.reiseanlass === 'sonstiges') {
      row('Begründung', b.sonstiges_grund)
      row('Genehmigung durch', b.genehmigung_name)
    }

    heading('Budget')
    row('Bestätigung', b.budget_bestaetigung === 'unter_120'
      ? 'Kosten ≤ 120 € pro Nacht inkl. Frühstück'
      : b.budget_bestaetigung === 'abweichung' ? 'Abweichung erforderlich' : '—')
    if (b.budget_bestaetigung === 'abweichung') {
      row('Begründung', b.budget_begruendung)
      row('Genehmigung durch', b.budget_genehmigung_name)
    }

    if (b.besondere_anforderungen) {
      heading('Besondere Anforderungen')
      row('', b.besondere_anforderungen)
    }

    const safeName = String(b.antragsteller_name || props.ownerName || 'Antrag').replace(/[^\w]+/g, '_')
    doc.save(`Hotelbuchung_${safeName}.pdf`)
    emit('exported')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <!-- Kopf: Auftrag an die Reisestelle -->
    <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                rounded-2xl shadow-sm p-5 flex items-center justify-between gap-4">
      <div>
        <p class="text-sm font-semibold text-gray-900 dark:text-white">Reisestelle – Buchung & Export</p>
        <p class="text-xs text-gray-400 mt-0.5">
          Beantragt von {{ ownerName || '—' }} · {{ createdAt || '—' }}
        </p>
      </div>
      <button @click="exportPdf" :disabled="exporting"
              class="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium
                     bg-[#3EAAB8] hover:bg-[#2B7D89] text-white disabled:opacity-60 transition flex-shrink-0">
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2"/>
        </svg>
        {{ exporting ? 'Erzeuge PDF…' : 'PDF exportieren' }}
      </button>
    </div>

    <!-- Buchungsdaten (read-only, wiederverwendet) -->
    <HotelbuchungContentPanel :description="description" />
  </div>
</template>
