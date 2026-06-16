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

// ── Helfer ──────────────────────────────────────────────────────────────────
function fmtDateTime(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 16).replace('T', ' ')
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) + ' Uhr'
}
// jsPDF-Standardschrift (WinAnsi) kann manche Unicode-Zeichen nicht – ersetzen.
function clean(v: any): string {
  return String(v ?? '—')
    .replace(/≤/g, 'max.').replace(/≥/g, 'min.')
    .replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
}

function exportPdf() {
  exporting.value = true
  try {
    const b = props.description?.buchung ?? {}
    const doc = new jsPDF({ unit: 'mm', format: 'a4' })
    const M = 16, RIGHT = 194, COL2 = 108, W_FULL = RIGHT - M, W_COL = COL2 - M - 6
    const pageH = doc.internal.pageSize.getHeight()
    const TEAL: [number, number, number] = [62, 170, 184]
    let y = 0

    const ensure = (h = 12) => { if (y + h > pageH - 18) { doc.addPage(); y = 18 } }

    // Feld (Label klein/grau, Wert dunkel) an x; ändert y NICHT, gibt Höhe zurück
    const drawField = (x: number, label: string, value: any, w: number): number => {
      doc.setFontSize(7.5); doc.setFont('helvetica', 'bold'); doc.setTextColor(150)
      doc.text(clean(label).toUpperCase(), x, y)
      doc.setFontSize(10); doc.setFont('helvetica', 'normal'); doc.setTextColor(35)
      const lines = doc.splitTextToSize(clean(value), w) as string[]
      doc.text(lines, x, y + 4.6)
      return 4.6 + lines.length * 4.7 + 4
    }
    const row2 = (l1: string, v1: any, l2?: string, v2?: any) => {
      ensure(16)
      const h1 = drawField(M, l1, v1, W_COL)
      const h2 = l2 ? drawField(COL2, l2, v2, W_COL) : 0
      y += Math.max(h1, h2)
    }
    const rowFull = (l: string, v: any) => { ensure(14); y += drawField(M, l, v, W_FULL) }
    const section = (title: string) => {
      ensure(16); y += 5
      doc.setFillColor(...TEAL); doc.rect(M, y - 3.4, 2.4, 5, 'F')
      doc.setFontSize(11.5); doc.setFont('helvetica', 'bold'); doc.setTextColor(...TEAL)
      doc.text(clean(title), M + 5, y); y += 7
    }

    // ── Header-Balken ──
    doc.setFillColor(...TEAL); doc.rect(0, 0, 210, 30, 'F')
    doc.setTextColor(255, 255, 255)
    doc.setFontSize(19); doc.setFont('helvetica', 'bold'); doc.text('Hotelbuchung', M, 14)
    doc.setFontSize(11); doc.setFont('helvetica', 'normal'); doc.text('Reiseantrag', M, 22)
    doc.setFontSize(8.5)
    doc.text(`Beantragt von: ${clean(props.ownerName)}`, RIGHT, 13, { align: 'right' })
    doc.text(`Erstellt: ${fmtDateTime(props.createdAt)}`, RIGHT, 19, { align: 'right' })
    y = 42

    section('Antragsteller')
    row2('Name', b.antragsteller_name, 'E-Mail', b.antragsteller_email)
    row2('Niederlassung', b.niederlassung, 'Telefon', b.telefonnummer)
    row2('Kostenstelle', b.kostenstelle)

    section('Reisedaten')
    row2('Anreise', b.anreisedatum, 'Abreise', b.abreisedatum)
    row2('Übernachtungen', b.anzahl_naechte)

    section('Reiseziel')
    row2('Ort / Stadt', b.ort_stadt, 'Partner-Hotel', b.partner_hotel)
    if (b.hotelwunsch) rowFull('Hotelwunsch', b.hotelwunsch)

    section('Reiseanlass')
    rowFull('Art', ANLASS_LABEL[b.reiseanlass] ?? b.reiseanlass)
    if (b.reiseanlass === 'kundentermin') {
      row2('Kundenname', b.kunde_name, 'Anschrift', b.kunde_anschrift)
      rowFull('Grund des Besuchs', b.kunde_grund)
    } else if (b.reiseanlass === 'besuch_niederlassung') {
      row2('Niederlassung', b.besuch_niederlassung)
      if (b.besuch_begruendung) rowFull('Begründung', b.besuch_begruendung)
    } else if (b.reiseanlass === 'sonstiges') {
      rowFull('Begründung', b.sonstiges_grund)
      row2('Genehmigung durch', b.genehmigung_name)
    }

    section('Budget')
    rowFull('Bestätigung', b.budget_bestaetigung === 'unter_120'
      ? 'Kosten max. 120 EUR pro Nacht inkl. Frühstück'
      : b.budget_bestaetigung === 'abweichung' ? 'Abweichung erforderlich' : '—')
    if (b.budget_bestaetigung === 'abweichung') {
      rowFull('Begründung', b.budget_begruendung)
      row2('Genehmigung durch', b.budget_genehmigung_name)
    }

    if (b.besondere_anforderungen) {
      section('Besondere Anforderungen')
      rowFull('', b.besondere_anforderungen)
    }

    // ── Fußzeile auf allen Seiten ──
    const pages = doc.getNumberOfPages()
    for (let i = 1; i <= pages; i++) {
      doc.setPage(i)
      doc.setDrawColor(225); doc.line(M, pageH - 14, RIGHT, pageH - 14)
      doc.setFontSize(7.5); doc.setFont('helvetica', 'normal'); doc.setTextColor(150)
      doc.text(`Hotelbuchung · ${clean(props.ownerName)}`, M, pageH - 9)
      doc.text(`Seite ${i} / ${pages}`, RIGHT, pageH - 9, { align: 'right' })
    }

    const safe = String(b.antragsteller_name || props.ownerName || 'Antrag').replace(/[^\w]+/g, '_')
    doc.save(`Hotelbuchung_${safe}.pdf`)
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
        <p class="text-sm font-semibold text-gray-900 dark:text-white">Reisestelle – Buchung &amp; Export</p>
        <p class="text-xs text-gray-400 mt-0.5">
          Beantragt von {{ ownerName || '—' }} · {{ fmtDateTime(createdAt) }}
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
