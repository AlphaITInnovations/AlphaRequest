/**
 * „Wer ist zuständig / wer ist der nächste Bearbeiter?" in ANZEIGBARER Form.
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist – das
 * Projekt hat kein jsdom.
 *
 * Die Zuständigkeit löst der SERVER auf (`ticket.responsibility`, siehe
 * backend/services/process_runtime.resolve_responsibility). Sie kommt mit IDs
 * an; die Namen liefert lib/processSources.ts. Nachbauen kann das Frontend die
 * Auflösung nicht – es kennt weder Gruppen-Mitgliedschaften noch die Regeln.
 *
 * DER WICHTIGE FALL IST DER LEERE: bei `kind='assignable'` bzw.
 * `kind='group_from_field'` steht die zuständige Stelle in einem FELD des
 * Auftrags. Ist das Feld leer, liefert der Server `user: null` / `group: null` –
 * dann ist NIEMAND zuständig, niemand wird benachrichtigt und der Auftrag bleibt
 * unbemerkt liegen. Deshalb hat `missing` einen eigenen Klartext-Hinweis: die
 * Oberfläche muss das laut zeigen können.
 */
import type { DepartmentState } from '@/lib/processDepartments'

/**
 * Lose Eingabeform von `ResolvedResponsibility` (types/process.ts).
 *
 * Absichtlich lose: der Server sendet bei leerem Quellfeld `group`/`user` als
 * `null`, die geteilte Typdatei beschreibt sie (noch) als `string`. Ein strenger
 * Typ hier würde genau den Fall wegdefinieren, um den es geht.
 */
export interface ResponsibilityIn {
  kind?: string | null
  group?: string | null
  user?: string | null
  from_field?: string | null
  assignable?: boolean | null
  departments?: readonly DepartmentState[] | null
}

export interface ResponsibilityLookup {
  /** Gruppen-ID → Name. */
  groupName?: (id: string) => string
  /** Personen-ID → Anzeigename. */
  userName?: (id: string) => string
  /** Feld-Schlüssel → Beschriftung (für „steht im Feld …"). */
  fieldName?: (key: string) => string
  /** Name der antragstellenden Person (`ticket.owner_name`). */
  ownerName?: string | null
}

export type ResponsibilityViewKind = 'owner' | 'group' | 'user' | 'departments' | 'unknown'

export interface ResponsibilityView {
  kind: ResponsibilityViewKind
  /** Art der Stelle, z. B. „Fachabteilung" – steht als Unterzeile unter dem Namen. */
  roleLabel: string
  /** Anzeigename der zuständigen Stelle; leer genau dann, wenn `missing`. */
  name: string
  /** Niemand zuständig – der Auftrag bleibt liegen. */
  missing: boolean
  /** Klartext, WARUM niemand zuständig ist (leer, wenn jemand zuständig ist). */
  missingHint: string
  /** Quellfeld der Zuständigkeit (`assignable`/`group_from_field`), sonst null. */
  fromField: string | null
}

const NO_ONE = 'Für diese Phase ist niemand zuständig – der Auftrag bleibt liegen, '
  + 'bis eine Stelle eingetragen wird.'

function feldName(key: string, look: ResponsibilityLookup): string {
  return look.fieldName?.(key) || key
}

/** „Im Feld „X" steht noch niemand" – der einzige Hinweis, der auch handelbar ist. */
function leeresFeldHinweis(
  fromField: string | null, look: ResponsibilityLookup, was: string,
): string {
  if (!fromField) return NO_ONE
  return `Im Feld „${feldName(fromField, look)}“ steht ${was} – solange es leer ist, `
    + 'ist niemand zuständig und der Auftrag bleibt liegen.'
}

