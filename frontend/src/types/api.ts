/**
 * Geteilte API-Typen: angemeldete Person, Rechte und die Antwort-Hüllen des
 * Backends (backend/schemas/responses.py).
 *
 * Bewusst KEINE fachlichen Typen hier. Diese Datei trägt genau das, was jeder
 * Aufruf braucht – vom Login (`api/auth.ts`, `stores/authStore.ts`) bis zu den
 * Prozess-Endpunkten. Fachliches gehört in `types/process.ts`.
 */

// ── Rechte ────────────────────────────────────────────────────────────────────

/**
 * Globale Rollen aus `backend/database/users.py` (PERM_VIEW/MANAGE/ADMIN).
 *
 * `(string & {})` bleibt bewusst offen: Rechte kommen aus der Datenbank und das
 * Frontend darf an einem neuen Recht nicht mit einem Typfehler scheitern. Wer
 * einen Auftrag ANLEGEN darf, steht dagegen nicht mehr hier – das entscheidet
 * `createPermissions` der jeweiligen Prozess-Definition, und der Server sagt es
 * je Prozess über `may_create` im Katalog (GET /processes).
 */
export type Permission = 'view' | 'manage' | 'admin' | (string & {})

export interface User {
  id:          string
  displayName: string
  mail:        string | null
  permissions: Permission[]
}

// ── Antwort-Hüllen ───────────────────────────────────────────────────────────

export interface Meta {
  total:  number
  limit:  number
  offset: number
}

export interface DataResponse<T> {
  data: T
}

export interface ListResponse<T> {
  data: T[]
  meta: Meta
}
