# Eingefrorene v1-Definitionen (Forward-Compat-Baseline)

Diese Dateien sind **eingefrorene Momentaufnahmen** gültiger `ProcessDefinition`s
zum Schema-Stand `schemaVersion: 1`. Sie stehen für „so sieht eine bereits in
Produktion **gepinnte** Alt-Definition aus".

`test_schema_golden.py` validiert sie gegen das AKTUELLE Meta-Schema. Der Sinn:

> **Diese Dateien dürfen NICHT mehr geändert/regeneriert werden.** Schlägt der Test
> fehl, hat eine Schema-Änderung eine bestehende, bereits ausgelieferte Definition
> **unlesbar** gemacht — genau das, was in Produktion laufende Tickets bricken würde.

Reaktion auf einen roten Test:
- Änderung **additiv** machen (neue Felder optional, neue Enum-Werte, neue
  Union-Varianten) — dann validieren die Alt-Definitionen weiter.
- Oder einen echten Migrationspfad bauen (schemaVersion-Bump + `migrate(old)→current`,
  Design-Doc §3.3) und erst DANN die Baseline bewusst mit-erneuern.

Neue Dateien hier hinzuzufügen ist willkommen (mehr Abdeckung); bestehende zu
editieren untergräbt die Garantie.