export function describeResponsibility(
  resp: ResponsibilityIn | null | undefined,
  look: ResponsibilityLookup = {},
): ResponsibilityView {
  const fromField = resp?.from_field?.trim() || null
  const base = { fromField, name: '', missing: false, missingHint: '' }

  if (!resp || !resp.kind || resp.kind === 'unknown') {
    return {
      ...base, kind: 'unknown', roleLabel: 'Zuständigkeit',
      missing: true,
      missingHint: 'Zu dieser Phase ist keine Zuständigkeit hinterlegt – bitte die '
        + 'Prozess-Definition prüfen.',
    }
  }

  if (resp.kind === 'owner') {
    // Die Ersteller:in gibt es immer; fehlt nur der Name, ist die Zuständigkeit
    // trotzdem geklärt – deshalb NICHT `missing`.
    return {
      ...base, kind: 'owner', roleLabel: 'Antragsteller:in',
      name: look.ownerName?.trim() || 'Ersteller:in des Auftrags',
    }
  }

  if (resp.kind === 'departments') {
    const list = (resp.departments ?? []).filter((d): d is DepartmentState => !!d)
    if (!list.length) {
      return {
        ...base, kind: 'departments', roleLabel: 'Fachabteilungen',
        missing: true,
        missingHint: 'Zu dieser Phase passt keine Fachabteilung – so lässt sich die Phase '
          + 'nicht quittieren. Bitte die Bedingungen der Definition prüfen.',
      }
    }
    return {
      ...base, kind: 'departments', roleLabel: 'Fachabteilungen',
      name: list.length === 1 ? '1 Fachabteilung' : `${list.length} Fachabteilungen`,
    }
  }

  if (resp.kind === 'group') {
    const id = resp.group?.trim() || ''
    if (!id) {
      return {
        ...base, kind: 'group', roleLabel: 'Fachabteilung',
        missing: true,
        missingHint: leeresFeldHinweis(fromField, look, 'keine Fachabteilung'),
      }
    }
    return {
      ...base, kind: 'group', name: look.groupName?.(id) || id,
      roleLabel: fromField ? 'Fachabteilung (aus dem Auftrag)' : 'Fachabteilung',
    }
  }

  if (resp.kind === 'user') {
    const id = resp.user?.trim() || ''
    if (!id) {
      return {
        ...base, kind: 'user', roleLabel: 'Person',
        missing: true,
        missingHint: leeresFeldHinweis(fromField, look, 'keine Person'),
      }
    }
    return {
      ...base, kind: 'user', name: look.userName?.(id) || id,
      roleLabel: fromField ? 'Person (aus dem Auftrag)' : 'Person',
    }
  }

  // Unbekannte Art ehrlich als Rohwert zeigen, statt sie zu erfinden.
  return {
    ...base, kind: 'unknown', roleLabel: `Unbekannte Zuständigkeit (${resp.kind})`,
    missing: true, missingHint: NO_ONE,
  }
}

/**
 * Darf die zuständige Stelle HIER umgestellt werden („weiterreichen")?
 *
 * Drei Bedingungen, alle vom Server:
 *  1. die Zuständigkeit kommt aus einem FELD (`from_field`),
 *  2. dieses Feld ist in der aktuellen Phase editierbar (`editable_fields`),
 *  3. diese Person darf den Auftrag überhaupt bearbeiten (`abilities.edit`).
 *
 * (3) ist NICHT in (2) enthalten: `editable_fields` ist ein Feld-Gate (Modus und
 * Sichtbarkeit), kein Rollen-Gate – auch Beobachter:innen und die Ersteller:in
 * bekommen die Liste gefüllt. Ohne die dritte Prüfung stünde bei ihnen ein Knopf,
 * den der PATCH mit 403 beantwortet.
 */
export interface HandoverTarget {
  /** Feld-Schlüssel, in dem die zuständige Stelle steht. */
  field: string
  /** Welche Auswahl gebraucht wird. */
  pick: 'group' | 'user'
  /** Aktuell eingetragener Wert; leer = niemand zuständig. */
  current: string
}

export function handoverTarget(
  resp: ResponsibilityIn | null | undefined,
  editableFields: readonly string[] | null | undefined,
  /** `ticket.abilities.edit` – bewusst ein eigener Parameter, siehe Docstring. */
  canEdit: boolean,
): HandoverTarget | null {
  if (!canEdit) return null
  const field = resp?.from_field?.trim() || null
  if (!field || !resp) return null
  if (!(editableFields ?? []).includes(field)) return null
  if (resp.kind === 'group') return { field, pick: 'group', current: resp.group?.trim() || '' }
  if (resp.kind === 'user') return { field, pick: 'user', current: resp.user?.trim() || '' }
  return null
}
