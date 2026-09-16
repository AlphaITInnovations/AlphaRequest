/**
 * Aufbereitung des Directus-Mitarbeiter-Datensatzes für die Profil-Anzeige.
 *
 * Der Datensatz trägt technische Feldnamen (`last_name`, `job_title`, …) und –
 * je nach geladenen Feldern – Relationen als ID oder als verschachteltes Objekt
 * (`{ name: … }`). `fmtValue` rendert beides sicher, `employeeRows` bringt die
 * bekannten Felder in eine sinnvolle Reihenfolge und übersetzt die Labels.
 */

/** Deutsche Labels für die bekannten `mitarbeitende`-Felder. */
export const FIELD_LABELS: Record<string, string> = {
  first_name: 'Vorname',
  last_name: 'Nachname',
  email: 'E-Mail',
  job_title: 'Position',
  company: 'Firma',
  cost_center: 'Kostenstelle',
  location: 'Niederlassung',
  phone: 'Telefon',
  mobile: 'Mobil',
  status: 'Status',
  ad_account: 'AD-Konto',
  ad_guid: 'AD-GUID',
  id: 'Directus-ID',
  date_created: 'Erstellt',
  date_updated: 'Aktualisiert',
  user_created: 'Erstellt von',
  user_updated: 'Geändert von',
  self_reported_at: 'Selbst gemeldet am',
}

/** Reihenfolge der inhaltlich wichtigen Felder; alles andere folgt danach. */
const ORDER = [
  'first_name', 'last_name', 'email', 'job_title',
  'company', 'cost_center', 'location', 'phone', 'mobile', 'status',
]

/** Rendert einen beliebigen Feldwert lesbar: Relation → Name, Liste → Aufzählung,
 *  leer → „–". */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '–'
  if (Array.isArray(v)) return v.length ? v.map(fmtValue).join(', ') : '–'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    for (const k of ['name', 'label', 'title', 'bezeichnung', 'nummer']) {
      if (typeof o[k] === 'string' || typeof o[k] === 'number') return String(o[k])
    }
    return JSON.stringify(v)
  }
  return String(v)
}

export function labelFor(key: string): string {
  return FIELD_LABELS[key] ?? key
}

export interface ProfileRow { key: string; label: string; value: string }

/** Bekannte Felder zuerst (feste Reihenfolge), dann der Rest; Werte formatiert. */
export function employeeRows(employee: Record<string, unknown> | null | undefined): ProfileRow[] {
  if (!employee) return []
  const keys = Object.keys(employee)
  const known = ORDER.filter((k) => k in employee)
  const rest = keys.filter((k) => !ORDER.includes(k))
  return [...known, ...rest].map((k) => ({
    key: k, label: labelFor(k), value: fmtValue(employee[k]),
  }))
}
