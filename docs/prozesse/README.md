# Arbeits-/Referenzkopien von Prozess-Definitionen

Hier liegen **Arbeitskopien** einzelner Prozess-Definitionen zum Nachschlagen,
Weiterbearbeiten und Wieder-Importieren – **kein** Laufzeit- oder Build-Artefakt
(nichts im Code importiert diese Dateien, und `docs/` ist nicht im Docker-Image).

## Unterschied zum mitgelieferten Seed

Nicht verwechseln mit `backend/seeds/processes/` – den **portablen** Seeds, die
per Admin-Aktion „Prozesse einspielen" auf jeder Installation eingespielt werden:

| | `docs/prozesse/` (hier) | `backend/seeds/processes/` |
|---|---|---|
| Gruppen | **konkrete IDs** dieser Instanz (`7c88…` usw.) | **Platzhalter** (`HIER_GRUPPEN_ID_IT_EINSETZEN` …) |
| Zweck | Arbeits-/Copy-out-Kopie der Live-Definition | portabler, getesteter Auslieferungs-Default |
| Wird getestet? | nein | ja (`test_seed_processes.py`, Anzahl fix auf 10) |

## Dateien

- `zugang-beantragen.json` – aktueller Stand des Onboarding-Prozesses
  („Onboarding Mitarbeiter:innen", Export v11: 61 Felder, Phasen
  `erstellung → freigabe → bearbeitung → arbeitsvertrag → vertragsruecklauf →
  durchfuehrung`). Direkt in die eigene Instanz re-importierbar, da mit den echten
  Gruppen-IDs. Wird hier gepflegt, damit die Definition nicht bei jeder Anpassung
  neu aus dem Chat kopiert werden muss.
