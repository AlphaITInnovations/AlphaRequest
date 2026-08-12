# Design: Dynamisches Prozess- & Workflow-System

> **Status:** Implementierungs-Spezifikation (Rev. 2, nach adversarischem Review) ·
> **Branch:** `feature/dynamic-processes` · **Checkpoint:** Tag `checkpoint/pre-dynamic-processes`
> **Grundsatz:** Neustart ohne Rückwärtskompatibilität. Alt-Tickets werden nicht migriert;
> der alte Stand bleibt über den Checkpoint erreichbar. Das Format muss die realen
> Prozess-*Formen* (Onboarding, Basis-Ticket, Hardware, Hotelbuchung …) trotzdem
> ausdrücken können — sonst ist „Code → Daten" nicht erfüllt.

> **Rev. 2 — was sich ggü. Rev. 1 geändert hat:** Format um Nicht-Skalar-Feldtypen erweitert
> (§3.1); Sichtbarkeit als *erzwungene* Invariante über **alle** Ausgabekanäle (§5);
> Versionen unveränderlich + lösch-/nebenläufigkeitssicher (§4); Timer-Semantik exakt
> definiert (§7); Validierung in zwei Pässe + Fehler-Envelope (§9); v1 wird **ersetzt**
> (kein /api/v2); vollständige REST-Oberfläche + Authz (§8). Offene Punkte entschieden (§13).

---

## 0. Ziel

Aufträge (Prozesse) werden von **Code** zu **Daten**: Phasen, Felder, Pflicht-/Anzeige-Regeln,
Sichtbarkeit und automatische Aktionen leben in einem **JSON-Dokument**, das **im Frontend
visuell bearbeitbar**, **exportier-/importier-/kopierbar** ist, über **Entwurf → Vorschau →
Release** läuft (nie direkt am Live-Prozess) und **erweiterbare Per-Phasen-Features** trägt.
Dazu **saubere REST-API** und **echte Server-Validierung**.

---

## 1. Anforderungen & getroffene Entscheidungen

