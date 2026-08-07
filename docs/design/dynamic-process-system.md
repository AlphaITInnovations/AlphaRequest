# Design: Dynamisches Prozess- & Workflow-System

> **Status:** Entwurf zur Review · **Branch:** `feature/dynamic-processes` ·
> **Checkpoint:** Tag `checkpoint/pre-dynamic-processes` (Rücksprungpunkt)
> **Grundsatz:** Neustart ohne Rückwärtskompatibilität — Alt-Auftragstypen werden
> nicht migriert. Der alte Stand bleibt über den Checkpoint erreichbar.

## 0. Ziel

Aufträge (Prozesse) werden von **Code** zu **Daten**. Ein Prozess — seine Phasen,
Felder, Pflichtregeln, Sichtbarkeit und automatischen Aktionen — wird als **JSON**
gespeichert, ist **im Frontend visuell bearbeitbar**, kann **exportiert/importiert/
kopiert** werden, läuft über ein **Entwurf-/Release-System** (nie direkt am Live-Prozess),
und trägt **flexible Per-Phasen-Features** wie zeitbasierte Eskalation. Dazu eine
**saubere REST-API** und **echte Server-seitige Validierung**.

---

## 1. Anforderungen (aus dem Auftrag)

1. **Prozess-Format (JSON)** — ein Prozess ist ein serialisierbares Dokument; Export / Import / Kopie.
2. **Visueller Editor** — Phasen im Frontend anlegen, verbinden, konfigurieren.
3. **Entwurf → Vorschau → Release** — Änderungen laufen nie sofort live; Versionierung.
4. **Keine Rückwärtskompatibilität** — sauberer Neustart, keine Migration von Alt-Tickets.
5. **Flexible Per-Phasen-Features** — z. B. Eskalation: 7 Tage unbearbeitet → erinnern, 14 Tage → an Vorgesetzte:n eskalieren; frei konfigurierbar.
6. **Saubere API** — weg von `view`/`overview`; ressourcenorientiertes Schema nach Best Practice.
7. **Server-Validierung** — Eingaben werden serverseitig gegen das Feld-Schema geprüft (heute: „alles wird angenommen").

---

## 2. Ausgangslage im Code (verifiziert)

Relevante Fundstücke, die das Design prägen:

- **Es gibt bereits einen Hintergrund-Loop:** [app_lifespan.py:72](../../backend/core/app_lifespan.py) startet
  `asyncio.create_task(user_sync_background())` mit `while True … asyncio.sleep(interval)` —
  synct AD-User/-Gruppen und ruft `prune_stale()` für Sessions. **Ein Prozess-Timer-Sweeper
  kann sich hier anhängen.** ⚠️ Der Loop läuft **pro Instanz** (dev *und* prod, ggf. mehrere
  Worker) → Gefahr doppelter Eskalationen (siehe §7).
- **Zeitstempel sind inkonsistent:** History schreibt **Berlin-Lokalzeit**
  ([ticket_history.py:24](../../backend/services/ticket_history.py)), Audit/Health nutzen **UTC**.
  Für SLA-Rechnen brauchen wir *eine* Basis → **intern konsequent UTC**, Anzeige in Berlin.
- **Phasen-Eintrittszeit** ist heute nur indirekt (über History-Events) ableitbar, nicht als
  Feld gespeichert → das neue Runtime-Modell speichert `entered_at` pro Phase explizit.
- **Sichtbarkeit** läuft heute durch **eine** Server-Naht (`ticket_visibility.filter_description`);
  diese Eigenschaft behalten wir bei (single point of enforcement).
- **Mail** wird synchron im Request versendet ([microsoft_mail.py](../../backend/services/microsoft_mail.py));
  aus dem Scheduler senden wir außerhalb eines Requests (App-Token, keine Session-Abhängigkeit).

---

## 3. Das Prozess-Format (`ProcessDefinition`)

Ein Prozess ist **ein JSON-Dokument**. Kernidee: **Felder werden genau einmal definiert**
(Katalog, Single Source of Truth); Phasen **referenzieren** Felder und legen pro Phase
Sichtbarkeit/Pflicht fest. Sichtbarkeit steckt **im Feld** — damit gibt es keine doppelten
Dot-Paths zwischen Frontend und Backend (ein Hauptproblem des Alt-Systems).

```jsonc
{
  "schemaVersion": 1,
  "key": "einstellung",                 // stabiler Prozess-Schlüssel
  "name": "Einstellung Mitarbeiter:in",
  "description": "Von den Einstellungsdaten bis zum Vertragsversand.",
  "icon": "📝",

  // ── Feld-Katalog (jedes Feld genau einmal) ─────────────────────────────
  "fields": [
    { "key": "base.first_name", "label": "Vorname", "widget": "text" },
    { "key": "base.contract_company", "label": "Firma lt. Vertrag", "widget": "company" },
    { "key": "fuhrpark.car", "label": "Dienstwagen?", "widget": "select",
      "options": ["Ja", "Nein"] },
    { "key": "personal.salary", "label": "Gehalt & Konditionen", "widget": "textarea",
      // Sichtbarkeit liegt IM Feld → keine doppelten Pfade, Gruppen als ID
      "visibility": { "confidential": true, "visibleToGroups": ["grp_sekretariat_gl"] } }
  ],

  // ── Phasen (Reihenfolge = Ablauf; linear + optionale benannte Hooks) ────
  "phases": [
    {
      "key": "erstellung",
      "label": "Erstellung",
      "kind": "start",                  // start | task | approval | review | end
      "responsibility": { "kind": "owner" },
      "view": "form",                   // Whitelist: form | readonly | approval | export | review
      "enterStatus": "in_progress",
      "fields": [
        { "ref": "base.first_name", "mode": "editable", "required": true },
        { "ref": "base.contract_company", "mode": "editable", "required": true },
        { "ref": "personal.salary", "mode": "editable",
          "requiredWhen": { "==": ["base.contract_type", "fest"] } }   // Condition-DSL
      ]
    },
    {
      "key": "durchfuehrung",
      "label": "Durchführung Fachabteilungen",
      "kind": "review",
      "responsibility": {
        "kind": "departments",
        "rule": [                        // welche Abteilungen, ggf. bedingt (DSL)
          { "group": "grp_it" },
          { "group": "grp_fuhrpark", "when": { "==": ["fuhrpark.car", "Ja"] } }
        ]
      },
      "view": "review",
      "enterStatus": "in_request",
      "fields": [ { "ref": "base.first_name", "mode": "readonly" } ],

      // ── Flexible Per-Phasen-Features (siehe §6) ──────────────────────
      "automations": [
        { "id": "reminder-7d",
          "trigger": { "type": "timer", "after": "P7D", "repeat": "P7D" },
          "guard": { "not": { "truthy": "_flags.done" } },
          "action": { "type": "notify", "to": "responsible", "template": "reminder" } },
        { "id": "escalate-14d",
          "trigger": { "type": "timer", "after": "P14D" },
          "action": { "type": "escalate", "to": "supervisor", "template": "escalation" } }
      ]
    }
  ],

  // ── Optional: prozessweite Automatisierungen (Trigger on_enter/exit/field) ─
  "automations": []
}
```

### 3.1 Feld-Widgets (Whitelist)
`text · textarea · number · date · select · multiselect · checkbox · checkbox-group ·
user · company · group · attachment`. Neue Widget-Typen sind ein bewusster Code-Schritt
(Frontend-Renderer + Server-Validator) — der Editor kann nur aus der Whitelist wählen.

### 3.2 Warum Sichtbarkeit ins Feld gehört
Im Alt-System lagen Feld-Pfade doppelt (Frontend-`RULES` **und** `ticket_visibility`),
mit stiller Desync-Gefahr. Neu: das Feld *ist* die einzige Quelle für Label, Widget,
Validierung **und** Sichtbarkeit. Der Server filtert weiter zentral (§5), liest die
Regel aber aus dem Feld der **gepinnten** Prozessversion.

---

## 4. Entwurf / Vorschau / Release (Versionierung)

**Kernregel: Ein Ticket „pinnt" die Prozessversion, unter der es erstellt wurde.**
Damit ändert ein Release *nie* laufende Tickets — es löst zugleich das größte
Sicherheits-Risiko (rückwirkende Feld-Freilegung), das die Vorab-Analyse gefunden hatte.

**Zustände einer Definition:** `draft` → `published` → `archived`.
- Pro `key` gibt es **höchstens eine** `published`-Version (die „Live"-Version).
- **Bearbeiten** erzeugt/ändert eine `draft`-Version (`version = max+1`).
- **Release** ist eine atomare Transaktion: `draft → published`, alte `published → archived`.
- **Vorschau:** Der Editor rendert den Entwurf live (Formular + Ablauf). Optional ein
  **Testlauf** — ein als `isPreview` markiertes Wegwerf-Ticket gegen den Entwurf, bei dem
  **Mails/Automationen unterdrückt** werden und das automatisch aufräumbar ist.
- **Neue Tickets** verwenden immer die aktuelle `published`-Version.
- **Export** = `definition_json` ausgeben. **Import** = neuer `draft` aus JSON (gegen
  Meta-Schema validiert). **Kopie** = Klonen unter neuem `key` als `draft`.

```
draft v3  ──(Release)──▶  published v3
                          published v2 ──▶ archived
laufende Tickets: bleiben auf ihrer gepinnten Version (v1/v2) — unverändert
```

---

## 5. Sichtbarkeit (die harte Anforderung)

Enforcement bleibt **strukturell identisch** zum Alt-System — nur die *Regelquelle*
wandert von Python-Dicts in die Definition:

1. **Ein Server-Filter** bleibt der einzige Ausgabepunkt für Feldwerte; alle Lesepfade
   laufen hindurch. Kein neuer Lesepfad ohne diesen Filter.
2. **Default-Deny + fail-restriktiv:** unbekannter/fehlerhafter Zustand → *mehr*
   verbergen, nie weniger. Ein Feld ohne explizite Sichtbarkeitsregel ist für alle
   Beteiligten mit Vollsicht sichtbar; ein `confidential`-Feld nur für `visibleToGroups`.
3. **Gruppen als ID**, nicht als Name (Umbenennen bricht dann nichts).
4. **Version-Pinning:** Sichtbarkeit wird gegen die *gepinnte* Version aufgelöst → ein
   Release legt nie rückwirkend Felder offen.
5. **Schreibschutz:** ein Client, der ein Feld nicht sehen darf, kann es per PATCH weder
   setzen noch leeren (server-seitiger Preserve-Guard, wie heute `preserve_confidential`).
6. ⚠️ **Zweiter Ausgabekanal beachten:** Der Runtime-/Workflow-Zustand darf **keine
   Feldwerte** enthalten, sonst umgeht er den Filter. Runtime speichert nur Phasen-Status,
   Zeitstempel, Flags — nie Feld-Inhalte.
7. Admin-Endpunkte weiter über `PERM_ADMIN`/`require_admin` + Audit.

---

## 6. Flexible Per-Phasen-Features: Automations

Eine **Automation** ist ein deklarativer Eintrag (phasen-lokal oder prozessweit):
`trigger` → optionaler `guard` (Condition-DSL) → `action`.

**Trigger:** `on_enter` · `on_exit` · `on_field_change` · **`timer`** (`after`, optional `repeat`, ISO-8601-Dauer).
**Actions (Whitelist, code-hinterlegte Handler):** `notify` · `escalate` · `set_priority` ·
`set_status` · `require_attachment` (blockiert Weiterschalten) · `auto_advance` · `spawn_process`.
**Empfänger (`to`):** `responsible` · `owner` · `watchers` · `group:<id>` · `supervisor`.

### 6.1 Dein Eskalations-Beispiel, konkret im Modell
Zwei `timer`-Automations an der Phase (siehe JSON §3):
- `reminder-7d`: `after P7D, repeat P7D` → `notify responsible` (Erinnerung, wöchentlich).
- `escalate-14d`: `after P14D` → `escalate supervisor` (an Vorgesetzte:n, einmalig).

**Laufzeit (Sweeper):** ein periodischer Task (im bestehenden Loop, §2) findet alle
**aktiven** Tickets, deren aktuelle Phase `entered_at` eine noch nicht ausgelöste
Timer-Schwelle überschreitet, prüft den `guard`, führt die `action` aus und schreibt einen
**Fire-Marker** (Idempotenz, §7). „Alle 7 Tage" = nächste Fälligkeit aus letztem Fire.

### 6.2 Condition-DSL (geteilt)
Ein kleines, serialisierbares Format — genutzt für `requiredWhen`, Feld-Sichtbarkeit,
bedingte Abteilungen (`when`) und Automation-`guard`. Auswertung **autoritativ im Backend**,
gespiegelt im Frontend (UX).
```jsonc
{ "==": ["fuhrpark.car", "Ja"] }
{ "truthy": "it.software.datev" }
{ "in": ["personal.department", ["IT", "HR"]] }
{ "and": [ {…}, {…} ] }   { "or": [ … ] }   { "not": {…} }
```
Refs sind Dot-Paths in die Feldwerte des Tickets.

---

## 7. Zeitgesteuerter Auswerter — die Fallstricke (bewusst adressiert)

| Risiko | Lösung im Design |
|---|---|
| **Doppel-Feuern** (dev+prod, mehrere Worker am selben Loop) | (a) **Idempotenz-Ledger** `process_timer_fires` mit `UNIQUE(ticket_id, phase_key, automation_id, occurrence)` — ein zweiter Insert schlägt fehl, Aktion läuft nur einmal. (b) Sweeper nur aktiv bei `config.RUN_SCHEDULER` → genau **eine** Instanz sweept. |
| **Reopen setzt die Uhr** | Bei (Wieder-)Eintritt einer Phase `entered_at` neu stempeln **und** deren Fire-Marker löschen → Eskalation startet im neuen Zyklus sauber. |
| **Terminale/pausierte Tickets** | `archived`/`rejected` überspringen. `waiting_contract` & Co. bekommen ein `pausesSla`-Flag → SLA läuft nicht weiter. |
| **Zeitzonen** | Intern **UTC** (auch History darauf vereinheitlichen), Anzeige Berlin. `entered_at` als tz-aware UTC. |
| **Mail-Sturm** | Idempotenz verhindert Wiederholungen; zusätzlich globaler Sicherungs-Cap pro Sweep. |
| **Mail aus Hintergrund** | App-Token statt Session; Empfänger server-seitig auflösen; Mail-Inhalt respektiert Sichtbarkeit (keine `confidential`-Felder in den Body). |

---

## 8. Saubere REST-API (ersetzt `view`/`overview`)

Ressourcenorientiert, Substantive im Plural, Nicht-CRUD-Aktionen als **Custom Method**
(`:verb`, Google-AIP-Stil). Neuer Namespace **`/api/v2`** während des Aufbaus (sauberer
Schnitt, kein Halbzustand); nach Cutover kann v1 entfallen.

**Prozess-Definitionen**
| Methode & Pfad | Zweck |
|---|---|
| `GET /processes` | Katalog der veröffentlichten Prozesse |
| `POST /processes` | Neuen Prozess anlegen (als `draft`) |
| `GET /processes/{key}` | Aktuelle veröffentlichte Definition |
| `GET /processes/{key}/versions` | Alle Versionen (draft/published/archived) |
| `GET /processes/{key}/versions/{v}` | Bestimmte Version |
| `PUT /processes/{key}/versions/{v}` | Entwurf bearbeiten |
| `POST /processes/{key}/versions/{v}:publish` | **Release** (draft → published) |
| `POST /processes/{key}:duplicate` | Kopieren (neuer key, draft) |
| `GET /processes/{key}/versions/{v}:export` | JSON-Export |
| `POST /processes:import` | JSON-Import → draft |

**Tickets (Instanzen)**
| Methode & Pfad | Zweck |
|---|---|
| `GET /tickets` | Liste mit Filter/Sort/Pagination (ersetzt *overview*) |
| `POST /tickets` | Erstellen (`processKey` + Feldwerte) — **server-validiert** |
| `GET /tickets/{id}` | Ein Ticket (ersetzt *view*) — Antwort nach Sichtbarkeit gefiltert |
| `PATCH /tickets/{id}` | Feldwerte ändern — **server-validiert** |
| `POST /tickets/{id}:advance` | Aktuelle Phase abschließen / weiterschalten |
| `POST /tickets/{id}:reject` · `:reopen` | Ablehnen / erneut öffnen |
| `POST /tickets/{id}/departments/{groupId}:complete` | Fachabteilung abschließen |
| `GET /tickets/{id}/history` | Verlauf |
| `… /tickets/{id}/attachments` | Anhänge (bereits gebaut) |

**Ich-bezogen** (ersetzt Teile von `dashboard`): `GET /me`, `GET /me/tickets` (meine Arbeit).

Antworten einheitlich im bestehenden Envelope (`DataResponse`/`ListResponse` + `Meta`),
Fehler über `api_error`/`ErrorCode`.

---

## 9. Server-Validierung

Zwei Ebenen, beide über **Pydantic**:
1. **Definition** — beim Speichern/Import gegen ein `ProcessDefinition`-Meta-Schema
   validieren (Feld-Keys eindeutig, `ref`s existieren im Katalog, Widgets aus Whitelist,
   Phasen-`view`/`enterStatus` aus Whitelist, DSL-Ausdrücke wohlgeformt). Malformed → `422`.
2. **Ticket-Eingaben** — der Server baut aus dem **Feld-Schema der gepinnten Version** einen
   dynamischen Validator: Typ, Pflicht (inkl. `requiredWhen` via DSL), erlaubte Optionen,
   Pattern, min/max. Verstoß → `422` mit `fields[]`-Detail. **Ersetzt „alles wird angenommen".**

---

## 10. Datenmodell (neue Tabellen)

- **`process_definitions`** — `id`, `key`, `version`, `status(draft|published|archived)`,
  `name`, `definition_json LONGTEXT`, `created_by(_name)`, `created_at`, `published_at`;
  `UNIQUE(key, version)`, `INDEX(key, status)`.
- **`tickets`** (angepasst) — `+ process_key`, `+ process_version` (Pin); `values_json`
  (Feldwerte, früher `description`); `runtime_json` (Phasen-Status, `current_index`,
  **`entered_at` pro Phase**, `rejected`, Flags). **Nie Feldwerte im Runtime** (§5.6).
- **`process_timer_fires`** — `id`, `ticket_id`, `phase_key`, `automation_id`, `occurrence`,
  `fired_at`; `UNIQUE(ticket_id, phase_key, automation_id, occurrence)` (Idempotenz).

DDL idempotent in `init_db()` bzw. Lifespan-`ensure_table` (wie bestehend).

---

## 11. Baustufen (jede ein Commit → weiterer Rücksprungpunkt)

1. **Format & Fundament** — `ProcessDefinition`-Pydantic-Modell + Meta-Schema-Validierung,
   `process_definitions`-Tabelle, Entwurf/Version/Release, Export/Import/Kopie, Definitions-API.
2. **Ticket-Runtime auf Definitionen** — Erstellen/PATCH/Advance gegen gepinnte Version;
   **Server-Feldvalidierung** aus dem Schema; Phasen-Engine liest Definition; `entered_at`-Stempel;
   neue Ticket-REST-API.
3. **Sichtbarkeit im Format** — feldbezogene Sichtbarkeit/Confidential, zentral server-durchgesetzt,
   Default-Deny, Gruppen-IDs, Schreibschutz.
4. **Condition-DSL** — serialisierbares Format + autoritativer Backend-Evaluator (+ Frontend-Spiegel);
   für `requiredWhen`, Feld-Sichtbarkeit, bedingte Abteilungen, Automation-Guards.
5. **Automations + Scheduler** — Automation-Modell, `on_enter/exit/field_change` + `timer`-Sweeper
   mit Idempotenz-Ledger, Eskalations-Actions; Fallstrick-Behandlung (§7).
6. **Visueller Editor (Frontend)** — generischer Schema-Formular-Renderer + Read-only-Renderer,
   visueller Phasen-Ketten-Editor, Entwurf/Vorschau/Release-UI, Import/Export.

> Reihenfolge folgt den Abhängigkeiten: Felder+Sichtbarkeit+Validierung sind Fundament,
> Automations bauen auf `entered_at`+DSL auf, der Editor kommt zuletzt (billig, weil alle
> Modelle stehen). Sichtbarer Fortschritt schon ab Stufe 2.

---

## 12. Bewusste Design-Entscheidungen

- **Linear + benannte Hooks statt n8n-Graph.** Das reale System hat genau eine Verzweigung
  (Onboarding-Spawn); ein freier Knoten-Graph wäre Overkill. Ablauf = geordnete Phasenkette;
  echte Nebenwirkungen (`spawn_process`) als Automation-Action. Ein expliziter Kanten-/Branch-
  Typ bleibt als spätere Option offen, falls je eine zweite echte Verzweigung entsteht.
- **Felder als Single Source of Truth** (Label/Widget/Validierung/Sichtbarkeit an einem Ort).
- **Version-Pinning** löst Migrations- und Sichtbarkeits-Risiken by design.
- **Genau ein Sweeper** (`RUN_SCHEDULER`) + Idempotenz-Ledger gegen Doppel-Aktionen.

## 13. Offene Punkte für dich

1. **`/api/v2` neu** oder **`/api/v1` ersetzen**? (Empfehlung: v2 während des Baus, dann Cutover.)
2. **`supervisor` (Vorgesetzte:r)** — woher kommt die Beziehung? AD-Manager-Feld, ein Feld im
   Prozess, oder Gruppen-basiert? (Betrifft `escalate to: supervisor`.)
3. **Sweeper-Takt** — alle wie viele Minuten? (SLA in Tagen → z. B. alle 15 min reicht üppig.)
4. **Testlauf-Vorschau** — echtes Wegwerf-Ticket (mit Aufräumen) oder rein clientseitige Simulation?
5. **Rollen im Editor** — wer darf Prozesse bearbeiten/releasen (nur Admin, oder eigene Rolle)?
