# Monitoring (Prometheus + Grafana)

Betriebs- und Fachkennzahlen von AlphaRequest. Wie bei `docs/prozesse/` liegt
`docs/` **nicht** im Docker-Image – dieser Ordner ist Dokumentation und trägt die
kanonische Dashboard-JSON; die operative Kopie liegt unter `monitoring/`.

Das Backend instrumentiert sich selbst mit `prometheus-client` und exponiert alle
Reihen unter **`GET /metrics`** (Port 5000). Ein daemon-Thread frischt die
Bestands-Gauges alle `METRICS_COLLECT_INTERVAL` Sekunden (Default 10) aus der DB
auf; Ereignis-Zähler/-Histogramme werden direkt an den Choke-Points des Motors
hochgezählt.

## Dateien

| Datei | Zweck |
|---|---|
| `docs/monitoring/alpharequest-dashboard.json` | **Kanonisches** Grafana-Dashboard (Import-Quelle) |
| `monitoring/grafana/alpharequest-overview.json` | Identische operative Kopie (gleiche `uid`) |
| `monitoring/grafana/generate_dashboard.py` | Generator – das Dashboard wird **erzeugt, nicht von Hand** gepflegt |
| `monitoring/prometheus/prometheus.yml` | Scrape-Konfiguration (Ziel `backend:5000/metrics`) |
| `monitoring/prometheus/alerts.yml` | Prometheus-Alarmregeln (Schwellen wie im Dashboard) |

Beide Dashboard-JSONs sind bytegleich. **Zum Ändern das Skript anpassen** und neu
laufen lassen (schreibt beide Pfade):

```bash
.venv/Scripts/python.exe monitoring/grafana/generate_dashboard.py \
  docs/monitoring/alpharequest-dashboard.json \
  monitoring/grafana/alpharequest-overview.json
```

## Dashboard importieren

Grafana → **Dashboards → New → Import** → `docs/monitoring/alpharequest-dashboard.json`
hochladen → beim Prompt die **Prometheus-Datenquelle** wählen (Variable
`Datenquelle`). Beim erneuten Import ersetzt Grafana den Stand über die stabile
`uid` `alpharequest-overview` (Version hochzählen). Oben filtern zwei Variablen:
**Datenquelle** und **Prozess** (Mehrfachauswahl je Auftragstyp).

