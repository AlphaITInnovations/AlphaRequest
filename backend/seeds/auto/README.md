# Auto-verwaltete Prozesse

Jede `*.json` in **diesem** Ordner ist ein **auto-verwalteter** Prozess:

- Beim Start der Anwendung wird er automatisch **angelegt** (falls noch nicht
  vorhanden) bzw. **aktualisiert** – eine Änderung an der JSON wird als **neue
  Version** veröffentlicht (die alte Version bleibt für laufende Aufträge; die
  pinnen ihre Version).
- Gruppen-Platzhalter (`HIER_GRUPPEN_ID_..._EINSETZEN`) werden gegen die
  vorhandenen Gruppen aufgelöst. Fehlt eine Gruppe, wird der Prozess **nicht**
  eingespielt (Warnung im Log), statt einen kaputten Zustand zu schreiben.
- Im **UI ist der Prozess schreibgeschützt** (wie ein System-Prozess): die JSON
  ist die einzige Quelle der Wahrheit. Wer eine frei editierbare Variante will,
  dupliziert den Prozess (`:duplicate`) – die Kopie liegt dann nicht hier.

Prozesse, die weiter **im UI** gepflegt werden sollen, gehören **nicht** hierher,
sondern nach `backend/seeds/processes/` (manueller Import über die Oberfläche).

Der Mechanismus steckt in `backend/services/seed_definitions.ensure_auto_processes`.