| # | Anforderung | Entscheidung |
|---|---|---|
| 1 | JSON-Prozessformat, Export/Import/Kopie | ✔ §3 |
| 2 | Visueller Phasen-Editor | ✔ Baustufe 6 |
| 3 | Entwurf → Vorschau → Release | Vorschau = **Client-Simulation** (kein Wegwerf-Ticket); Release s. §4 |
| 4 | Keine Rückwärtskompatibilität | ✔ Neustart; **v1 wird ersetzt** (kein Parallelbetrieb, §8/§13) |
| 5 | Flexible Per-Phasen-Features (z. B. Eskalation) | Erweiterbares **Automations-Registry** (§6); Eskalation ist **späteres** Beispiel, Modell muss es tragen |
| 6 | Saubere API statt `view`/`overview` | ✔ §8 |
| 7 | Server-Validierung (heute: „alles wird angenommen") | ✔ Zwei-Pass-Validierung + Fehler-Envelope (§9) |
| — | Wer darf Prozesse bearbeiten/releasen? | **Nur Admin** (`PERM_ADMIN`) + Audit (§8) |
| — | Sweeper-Takt | Default **15 min**, eigener gated Task (§7) |

---

## 2. Ausgangslage im Code (verifiziert)

- **Hintergrund-Loop existiert:** [app_lifespan.py:72](../../backend/core/app_lifespan.py)
  (`while True … asyncio.sleep`, AD-Sync + `prune_stale`). ⚠️ Er läuft **im Event-Loop** und
  **pro Instanz**. Der Sweeper darf **nicht** einfach hier reingehängt werden (§7).
- **Zeitstempel inkonsistent:** History = **Berlin-Lokalzeit** ([ticket_history.py:24](../../backend/services/ticket_history.py)),
  Audit/Health = UTC. `_now_iso()` in [tickets.py](../../backend/api/v1/tickets.py) erzeugt **naive** Zeit
  (ohne tzinfo). → Für SLA ein **eigener tz-aware-UTC-Writer**, nie `_now_iso()` (sonst `TypeError` beim ersten Vergleich).
- **Sichtbarkeit** läuft heute durch **eine** Server-Naht (`ticket_visibility.filter_description`) —
  aber History-`details` und `workflow_state` gehen **daran vorbei** (§5).
- **Mail** ist synchron `requests.post(timeout=30)` ([microsoft_mail.py](../../backend/services/microsoft_mail.py)) — blockierend.
- **Personalnummer**: server-generiert aus Pro-Firma-Zähler mit Warnschwelle + Warnmail
  ([personalnummer.py](../../backend/database/personalnummer.py)). Muss als Feldtyp/Action abbildbar sein (§3.1).

---

## 3. Das Prozess-Format (`ProcessDefinition`)

Ein Prozess = **ein JSON-Dokument**. **Felder werden genau einmal** im Katalog definiert
(Label, Widget, Constraints, Sichtbarkeit); **Phasen referenzieren** Felder und legen pro Phase
`mode` (editable/readonly/hidden), `required`/`requiredWhen`, `visibleWhen` fest.
**Sichtbarkeit steckt im Feld** → keine doppelten Dot-Paths.

```jsonc
{
  "schemaVersion": 1,
  "key": "einstellung",
  "name": "Einstellung Mitarbeiter:in",
  "icon": "📝",

  "fields": [
    { "key": "base.first_name", "label": "Vorname", "widget": "text",
      "constraints": { "maxLength": 100 } },

    { "key": "base.contract_company", "label": "Firma lt. Vertrag",
      "widget": "select", "optionsSource": "companies", "valueShape": "name" },

    // Server-generiert: kein Client-Input, per Action befüllt
    { "key": "personal.personal_number", "label": "Personalnummer",
      "widget": "server_generated", "assign": { "action": "assign_sequence",
        "counter": "per_company", "companyRef": "base.contract_company" } },

    // Berechnet mit „manuell schlägt Automatik"
    { "key": "signature.title", "label": "Signatur-Titel", "widget": "text",
      "computed": { "from": "base.title" }, "overridable": true },

    // Vertraulich: Sichtbarkeit im Feld, Gruppen als ID
    { "key": "personal.salary", "label": "Gehalt & Konditionen", "widget": "textarea",
      "visibility": { "confidential": true, "visibleToGroups": ["grp_sekretariat_gl"] } },

    // Wiederholgruppe, append-only, server-gestempelt (Basis-Ticket-Log)
    { "key": "eintraege", "label": "Verlauf", "widget": "collection",
      "mode": "append_only",
      "item": [
        { "key": "text", "widget": "textarea" },
        { "key": "author", "widget": "server_stamped", "value": "actor" },
        { "key": "timestamp", "widget": "server_stamped", "value": "now" }
      ] }
  ],

  "phases": [
    {
      "key": "erstellung", "label": "Erstellung", "kind": "start",
      "responsibility": { "kind": "owner" },
      "view": "form", "enterStatus": "in_progress",
      "grantsFullView": true,
      "fields": [
        { "ref": "base.first_name", "mode": "editable", "required": true },
        { "ref": "personal.salary", "mode": "editable",
          "visibleWhen": { "==": ["base.contract_type", "fest"] },
          "requiredWhen": { "==": ["base.contract_type", "fest"] } }
      ],
      "constraints": [
        { "when": { "or": [ { "truthy": "artikel.notebook" }, { "truthy": "monitor.benoetigt" } ] },
          "message": "Mindestens ein Artikel oder Monitor nötig." }
      ]
    },
    {
      "key": "durchfuehrung", "label": "Durchführung", "kind": "review",
      "view": "review", "enterStatus": "in_request", "grantsFullView": false,
      "responsibility": {
        "kind": "departments",
        "rule": [
          { "group": "grp_it", "required": true },
          { "group": "grp_fuhrpark", "required": true, "when": { "==": ["fuhrpark.car", "Ja"] } }
        ],
        "resetOnDescriptionChange": true
      },
      "fields": [ { "ref": "it.hostname", "mode": "editable" } ],
      "automations": [
        { "id": "reminder-7d", "trigger": { "type": "timer", "after": "P7D", "repeat": "P7D" },
          "action": { "type": "notify", "to": "responsible", "template": "reminder" } }
      ]
    }
  ],

  "automations": []
}
```

### 3.1 Feld-Typen (Widget-Whitelist)
**Skalar:** `text · textarea · number · date · select · multiselect · checkbox · checkbox-group · attachment`.
**Referenz-Picker:** `user · company · group` — mit `optionsSource` (`static | groups | companies | users`,
kombinierbar mit inline `options` + `allowOther`-Begleitfeld) und definierter `valueShape`
(`id` vs. `name`; User/Company/Group als strukturiertes `{id,label,email?}` **oder** dokumentierte
Geschwister-Keys `*_id/*_name/*_email` als denormalisierter Snapshot — Sichtbarkeit/History hängen daran).
**Nicht-Skalar (neu, aus Review):**
- `collection` — Array von Sub-Katalog-Items; `mode: append_only` möglich; `server_stamped`-Subfelder
  (author/timestamp beim Anhängen serverseitig gesetzt, **nicht** client-schreibbar). Deckt Basis-Ticket-Log
  und Marketing-Freitextlisten. Klar getrennt von `multiselect` (feste Optionsliste).
- `server_generated` — kein Client-Input; per benannter Action befüllt (z. B. `assign_sequence`
  über einen Zähler-Source, wiederverwendet `personalnummer.py`).
- `server_stamped` — vom Server gesetzter Wert (`actor`/`now`), nur innerhalb `collection`-Items.

**Feld-Attribute:** `computed.from` (+ `overridable`, „manuell schlägt Automatik"), optional
`constraints` (`pattern, minLength, maxLength, min, max, minDate, maxDate`) — vom Meta-Schema geprüft
und in Pass 1 der Validierung (§9) erzwungen. Externe Lookups (PLZ→Bundesland) sind ein **whitelisted
`lookup`-Source** — oder bleiben bewusst code-seitig (dann explizit als Platzhalter deklariert).

**`view`-Whitelist der Phase:** `form | readonly | approval | review`. `export` (z. B. der jsPDF-Layout
der Hotelbuchung) ist ein **code-hinterlegter Per-Prozess-Baustein**, außerhalb des generischen Renderers
(optional später als Export-Template-Konfiguration).

### 3.2 Bedingungen: `visibleWhen` vs. `requiredWhen` vs. `constraints`
- `visibleWhen` (Feld-*Anzeige* pro Phase) — **fehlte in Rev. 1**; reale Formulare zeigen ganze Blöcke
  bedingt (Hotelbuchung-Reiseanlass, Zugang-Softwarerechte). Serverseitig autoritativ ausgewertet.
- `requiredWhen` (bedingte Pflicht) — bindet an ein Feld.
- Phase-`constraints[]` (feldübergreifend, z. B. „mind. ein Artikel") — vom Validator in Pass 2 geprüft.

### 3.3 `schemaVersion`-Politik
Der Runtime-Interpreter muss **alle ausgelieferten `schemaVersion`** gepinnter Definitionen verstehen
(versionierte Parser; das Meta-Schema dispatcht nach `schemaVersion`). Breaking-Bumps sind verboten,
solange ein Ticket eine ältere Version pinnt.

---

## 4. Versionierung: Entwurf / Vorschau / Release

**Kernregel: Jedes Ticket pinnt seine Prozessversion** (`process_key` + `process_version`).
Zustände: `draft` → `published` → `archived`.

**Invarianten (im Handler erzwungen, nicht nur Prosa):**
1. **Unveränderlichkeit:** `definition_json` ist **nur** schreibbar, solange `status='draft'` **und** kein
   Ticket `(key,version)` pinnt. `publish` friert die Version für immer ein; `archived` ist read-only.
   `PUT`/`:publish` antworten `409/422`, wenn nicht `draft`. → schließt das rückwirkende Freilegen (Rev. 1-Risiko).
2. **Höchstens eine `published` pro `key`:** über eine **generierte Spalte** `published_marker`
   (`= key` wenn published, sonst `NULL`) mit `UNIQUE` erzwungen (MariaDB kann keinen Partial-Index).
3. **Atomarer, nebenläufigkeitssicherer Release:** `conn.begin()` + `SELECT … FOR UPDATE` über alle
   Zeilen des `key`, dann Flip. `:publish` ist **guarded + idempotent** (nur `draft→published`;
   Wiederholung = No-op-Erfolg; `archived` terminal). Optimistic Concurrency via `If-Match`/ETag →
   `409 PROCESS_VERSION_CONFLICT`.
4. **Draft-Politik:** höchstens **ein** offener Draft pro `key` (Create liefert den bestehenden), **oder**
   `base_version` merken und Publish rebasen/ablehnen, wenn `base_version ≠ aktuell published` (Lost-Update-Schutz).
5. **Löschschutz:** eine Version ist nur löschbar, wenn **kein** Ticket sie referenziert
   (Pre-Delete-Count bzw. FK `ON DELETE RESTRICT`). Archivieren ändert **nur** `status`.
6. **Import:** Ziel-`key` muss vom Aufrufer bestätigt werden; `422` bei Kollision — **nie** den `key`
   allein aus (unvertrautem) Import-JSON ableiten.

**Vorschau = Client-Simulation:** Der Editor rendert den Entwurf im Browser (Formular + Ablauf), ohne
Ticket, ohne Mail/Automationen. **Neue** Tickets nutzen immer die aktuelle `published`-Version.
**Export** = `definition_json`; **Kopie** = Klon unter neuem `key` als `draft`.

```
draft v3 ──(:publish, FOR UPDATE)──▶ published v3 ;  published v2 ──▶ archived (eingefroren)
laufende Tickets bleiben auf ihrer gepinnten Version — unverändert
```

---

## 5. Sichtbarkeit (harte Anforderung) — als erzwungene Invariante

**Invariante:** *Jeder wertetragende Ausgabekanal* passiert den Feld-Sichtbarkeits-/Confidential-Filter —
nicht nur `description`/`values_json`. Rev. 1 war hier lückenhaft:

1. **Ein Filter, alle Kanäle.** Auch **History-`details`** (heute steht `salary` unstripped im
   `ticket_updated`-Event) und **`runtime_json`** laufen durch den Filter — oder History speichert nur
   Feld-Keys/Diff-Marker und löst Werte über den gefilterten Lesepfad auf. `runtime_json` bekommt ein
   **striktes Pydantic-Schema, das strukturell keine Feldwerte halten kann**; `notify`/Templates dürfen
   keine gerenderten Feldwerte in Runtime schreiben.
2. **Vollsicht ist explizit**, nicht abgeleitet: Phase-Flag **`grantsFullView`** (Default `false` →
   Default-Deny). Vollsicht = Aufsichtsrechte ∪ Owner ∪ Beobachter ∪ aktive Zuständige von
   `grantsFullView`-Phasen. Eingeschränkt = Mitglieder eines `departments`-Eintrags, begrenzt auf dessen
   Feldmenge. Terminale Tickets (archived/rejected) entziehen Bearbeitern die Vollsicht.
3. **Schreibschutz (per-Feld-Merge):** Bei PATCH wird aus der gepinnten Definition die
   *sichtbare-und-editierbare* Feldmenge des Schreibers berechnet; Start = gespeicherte Werte, nur erlaubte
   Writes werden angewandt, der Rest verworfen (verborgene Felder immer aus dem Bestand). Damit kann eine
   Fachabteilung `it.hostname` schreiben, während `personal.salary` im selben Payload ignoriert wird —
   der alte „Restricted-Viewer darf gar nicht PATCHen"-Guard passt nicht mehr.
4. **Gruppen als ID.** Umbenennen ist damit sicher; **Löschen** einer referenzierten Gruppe wird
   **blockiert/auditiert** (Scan über `definition_json`, analog `is_required_group_name`). **Admin-Fallback:**
   `PERM_ADMIN` kann (auditiert) Confidential-Felder lesen, deren `visibleToGroups` nicht mehr auflösbar ist —
   fail-restrictive darf nicht = permanenter Datenverlust sein (rechtlich relevante Onboarding-Daten).
5. **Version-Pinning:** Sichtbarkeit wird gegen die **gepinnte** Version aufgelöst; ein Release legt nie
   rückwirkend Felder offen (kombiniert mit §4-Unveränderlichkeit).
6. **Default-Deny + fail-restrictive:** unbekannter/fehlerhafter Zustand → *mehr* verbergen.
7. Admin-/Definitions-Endpunkte über `PERM_ADMIN`/`_require_admin` + Audit (§8).
8. **Regressionstests (Baustufe 3):** ein Restricted-Viewer-Serialisat trägt unter **keinem** Key von
   `values_json`, `runtime_json` oder History einen Confidential-/Fremdabteilungs-Wert.

---

## 6. Per-Phasen-Features: erweiterbares Automations-Registry

Eine **Automation** = `trigger` → optionaler `guard` (DSL) → `action`. Bewusst als **Registry** gebaut,
damit komplexe Features (wie die Eskalation) **ohne Engine-Umbau** nachrüstbar sind:

- **Trigger-Registry:** `on_enter · on_exit · on_field_change · timer` (`after`, optional `repeat`, ISO-8601).
- **Action-Registry (code-hinterlegte Handler):** `notify · escalate · set_field · set_priority ·
  set_status · assign_sequence · require_attachment · auto_advance · spawn_process`. Neue Actions = neuer
  registrierter Handler, kein Format-Bruch.
- **Empfänger-Resolver-Registry (`to`):** `responsible · owner · watchers · group:<id>`.
  **`supervisor` ist ein späterer Resolver** (Quelle noch offen, §13) — das Modell trägt ihn bereits.
  **Pflicht-Fallback:** jeder `notify`/`escalate` hat einen garantierten Fallback-Empfänger
  (z. B. `TICKET_MAIL`/Owner-Gruppe), damit eine Aktion **nie stumm ins Leere** läuft.

### 6.1 Condition-DSL (geteilt, autoritativ im Backend)
Für `visibleWhen`, `requiredWhen`, Abteilungs-`when`, Phase-`constraints` und Automation-`guard`:
```jsonc
{ "==": ["fuhrpark.car", "Ja"] }   { "truthy": "it.software.datev" }
{ "in": ["personal.department", ["IT","HR"]] }
{ "and": [ … ] }  { "or": [ … ] }  { "not": { … } }
```
Refs sind Dot-Paths in `values_json`. **Auswertung gegen die serverseitig gemergten Werte** (nach dem
Confidential-Preserve-Schritt), nie gegen den Roh-Request. Wertproduzierende Formen (für `computed`/`set_field`)
sind eine eigene, ebenfalls serialisierbare Ausdrucksform.

*Eskalations-Beispiel (später):* `reminder-7d` (`after P7D, repeat P7D` → `notify responsible`) +
`escalate-14d` (`after P14D` → `escalate supervisor`, mit Pflicht-Fallback).

---

## 7. Scheduler & Timer-Semantik (exakt)

**Ausführung:** ein **eigener** asyncio-Task mit `SCHEDULER_INTERVAL` (Default 15 min), **gated durch
`RUN_SCHEDULER`** (genau eine Instanz sweept). `user_sync_background` bleibt **ungegated** (läuft pro Instanz
weiter). **Sweep + Mail laufen off-event-loop** (`asyncio.to_thread`/Executor bzw. eigener Thread mit eigener
DB-Connection) — sonst blockiert synchrones pymysql/`requests.post(timeout=30)` alle HTTP-Requests.
**Korrektheitsgarantie gegen Doppelfeuern ist der Idempotenz-Ledger, nicht `RUN_SCHEDULER`.**

**Fälligkeit deterministisch aus `entered_at`** (nicht aus `fired_at` → kein Drift):
`occurrence = floor((now − entered_at − after − accumulated_pause) / repeat) + 1`, `occurrence 1` = erste Periode.
Der Ledger-Marker trägt diese berechnete `occurrence`.

**Missed-Window-Politik:** One-Shot-Timer feuern einmal, wenn Schwelle überschritten und kein Marker existiert.
Repeat-Timer machen **Fire-once-Catch-up** (nur die zuletzt fällige Occurrence feuern, für übersprungene
Occurrences unterdrückte Marker schreiben) — **nie** Loop-Feuern (kein Mail-Sturm). Per-Sweep-Cap nur als
Sicherung.

**Pause:** ein akkumuliertes `sla_paused_ms` im Runtime (bei Pause-Ende fortgeschrieben); `pausesSla`-Status
(z. B. `waiting_contract`) zählt **nicht** mit. Ein bloßes Bool reicht nicht — sonst feuern nach 30 Tagen
Pause alle Timer sofort.

**Reopen ohne Race:** Ledger-`UNIQUE(ticket_id, phase_key, epoch, automation_id, occurrence)`. Reopen **erhöht
nur die `epoch`** — kein Löschen von Markern (keine Race mit dem laufenden Sweeper, Marker bleiben für Audit).
Sweeper-Aktion + Marker-Insert in **einer** INSERT-first-Transaktion.

**Performance:** indizierte Spalte **`next_timer_due_at DATETIME`** auf `tickets` (Minimum der fälligen Timer der
aktuellen Phase; `NULL` für terminal/ohne Timer) → Sweep = `WHERE next_timer_due_at <= UTC_NOW()` statt
Full-Scan + JSON-Parse aller aktiven Tickets.

**Zeit:** eigener **tz-aware-UTC-Writer** für `entered_at`/`next_timer_due_at` (nie `_now_iso()`); vor der
Arithmetik Awareness sicherstellen.

---

## 8. REST-API (ersetzt v1 in-place; `view`/`overview` entfallen)

**v1 wird ersetzt, nicht parallel betrieben** — die `tickets`-Tabelle wird in-place umgewidmet (§10), ein
Parallelbetrieb bräuchte einen Kompatibilitäts-Shim (verboten, Anf. #4). Der Checkpoint bewahrt das Alt-System.

Ressourcenorientiert, Plural-Substantive, Nicht-CRUD als **Custom Method** (`:verb`). Envelope wie bestehend
(`DataResponse`/`ListResponse`/`Meta`), Fehler über den neuen Envelope (§9).

**Prozess-Definitionen** — **alle Mutationen `PERM_ADMIN` + Audit**; Draft/Version-Reads für Admin/Manage:
`GET /processes` (veröffentlichter Katalog, für Authentifizierte) · `POST /processes` (Draft) ·
`GET /processes/{key}` · `GET /processes/{key}/versions` · `GET /processes/{key}/versions/{v}` ·
`PUT /processes/{key}/versions/{v}` (nur Draft) · `POST /processes/{key}/versions/{v}:publish` ·
`POST /processes/{key}:duplicate` · `GET /processes/{key}/versions/{v}:export` · `POST /processes:import`.

**Tickets (Instanzen):**
`GET /tickets` (Filter/Sort/Pagination) · `POST /tickets` (`processKey` + Werte, validiert) ·
`GET /tickets/{id}` (nach Sichtbarkeit gefiltert) · `PATCH /tickets/{id}` (validiert) ·
`POST /tickets/{id}:advance` (Body: nächste:r Zuständige:r bei frei zuweisbaren Phasen) ·
`POST /tickets/{id}:reject` · `:reopen` (Body: `phase_index`, Abteilungs-open/done-Map, Assignee) ·
`POST /tickets/{id}/departments/{groupId}:complete` / `:reject` / `:skip` ·
`GET /tickets/{id}/history` · Sub-Collections: `…/watchers` (GET/POST/DELETE), `…/comments` (append-only
Nachtrag, mailt Beteiligte), `…/attachments` (bereits gebaut).

**Ich-bezogen:** `GET /me`, `GET /me/tickets`.

---

## 9. Server-Validierung (zwei Pässe + Fehler-Envelope)

**Zwei getrennte Momente** (Rev. 1 vermischte sie):
1. **Wert-Form (bei `POST`/`PATCH`, nur über gesendete Felder):** Typ, Optionen, `pattern`, `min/max`,
   Datumsgrenzen — und **unbekannter Dot-Path → `422`** (schließt das Free-Blob-Schlupfloch: „alles wird
   angenommen"). Blockiert **nicht** das Speichern eines halbfertigen Entwurfs.
2. **Phasen-Abschluss (nur bei `:advance` und Department-`:complete`):** `required` + `requiredWhen` +
   Phase-`constraints` für die Feldmenge der aktuellen Phase.

**Definition selbst:** beim Speichern/Import gegen ein `ProcessDefinition`-**Meta-Schema** (Pydantic):
Feld-Keys eindeutig, alle `ref`s existieren, Widgets/`view`/`enterStatus`/DSL wohlgeformt, `constraints` gültig.

**Fehler-Contract (in Baustufe 1, vor dem ersten 422):** `ErrorResponse` um optionales
`fields: [{path, code, message}]` erweitern; `ErrorCode.VALIDATION_FAILED`, `PROCESS_VERSION_CONFLICT` (409),
`PROCESS_NOT_FOUND` (404). **Ein** `@app.exception_handler(RequestValidationError)` + `HTTPException`-Handler
normalisiert beide 422-Quellen in diesen Envelope (heute divergieren ~3–4 Fehlerformen im Frontend).

**Anhang-Pflicht** wird gegen die **attachments-Tabelle** geprüft (via `field_key`-Verknüpfung), nicht gegen
`values_json`; `require_attachment`-Automation und Pflicht-Attachment-Feld sind **ein** Mechanismus (nicht zwei).

---

## 10. Datenmodell

- **`process_definitions`** — `id`, `key`, `version`, `status(draft|published|archived)`, `name`,
  `definition_json LONGTEXT`, `published_marker` (generiert: `key` wenn published sonst `NULL`, **UNIQUE**),
  `base_version`, `created_by(_name)`, `created_at`, `published_at`; `UNIQUE(key,version)`, `INDEX(key,status)`.
- **`tickets`** (umgewidmet) — `+ process_key`, `+ process_version` (Pin, `ON DELETE RESTRICT`),
  `values_json` (Feldwerte, ex-`description`), `runtime_json` (**striktes Schema, keine Feldwerte**:
  Phasen-Status, `current_index`, `entered_at` je Phase, `epoch`, `sla_paused_ms`, Flags),
  `+ next_timer_due_at DATETIME` **indiziert**.
- **`process_timer_fires`** — `id`, `ticket_id`, `phase_key`, `epoch`, `automation_id`, `occurrence`,
  `fired_at`, `suppressed`; `UNIQUE(ticket_id, phase_key, epoch, automation_id, occurrence)`.

DDL idempotent (`init_db()`/Lifespan-`ensure_table`). Timestamps für SLA tz-aware UTC.

---

## 11. Baustufen (jede ein Commit → Rücksprungpunkt)

1. **Fundament** — `ProcessDefinition`-Pydantic + Meta-Schema; `process_definitions` mit allen §4-Invarianten
   (Unveränderlichkeit, `published_marker` UNIQUE, `FOR UPDATE`-Release, guarded Publish, Löschschutz);
   Definitions-API **inkl. `PERM_ADMIN`-Gates**; **Fehler-Envelope + Exception-Handler** (§9). Export/Import/Kopie.
2. **Ticket-Runtime** — Create/PATCH/`:advance` gegen gepinnte Version; **Zwei-Pass-Validierung**;
   Phasen-Engine liest Definition; `entered_at`/`next_timer_due_at`-Stempel; neue Ticket-REST (v1 ersetzt).
3. **Sichtbarkeit** — feldbezogen, **alle Kanäle** gefiltert (values/runtime/history), Default-Deny,
   `grantsFullView`, Per-Feld-Schreib-Merge, Gruppen-ID + Löschschutz + Admin-Fallback, **Regressionstests**.
4. **Condition-DSL** — Boolean- + Wert-Ausdrücke, autoritativer Backend-Evaluator (+ Frontend-Spiegel);
   `visibleWhen`/`requiredWhen`/`constraints`/`computed`/Abteilungs-`when`.
5. **Automations + Scheduler** — Registry (Trigger/Action/Resolver), eigener gated Off-Loop-Sweeper,
   Idempotenz-Ledger + Epoch, deterministische Occurrence, Missed-Window, Pause-Akkumulation.
6. **Visueller Editor** — generischer Schema-Formular-Renderer (inkl. `collection`) + Read-only-Renderer,
   Phasen-Ketten-Editor, Entwurf/Vorschau(Client-Sim)/Release-UI, Import/Export.

---

## 12. Bewusste Design-Entscheidungen

- **Linear + benannte Hooks statt n8n-Graph** (System hat ~1 echte Verzweigung: Onboarding-Spawn).
  `spawn_process` als Action; per-Instanz-Zuständigkeit via `responsibility.kind = originator` bzw.
  `spawn_process.assign: {phaseKey → originator}` (P1→P2-Übergabe als Daten).
- **Felder = Single Source of Truth** (Label/Widget/Constraints/Sichtbarkeit an einem Ort).
- **Sicherheit strukturell, nicht per Konvention** — Sichtbarkeits-Invariante über alle Kanäle,
  Versionen unveränderlich, Idempotenz als Korrektheitsgarantie.
- **Erweiterbarkeit als Registry** — neue Trigger/Actions/Resolver ohne Format-/Engine-Bruch.

## 13. Entschieden / später

**Entschieden:** v1 ersetzen (kein v2) · Vorschau = Client-Simulation · Editieren/Releasen nur `PERM_ADMIN` ·
Sweeper-Default 15 min.
**Später (Modell trägt es bereits):** Eskalation an **Vorgesetzte:r** — Quelle des Vorgesetzten-Bezugs
(AD-`manager`-Feld vs. Prozessfeld vs. Gruppe) offen; bei AD-`manager` die Relationen im Lifespan-Cache
mitführen (kein Blocking-Graph-Call im Sweep) und stets Pflicht-Fallback-Empfänger.

---

## 14. Cutover (Rev. 3, 2026-08-12)

Das Alt-System (hartcodierte `TicketType`-Enums, `TICKET_PHASES`,
`ticket_visibility`-Dicts, 10 handgeschriebene Vue-Formulare) wird ENTFERNT. Alle
Prozesse laufen datengetrieben. Es gibt **keine Rückwärtskompatibilität** und
**keine Migration alter Ticket-Daten** – bewusster Neustart.

### 14.1 Der Nachfolge-Prozess ist gestrichen
`spawn_process`, `ResponsibilityKind.originator`, `require_attachment` und
`Action.process` sind **ersatzlos entfernt**. Das zweigeteilte Onboarding
(Einstellung → Onboarding nach Vertragsrücklauf) wird nicht gebraucht.
Damit ist §12 („~1 echte Verzweigung: Onboarding-Spawn") überholt: das Modell ist
jetzt rein linear mit Rücksprung (`approval.onReject = back_to:<phase>`).

`originator` war die gefährlichste dieser Altlasten: der Wert stand in KEINER
`UNIMPLEMENTED_*`-Menge, war im Editor auswählbar und hätte zur Laufzeit eine Phase
ohne jede zuständige Stelle erzeugt.

### 14.2 Was für den Ersatz nachgebaut werden musste
Die 10 Definitionen waren zunächst **um drei Lücken herumgebaut**. Ohne sie wäre
der Cutover ein fachlicher Rückschritt gewesen:

| Fähigkeit | Alt-System | Umsetzung im neuen Format |
|---|---|---|
| Freigabe ohne Login | Mail-Link mit Ja/Nein | `kind=approval` + `ApprovalSpec` |
| Personalnummer | Vergabe je Firma | `widget=server_generated` + `assign` |
| Export (Hotelbuchung) | eigenes PDF-Panel | `view=export`, generisch aus `layout` |
| Fachabteilung frei wählbar (Basis-Ticket) | Auswahl beim Anlegen | `kind=group_from_field` |

**Alle vier `UNIMPLEMENTED_*`-Mengen sind jetzt leer.** Die Ehrlichkeits-Regel
(§ Review) bleibt als *Mechanismus* bestehen: wer künftig einen Schema-Wert ergänzt,
dessen Laufzeit noch fehlt, trägt ihn dort ein – dann lehnt der Server ihn beim
Veröffentlichen ab, statt ihn still zu ignorieren.

### 14.3 Freigabe-Phase: zwei bewusste Abweichungen vom Alt-System
1. **GET hat keinen Seiteneffekt.** Der Mail-Link öffnet eine Bestätigungsseite,
   entschieden wird per POST. Im Alt-System entschied der Klick sofort – Mail-Clients
   und Sicherheits-Scanner laden Links vorab und hätten Aufträge ungewollt freigegeben.
2. **Der Epoch steckt im Token** (`{tid, act, phase, epoch}`). Ohne ihn wäre ein
   alter, noch nicht abgelaufener Link nach einer Wiederaufnahme wieder wirksam.
Einmaligkeit über einen Entscheidungs-Eintrag im Runtime der Phase. Fehlt der
zuständigen Gruppe die Verteiler-Adresse, wird das laut gemeldet (Audit + Verlauf) –
im Alt-System verpuffte es in einem `logger.warning`, und der Auftrag lag unbemerkt.

### 14.4 Nummern-Vergabe hängt am Phasenabschluss, nicht an einer Automation
`assign_sequence` ist als Automation **verboten**: `process_engine.fire()` fängt jede
Action-Exception ab und auditiert sie nur – ein erschöpfter Nummernkreis hätte den
Auftrag stillschweigend ohne Nummer weitergeschaltet. Die Vergabe läuft daher in
`engine.transition` VOR dem Übergang und bricht ihn bei Fehlern ab.
Idempotenz über einen Anspruchs-Ledger: `UNIQUE(ticket, field)` gegen doppelte
Vergabe beim Retry, `UNIQUE(counter, scope, nummer)` macht eine echte Doppelvergabe
zum lauten Fehler statt zu stiller Datenkorruption. Ein Anspruch wird NIE
freigegeben – auch nicht bei Ablehnung oder Wiederaufnahme.

### 14.5 Sichtbarkeit: der Server sagt, was das Formular zeigt
Die Antwort trägt `visible_fields` und `editable_fields` (und `abilities` für die
erlaubten Aktionen). Das Frontend kennt die Gruppen-Mitgliedschaft **nicht** und darf
die Entscheidung nicht nachbauen. Für den Anlege-Dialog, wo noch kein Ticket
existiert, liefert `GET /processes/{key}/field-access` dasselbe für die Start-Phase.
Die Erlaubnisliste überstimmt bewusst auch `isAdmin` und `confidential` – der
Admin-Fallback ist serverseitig schon eingerechnet. Ohne Liste (nur in der
Editor-Vorschau) entscheiden weiter die Gruppen-Regeln des Client-Spiegels.

### 14.6 Einspielen der Definitionen
Die 10 Definitionen liegen **paketiert unter `backend/seeds/processes/`**, nicht in
`docs/` – der Build-Kontext beider Images ist der jeweilige Unterordner, `docs/`
landet in KEINEM Image. Sie referenzieren Gruppen-**Namen**, die der Seeder
case-insensitiv auflöst; er ist **fail-closed** (ein unaufgelöster Platzhalter
validiert zwar, erzeugt aber einen dauerhaft kaputten Prozess: niemand zuständig,
Fachabteilungs-Phase nie abschließbar) und **überschreibt nie** einen vorhandenen
Key – eine vom Admin geänderte Definition setzt ein Seeder nicht zurück.
Die heutigen `create_<typ>`-Rechte werden einmalig in `createPermissions`
übernommen. `may_create` sieht dabei Fachabteilungs- UND AD-Gruppen; ohne letztere
verlöre jede Person das Anlegerecht, die es nur über eine AD-Gruppe hat.

### 14.7 Was ohne Ersatz wegfällt
Ehrlich festgehalten, damit es niemand später als Bug entdeckt:
- **Alte Ticket-Daten sind ohne Oberfläche.** Die Tabellen werden NICHT gedroppt
  (die DB gehört dem Kunden), aber es gibt keinen Lesepfad mehr.
- **`waiting_contract`** bleibt als erlaubter `enterStatus` bestehen, hat ohne den
  zweigeteilten Onboarding-Prozess aber keinen Nutzer mehr.
