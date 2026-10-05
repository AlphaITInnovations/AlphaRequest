/**
 * Dokument-Vorlagen-Typen (Labels): verwaltete Liste der Typen (Arbeitsvertrag,
 * Kündigung …). Firmen laden ihre Vorlagen je Typ hoch; der Prozess referenziert
 * den Typ. Pro Typ EIN kanonischer {{Platzhalter}}-Satz (beim ersten Upload erfasst,
 * danach erzwungen).
 */
import { client } from '@/api/client'

export interface TemplateLabel {
  name: string
  /** Kanonischer Platzhalter-Satz des Typs; null = noch keine Vorlage hochgeladen. */
  placeholders: string[] | null
  /** Firmen, die für diesen Typ eine Vorlage hinterlegt haben. */
  companies: string[]
}

export async function listTemplateLabels(): Promise<TemplateLabel[]> {
  const { data } = await client.get('/settings/document-template-labels')
  return (data.data?.labels as TemplateLabel[]) ?? []
}

export async function saveTemplateLabels(names: string[]): Promise<TemplateLabel[]> {
  const { data } = await client.put('/settings/document-template-labels', { labels: names })
  return (data.data?.labels as TemplateLabel[]) ?? []
}
