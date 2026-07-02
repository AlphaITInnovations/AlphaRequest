// Reine Logik für die Verlaufs-Anzeige (Diff/Labels) – ohne Vue, damit unit-testbar.

export const FIELD_LABEL: Record<string, string> = {
  priority:    'Priorität',
  comment:     'Kommentar',
  description: 'Formular',
  assignee:    'Zuständig',
  accountable: 'Verantwortlich',
}

// Deutsche Beschriftungen der Formularfelder (für die Verlaufs-Diffs).
// Keyed nach dem letzten Pfadsegment des geflatteten description-Keys.
export const DE_FIELD_LABELS: Record<string, string> = {
  // Stammdaten
  first_name: 'Vorname', last_name: 'Nachname', title: 'Titel',
  private_street: 'Straße (privat)', private_zip: 'PLZ (privat)', private_city: 'Ort (privat)',
  private_address: 'Adresse (privat)',
  start_date: 'Eintrittsdatum', homeoffice: 'Homeoffice', weekly_hours: 'Wochenstunden',
  personal_number: 'Personalnummer',
  // Organisation
  federal_state: 'Bundesland', department: 'Fachabteilung', department_other: 'Fachabteilung (sonstige)',
  cost_center: 'Kostenstelle', location: 'Niederlassung', contract_company: 'Firma (Vertrag)',
  // Beziehungen
  supervisor_hr_id: 'Vorgesetzter', supervisor_hr_name: 'Vorgesetzter',
  contact_person_id: 'Ansprechpartner', contact_person_name: 'Ansprechpartner',
  // IT / Signatur
  appearance_company: 'Firma (Signatur)', street: 'Straße', zip: 'PLZ', city: 'Ort',
  // Timebutler
  vacation_year: 'Urlaubsanspruch', supervisor_id: 'Urlaubsfreigabe', supervisor_name: 'Urlaubsfreigabe',
  // Software-Zugriffe
  datev: 'DATEV-Zugriff', datev_rights: 'DATEV: Rechte wie',
  persopro: 'PersoPro-Zugriff', persopro_rights: 'PersoPro: Zugriffe',
  timejob: 'TimeJob-Zugriff', timejob_rights: 'TimeJob: Zugriffe',
  zvoove: 'Zvoove-Zugriff', zvoove_rights: 'Zvoove: Zugriffe',
  other_systems: 'Weitere Software',
  // Postfächer
  info_mailbox: 'Infopostfach', additional: 'Zusätzliche Postfächer', notes: 'Postfächer (Notiz)',
  additional_cost_centers: 'Zusätzliche Kostenstellen',
  // Fuhrpark
  car: 'Dienstwagen', car_class: 'Fahrzeuggruppe', car_from: 'Dienstwagen ab',
  // Basis-Ticket
  titel: 'Titel', beschreibung: 'Beschreibung',
}

export function labelize(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// Deutsche Beschriftung für ein (ggf. geflattetes) Feld: erst ganzer Pfad,
// dann letztes Segment, sonst aufgehübschter Schlüssel.
export function fieldLabel(key: string): string {
  if (FIELD_LABEL[key]) return FIELD_LABEL[key]
  const seg = key.split('.').pop() ?? key
  return DE_FIELD_LABELS[seg] ?? FIELD_LABEL[seg] ?? labelize(seg)
}

export function formatVal(v: any): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (typeof v === 'object') return '—' // sollte nach flatten nicht mehr vorkommen
  return String(v)
}

export function isText(v: any): boolean {
  return v !== null && v !== undefined && String(v).trim() !== ''
}

// Verb je nach alt/neu: hinzugefügt / geändert / entfernt
export function commentVerb(change: { old?: any; new?: any } | undefined): string {
  const had = isText(change?.old)
  const has = isText(change?.new)
  if (!had && has) return 'Kommentar hinzugefügt'
  if (had && !has) return 'Kommentar entfernt'
  return 'Kommentar geändert'
}

// Flacht ein verschachteltes Objekt auf primitive Werte ab.
// { software: { datev: true, persopro: false } } → { 'software.datev': true, 'software.persopro': false }
export function flatten(obj: Record<string, any>, prefix = ''): Record<string, any> {
  const result: Record<string, any> = {}
  for (const [k, v] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(result, flatten(v, fullKey))
    } else {
      result[fullKey] = v
    }
  }
  return result
}

export interface FieldDiff { key: string; label: string; oldVal: any; newVal: any }

// Vergleicht zwei description-Snapshots und gibt nur geänderte primitive Felder zurück.
export function descriptionDiff(
  old: Record<string, any>,
  next: Record<string, any>,
): FieldDiff[] {
  const flatOld  = flatten(old  ?? {})
  const flatNext = flatten(next ?? {})

  const allKeys = new Set([...Object.keys(flatOld), ...Object.keys(flatNext)])
  const result: FieldDiff[] = []

  for (const key of allKeys) {
    // Interne Meta-Felder (mit '_' beginnend, z.B. _next_assignee) nicht anzeigen.
    if (key.startsWith('_')) continue
    // ID-Felder (rohe GUIDs) nicht anzeigen – die lesbare Änderung steht im *_name-Feld.
    const seg = key.split('.').pop() ?? key
    if (seg === 'id' || seg.endsWith('_id')) continue

    const o = flatOld[key]
    const n = flatNext[key]
    if (JSON.stringify(o) !== JSON.stringify(n)) {
      const newMeaningful = n !== null && n !== undefined && n !== '' && n !== false
      const oldMeaningful = o !== null && o !== undefined && o !== '' && o !== false
      if (!newMeaningful && !oldMeaningful) continue
      result.push({ key, label: fieldLabel(key), oldVal: o, newVal: n })
    }
  }
  return result
}