Aufbau (8 Reihen): Überblick · Offene Aufträge · **Erstellungs-Muster** (Heatmap
„wann werden viele Aufträge angelegt") · Motor (Durchlaufzeiten & Automatik) ·
Scheduler & Integration · E-Mail · Auth & Sessions · HTTP & System. Default-
Zeitraum 24 h, Refresh 30 s.

## „Alle" vs. „Offen"

Status/Priorität/Typ gibt es **doppelt**: die `process_tickets_by_*`-Reihen zählen
**alle** Aufträge (Historie), die `process_tickets_open_by_*`-Reihen nur die
**offenen** (nicht-terminalen). Im Dashboard sind bewusst die **Offen**-Reihen
verdrahtet – sonst überwiegen mit der Zeit die archivierten Aufträge und
verdecken das Tagesbild. „Offen" = `status NOT IN (archived, rejected)`.

## Erstellungs-Muster („wann viele neue Mitarbeiter")

`process_tickets_created_total{process}` ist ein DB-basierter, monotoner Counter
(überlebt Neustarts). Über `increase(...[1h])` je Prozess entsteht die Heatmap
und die gestapelte Balkenreihe „Neue Aufträge je Typ" – dort sieht man Wellen
(z. B. viele neue Onboardings vor Quartalsbeginn) und ihre Verteilung nach Typ.

## Metrik-Katalog

**Prozess-Bestände (Gauge, 10 s-Sammellauf):**
`process_tickets_total`, `process_tickets_open`, `process_tickets_by_status{status}` /
`process_tickets_open_by_status{status}`, `process_tickets_by_priority{priority}` /
`process_tickets_open_by_priority{priority}`, `process_tickets_by_process{process}` /
`process_tickets_open_by_process{process}`, `process_tickets_by_phase{process,phase}`,
`process_tickets_open_by_department{department,required}` (Stau-Indikator),
`process_tickets_oldest_open_age_seconds{process}`, `process_tickets_timers_due`.

**Prozess-Ereignisse (Counter/Histogram, am Choke-Point):**
`process_tickets_created_total{process}`, `process_tickets_terminal_total{outcome}`
(archived|rejected), `process_phase_duration_seconds{process,phase}` (Histogram –
Engpass-Phasen), `process_automation_fired_total{process,trigger,action}` /
`process_automation_failed_total{process,action}`,
`process_scheduler_sweeps_total`, `process_scheduler_sweep_duration_seconds`
(Histogram), `process_scheduler_ticket_failures_total`,
`process_directus_write_total{operation,outcome}`,
`process_http_request_total{method,outcome}` /
`process_http_request_duration_seconds` (Histogram – ausgehende API-Aufrufe der
Aktion `http_request`).

> Eskalationen/Erinnerungen = `process_automation_fired_total{trigger="timer"}`
> (`action="escalate"` bzw. `"notify"`).

**E-Mail:** `mail_sent_total{type,status}` (Microsoft Graph, sent|error).

**Auth/Sessions:** `auth_sessions_active`, `auth_users_online`,
`auth_login_attempts_total`, `auth_logins_success_total{provider}`,
`auth_login_failed_total{reason}`, `session_force_logouts_total{scope}`.

**HTTP:** `http_requests_total{method,route,status}`,
`http_request_duration_seconds` (Histogram), `http_requests_in_progress`,
`http_exceptions_total{route,exception}`.

**System/Betrieb:** `process_uptime_seconds`, `process_threads`,
`process_resident_memory_bytes`, `metrics_collect_failures_total{part}`
(>0 = eingefrorene Kennzahlen).

**Datenschutz:** Labels tragen ausschließlich Definitions-Schlüssel (Prozess-Key,
Phasen-Key), Gruppen-IDs, Status/Enums – **niemals** Feldwerte, Titel oder
Personendaten. `/metrics` hat keinen Sichtbarkeitsfilter; die Reihen sind daher
bewusst personendatenfrei (testgesichert in `backend/tests/test_process_metrics.py`).

## Scrape & Betrieb

Prometheus scrapt `backend:5000/metrics` im `dokploy-network`
(`monitoring/prometheus/prometheus.yml`), `scrape_interval` 15 s
(≥ `METRICS_COLLECT_INTERVAL`). Uptime zusätzlich über `/health`.

**Retention:** als Prometheus-Deploy-Parameter setzen, z. B.
`--storage.tsdb.retention.time=30d`. Langzeit (VictoriaMetrics/Mimir/Thanos via
`remote_write`) ist ein optionaler späterer Schritt.

**Absicherung (`/metrics`):** Der Endpunkt ist offen, solange
`METRICS_USERNAME`/`METRICS_PASSWORD` im Backend **nicht** gesetzt sind. Für
Produktion beide in der Backend-Umgebung setzen und in `prometheus.yml` den
`basic_auth`-Block aktivieren. Mit `ENABLE_METRICS=false` lässt sich `/metrics`
ganz abschalten.

## Alarme

`monitoring/prometheus/alerts.yml` (Zustellung via Alertmanager oder direkt als
Grafana-Alerting): u. a. **BackendDown**, **SchedulerSteht** (überfällige Timer,
aber keine Sweeps), **MetrikenEingefroren**, **AutomationenFehlerhaft**,
**DirectusSchreibfehler**, **AuftraegeLiegenZuLange** (>3 Tage),
**Http5xxErhoeht**, **MailZustellungFehlerhaft**.
