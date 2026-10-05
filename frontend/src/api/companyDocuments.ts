/**
 * API-Client für firmenabhängige Dokument-Vorlagen (.docx/PDF je Firma, nach Name).
 * Verwaltet in den Firmen-Einstellungen; im Prozess referenziert ein Dokument eine
 * solche Vorlage nur über ihren Namen (DocumentSpec.companyTemplate).
 */
import { client } from '@/api/client'

export interface CompanyDocument {
  name: string
  filename: string | null
  size: number | null
  uploaded_at: string | null
  uploaded_by: string | null
  format: 'docx' | 'pdf' | null
  placeholders: string[]
  /** Nicht-null: diese Vorlage ist ein VERWEIS auf die gleichnamige Datei dieser Firma
   *  (keine eigene Datei; Format/Platzhalter stammen aus der Ziel-Datei). */
  ref_company: string | null
}

export interface CompanyDocumentList {
  documents: CompanyDocument[]
  /** Nicht-null: diese Firma übernimmt die Vorlagen der genannten Firma (read-only). */
  shared_from: string | null
}

function base(company: string): string {
  return `/settings/companies/${encodeURIComponent(company)}/documents`
}

export async function listCompanyDocuments(
  company: string, opts: { own?: boolean } = {},
): Promise<CompanyDocumentList> {
  // own=1 umgeht die Übernahme-Auflösung und liefert den EIGENEN Bestand der Firma.
  const { data } = await client.get(base(company), opts.own ? { params: { own: 1 } } : undefined)
  return {
    documents: (data.data?.documents as CompanyDocument[]) ?? [],
    shared_from: (data.data?.shared_from as string | null) ?? null,
  }
}

export async function uploadCompanyDocument(
  company: string, name: string, file: File,
): Promise<CompanyDocument> {
  const form = new FormData()
  form.append('file', file)
  // Content-Type NICHT setzen – der Browser ergänzt die multipart-Boundary.
  const { data } = await client.post(base(company), form, {
    headers: { 'Content-Type': undefined },
    params: { name },
  })
  return data.data
}

export async function deleteCompanyDocument(company: string, name: string): Promise<void> {
  await client.delete(`${base(company)}/${encodeURIComponent(name)}`)
}

/** Diesen Vorlagen-Typ dieser Firma auf die Datei einer ANDEREN Firma verweisen
 *  lassen (statt einer eigenen Datei). Ein Sprung – das Ziel muss die Datei besitzen. */
export async function referenceCompanyDocument(
  company: string, name: string, refCompany: string,
): Promise<CompanyDocument> {
  const { data } = await client.put(
    `${base(company)}/${encodeURIComponent(name)}/reference`, { ref_company: refCompany })
  return data.data
}

/** Download-URL für einen direkten <a href> (KEIN axios → baseURL /api/v1 selbst
 *  voranstellen, sonst landet der Link im SPA-Router statt an der API). */
export function companyDocumentDownloadUrl(company: string, name: string): string {
  return `/api/v1${base(company)}/${encodeURIComponent(name)}/download`
}
