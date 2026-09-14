"""Generator für das AlphaRequest Enterprise-Grafana-Dashboard.

Baut Python-Dicts (garantiert valides JSON) und schreibt das Dashboard an beide
Orte: docs/monitoring (Doku-Heimat) und monitoring/grafana (operativ). Erzeugt,
nicht von Hand gepflegt – bei Änderungen dieses Skript anpassen und neu laufen
lassen (Pfad steht im Dashboard-Titel-Kommentar / README).
"""
import json
import sys

TEAL = "#3EACB6"
DS = {"type": "prometheus", "uid": "${datasource}"}
GRID = 24

_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

# Layout-Helfer: legt Panels in Reihen à 24 Spalten, verwaltet y automatisch.
class Layout:
    def __init__(self):
        self.panels = []
        self.y = 0
        self.x = 0
        self.rowh = 0

    def row(self, title):
        if self.x:
            self.y += self.rowh
            self.x = 0
            self.rowh = 0
        self.panels.append({"id": nid(), "type": "row", "title": title,
                            "collapsed": False, "panels": [],
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}})
        self.y += 1
        self.rowh = 0

    def add(self, panel, w, h):
        if self.x + w > GRID:
            self.y += self.rowh
            self.x = 0
            self.rowh = 0
        panel["gridPos"] = {"h": h, "w": w, "x": self.x, "y": self.y}
        panel["id"] = nid()
        panel["datasource"] = DS
        self.panels.append(panel)
        self.x += w
        self.rowh = max(self.rowh, h)


def _targets(exprs):
    out = []
    for i, (expr, legend) in enumerate(exprs):
        t = {"refId": chr(65 + i), "expr": expr, "datasource": DS}
        if legend is not None:
            t["legendFormat"] = legend
        out.append(t)
    return out


def stat(title, desc, exprs, unit="short", color=TEAL, steps=None, mode="value",
         graph="area", legend=None):
    fc = {"color": {"mode": "fixed", "fixedColor": color}, "unit": unit,
          "thresholds": {"mode": "absolute",
                         "steps": steps or [{"color": color, "value": None}]}}
    if steps:
        fc["color"] = {"mode": "thresholds"}
    return {"type": "stat", "title": title, "description": desc,
            "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "orientation": "auto", "textMode": "auto", "colorMode": mode,
                        "graphMode": graph, "justifyMode": "auto"},
            "targets": _targets([(e, legend) for e in exprs])}


def timeseries(title, desc, exprs, unit="short", stack=False, style="line",
               fill=10, legend_calcs=("mean", "lastNotNull", "max"), width=1, points=False):
    return {"type": "timeseries", "title": title, "description": desc,
            "fieldConfig": {"defaults": {
                "color": {"mode": "palette-classic"}, "unit": unit,
                "custom": {"drawStyle": style, "lineInterpolation": "smooth",
                           "lineWidth": width, "fillOpacity": fill,
                           "gradientMode": "opacity", "showPoints": "auto" if points else "never",
                           "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                           "axisPlacement": "auto", "spanNulls": True}},
                "overrides": []},
            "options": {"tooltip": {"mode": "multi", "sort": "desc"},
                        "legend": {"displayMode": "table", "placement": "bottom",
                                   "calcs": list(legend_calcs)}},
            "targets": _targets(exprs)}


def barchart(title, desc, expr, legend, unit="short", horizontal=True):
    return {"type": "barchart", "title": title, "description": desc,
            "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}, "unit": unit,
                            "custom": {"fillOpacity": 85, "lineWidth": 1, "gradientMode": "opacity"}},
                            "overrides": []},
            "options": {"orientation": "horizontal" if horizontal else "vertical",
                        "showValue": "auto", "stacking": "none",
                        "legend": {"displayMode": "hidden", "placement": "bottom"},
                        "xTickLabelRotation": 0, "tooltip": {"mode": "single", "sort": "none"}},
            "targets": _targets([(expr, legend)])}


def piechart(title, desc, expr, legend, unit="short"):
    return {"type": "piechart", "title": title, "description": desc,
            "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}, "unit": unit},
                            "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "pieType": "donut", "tooltip": {"mode": "single", "sort": "desc"},
                        "legend": {"displayMode": "table", "placement": "right",
                                   "values": ["value", "percent"]},
                        "displayLabels": ["name"]},
            "targets": _targets([(expr, legend)])}


def table(title, desc, expr, unit="short"):
    return {"type": "table", "title": title, "description": desc,
            "fieldConfig": {"defaults": {"color": {"mode": "thresholds"}, "unit": unit,
                            "custom": {"align": "auto", "filterable": True}},
                            "overrides": []},
            "options": {"showHeader": True, "sortBy": [{"displayName": "Value", "desc": True}]},
            "targets": [{"refId": "A", "expr": expr, "datasource": DS,
                         "format": "table", "instant": True}]}


def heatmap(title, desc, expr):
    return {"type": "heatmap", "title": title, "description": desc,
            "options": {"calculate": True,
                        "calculation": {"xBuckets": {"mode": "size", "value": "1h"}},
                        "color": {"scheme": "Turbo", "mode": "scheme", "steps": 64,
                                  "reverse": False, "exponent": 0.5},
                        "cellGap": 1, "yAxis": {"unit": "short"},
                        "tooltip": {"show": True, "yHistogram": False},
                        "legend": {"show": True}, "exemplars": {"color": "rgba(255,0,255,0.7)"}},
            "fieldConfig": {"defaults": {"custom": {"scaleDistribution": {"type": "linear"}}}, "overrides": []},
            "targets": [{"refId": "A", "expr": expr, "datasource": DS,
                         "format": "heatmap", "legendFormat": "{{process}}"}]}


# Schwellen-Vorlage: grün ab 0, optional gelb ab `y`, rot ab `r`.
def th(_g=0, y=None, r=None):
    out = [{"color": "green", "value": None}]
    if y is not None:
        out.append({"color": "yellow", "value": y})
    if r is not None:
        out.append({"color": "red", "value": r})
    return out


L = Layout()

# ── Überblick (KPIs) ─────────────────────────────────────────────────────────
L.row("Überblick")
L.add(stat("Offene Aufträge", "Nicht-terminale Prozess-Aufträge (das arbeitsrelevante Bild).",
           ["process_tickets_open"], color=TEAL, mode="value", graph="area"), 4, 4)
L.add(stat("Überfällige Timer", "Aktive Aufträge mit fälligem Timer (next_timer_due_at ≤ jetzt). "
           "Steigt dauerhaft, wenn der Scheduler nicht abarbeitet.",
           ["process_tickets_timers_due"], steps=th(0, 1, 10)), 4, 4)
L.add(stat("Ältester offener Auftrag", "Alter des ältesten offenen Auftrags (über alle Prozesse).",
           ["max(process_tickets_oldest_open_age_seconds)"], unit="s",
           steps=th(0, 86400, 259200)), 4, 4)
L.add(stat("Abgeschlossen (24 h)", "Erreichte Endzustände „archiviert“ der letzten 24 h (Durchsatz).",
           ['sum(increase(process_tickets_terminal_total{outcome="archived"}[24h]))'],
           color="#73BF69"), 4, 4)
L.add(stat("Abgelehnt (24 h)", "Ablehnungen der letzten 24 h.",
           ['sum(increase(process_tickets_terminal_total{outcome="rejected"}[24h]))'],
           color="#FF9830"), 4, 4)
L.add(stat("Automations-Fehler (1 h)", "Fehlgeschlagene Automationen der letzten Stunde – "
           "Zuverlässigkeit der Automatik.",
           ["sum(increase(process_automation_failed_total[1h]))"], steps=th(0, 1, 5)), 4, 4)

# ── Offene Aufträge – das Tagesbild ──────────────────────────────────────────
L.row("Offene Aufträge (das Tagesbild)")
L.add(piechart("Offen nach Status", "Offene Aufträge je Status (process_tickets_open_by_status). "
               "Archivierte/abgelehnte sind hier bewusst NICHT enthalten.",
               "process_tickets_open_by_status", "{{status}}"), 8, 8)
L.add(barchart("Offen nach Priorität", "Offene Aufträge je Priorität.",
               "process_tickets_open_by_priority", "{{priority}}"), 8, 8)
L.add(barchart("Offen nach Typ (Prozess)", "Offene Aufträge je Auftragstyp (Prozess-Key). "
               "Filterbar über die Prozess-Variable oben.",
               'process_tickets_open_by_process{process=~"$process"}', "{{process}}"), 8, 8)
L.add(barchart("Offen nach Phase", "Offene Aufträge in der aktuellen Phase (je Prozess) – "
               "wo stapelt sich die Arbeit gerade?",
               'process_tickets_by_phase{process=~"$process"}', "{{process}} · {{phase}}"), 12, 8)
L.add(barchart("Stau je Fachabteilung", "Offene Fachabteilungs-Quittierungen je Gruppe "
               "(aktuelle Phase). DER Stau-Indikator: welche Abteilung hält gerade auf.",
               "process_tickets_open_by_department", "{{department}} (Pflicht={{required}})"), 12, 8)

# ── Erstellungs-Muster ──────────────────────────────────────────────────────
L.row("Erstellungs-Muster – wann werden viele Aufträge angelegt")
L.add(heatmap("Erstellungs-Heatmap (je Typ)", "Wann werden wie viele Aufträge angelegt "
              "(z. B. Wellen neuer Mitarbeiter). Intensität = Neuanlagen pro Stunde, aus "
              "increase(process_tickets_created_total).",
              'sum by (process) (increase(process_tickets_created_total{process=~"$process"}[1h]))'),
      24, 9)
L.add(timeseries("Neue Aufträge je Typ (pro Stunde)", "Neuanlagen je Auftragstyp über die Zeit "
                 "(gestapelte Balken) – zeigt Spitzen und ihre Verteilung nach Prozess.",
                 [('sum by (process) (increase(process_tickets_created_total{process=~"$process"}[1h]))',
                   "{{process}}")], stack=True, style="bars", fill=80,
                 legend_calcs=("sum", "max")), 16, 8)
L.add(stat("Neu angelegt (24 h)", "Alle Neuanlagen der letzten 24 h.",
           ["sum(increase(process_tickets_created_total[24h]))"], color=TEAL), 4, 4)
L.add(stat("Neu angelegt (7 Tage)", "Alle Neuanlagen der letzten 7 Tage.",
           ["sum(increase(process_tickets_created_total[7d]))"], color=TEAL), 4, 4)
L.add(stat("Aufträge gesamt", "Alle je angelegten Aufträge (kumulativ, DB-basiert).",
           ["process_tickets_total"], color="#8AB8FF"), 4, 4)
L.add(stat("Ablehnquote (7 Tage)", "Anteil Ablehnungen an allen Endzuständen der letzten 7 Tage.",
           ['sum(increase(process_tickets_terminal_total{outcome="rejected"}[7d])) '
            '/ clamp_min(sum(increase(process_tickets_terminal_total[7d])), 1)'],
           unit="percentunit", steps=th(0, 0.1, 0.3)), 4, 4)

# ── Motor: Durchlaufzeiten & Automatik ──────────────────────────────────────
L.row("Motor – Durchlaufzeiten & Automatik")
L.add(timeseries("Phasen-Durchlaufzeit p90 / p50", "Wie lange sitzen Aufträge je Phase "
                 "(90./50. Perzentil). Lange Balken = Engpass (z. B. Freigabe hängt Tage).",
                 [('histogram_quantile(0.9, sum by (process, phase, le) '
                   '(rate(process_phase_duration_seconds_bucket{process=~"$process"}[$__rate_interval])))',
                   "p90 {{process}}·{{phase}}"),
                  ('histogram_quantile(0.5, sum by (process, phase, le) '
                   '(rate(process_phase_duration_seconds_bucket{process=~"$process"}[$__rate_interval])))',
                   "p50 {{process}}·{{phase}}")],
                 unit="s", legend_calcs=("max", "mean")), 12, 8)
L.add(table("Langsamste Phasen (p90, jetzt)", "Aktuelles p90 der Verweildauer je Phase – "
            "sortierte Engpass-Liste.",
            "histogram_quantile(0.9, sum by (process, phase, le) "
            "(rate(process_phase_duration_seconds_bucket[1h])))", unit="s"), 12, 8)
L.add(timeseries("Automationen gefeuert (je Aktion)", "Vom Motor autonom ausgeführte Automationen "
                 "je Aktionstyp (notify/escalate/set_field/auto_advance/directus_write …).",
                 [("sum by (action) (rate(process_automation_fired_total[$__rate_interval]))",
                   "{{action}}")], unit="ops"), 8, 8)
L.add(timeseries("Automations-Fehler (je Aktion)", "Fehlgeschlagene Automationen je Aktionstyp – "
                 "sollte dauerhaft 0 sein.",
                 [("sum by (action) (rate(process_automation_failed_total[$__rate_interval]))",
                   "{{action}}")], unit="ops", fill=30), 8, 8)
L.add(timeseries("Eskalationen & Erinnerungen", "Zeitgesteuerte Mails: escalate = Eskalation "
                 "(+Priorität hoch), notify = Erinnerung. Spitze = viele Aufträge überfällig.",
                 [('sum by (action) (rate(process_automation_fired_total{trigger="timer"}[$__rate_interval]))',
                   "{{action}}")], unit="ops"), 8, 8)

# ── Scheduler & Integration ─────────────────────────────────────────────────
L.row("Scheduler & Integration")
L.add(timeseries("Scheduler-Sweeps", "Durchläufe des Timer-Schedulers pro Sekunde. Fällt das auf 0, "
                 "während „Überfällige Timer“ steigt → der Off-Loop-Motor steht.",
                 [("rate(process_scheduler_sweeps_total[$__rate_interval])", "Sweeps/s")],
                 unit="ops"), 8, 7)
L.add(timeseries("Sweep-Dauer p95 & Ticket-Fehler", "p95-Dauer eines Sweeps und Rate der "
                 "in den Backoff gegangenen Tickets.",
                 [("histogram_quantile(0.95, sum by (le) "
                   "(rate(process_scheduler_sweep_duration_seconds_bucket[$__rate_interval])))", "p95 Dauer"),
                  ("rate(process_scheduler_ticket_failures_total[$__rate_interval])", "Ticket-Fehler/s")],
                 unit="s"), 8, 7)
L.add(timeseries("Directus-Schreiben", "Ausgang der Directus-Schreibvorgänge aus Automationen "
                 "(ok/error) – erfasst auch die blockierenden Fehler.",
                 [("sum by (outcome) (rate(process_directus_write_total[$__rate_interval]))",
                   "{{outcome}}")], unit="ops"), 8, 7)

# ── E-Mail ──────────────────────────────────────────────────────────────────
L.row("E-Mail (Microsoft Graph)")
L.add(timeseries("Versand je Typ", "Erfolgreich versendete Mails je Anlass (phase_entry, "
                 "approval_link, escalate, notify, rejection, sent_back …).",
                 [('sum by (type) (rate(mail_sent_total{status="sent"}[$__rate_interval]))',
                   "{{type}}")], unit="ops", stack=True, fill=60), 16, 7)
L.add(stat("Mailfehler (1 h)", "Fehlgeschlagene Zustellungen der letzten Stunde.",
           ['sum(increase(mail_sent_total{status="error"}[1h]))'], steps=th(0, 1, 3)), 8, 7)

# ── Auth & Sessions ─────────────────────────────────────────────────────────
L.row("Auth & Sessions")
L.add(timeseries("Sessions & Online-Nutzer", "Aktive Sessions und verschiedene angemeldete Nutzer:innen.",
                 [("auth_sessions_active", "Aktive Sessions"),
                  ("auth_users_online", "Online-Nutzer:innen")], fill=20), 12, 7)
L.add(timeseries("Logins Erfolg / Fehler", "Erfolgreiche vs. fehlgeschlagene Anmeldungen (je Grund).",
                 [("sum(rate(auth_logins_success_total[$__rate_interval]))", "Erfolg"),
                  ("sum by (reason) (rate(auth_login_failed_total[$__rate_interval]))", "Fehler · {{reason}}")],
                 unit="ops"), 12, 7)

# ── HTTP & System ───────────────────────────────────────────────────────────
L.row("HTTP & System")
L.add(timeseries("Request-Rate & 5xx", "HTTP-Durchsatz gesamt und Server-Fehler (5xx).",
                 [("sum(rate(http_requests_total[$__rate_interval]))", "Requests/s"),
                  ('sum(rate(http_requests_total{status=~"5.."}[$__rate_interval]))', "5xx/s")],
                 unit="reqps"), 12, 7)
L.add(timeseries("Latenz p95 / p50", "Antwortzeit-Perzentile über alle Routen.",
                 [("histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[$__rate_interval])))", "p95"),
                  ("histogram_quantile(0.5, sum by (le) (rate(http_request_duration_seconds_bucket[$__rate_interval])))", "p50")],
                 unit="s"), 12, 7)
L.add(stat("Uptime", "Laufzeit des Backend-Prozesses seit Start.",
           ["process_uptime_seconds"], unit="s", color="#8AB8FF"), 4, 5)
L.add(stat("Speicher (RSS)", "Residenter Speicher des Prozesses.",
           ["process_resident_memory_bytes"], unit="bytes", color="#8AB8FF"), 4, 5)
L.add(stat("Threads", "Aktive Python-Threads.", ["process_threads"], color="#8AB8FF"), 4, 5)
L.add(stat("Metrik-Sammel-Fehler", "Fehlgeschlagene Teil-Durchläufe der Metrik-Erhebung – "
           ">0 heißt: einige Kennzahlen sind eingefroren.",
           ["sum(metrics_collect_failures_total)"], steps=th(0, 1, 1)), 12, 5)


dashboard = {
    "annotations": {"list": [{"builtIn": 1,
                              "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                              "enable": True, "hide": True,
                              "iconColor": "rgba(0, 211, 255, 1)",
                              "name": "Annotations & Alerts", "type": "dashboard"}]},
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
    "liveNow": False, "refresh": "30s", "schemaVersion": 39, "tags": ["alpharequest", "prozesse"],
    "templating": {"list": [
        {"current": {}, "hide": 0, "includeAll": False, "label": "Datenquelle", "multi": False,
         "name": "datasource", "options": [], "query": "prometheus", "refresh": 1, "regex": "",
         "skipUrlSync": False, "type": "datasource"},
        {"current": {"text": "Alle", "value": "$__all"}, "hide": 0, "includeAll": True,
         "label": "Prozess", "multi": True, "name": "process",
         "datasource": DS, "definition": "label_values(process_tickets_by_process, process)",
         "query": {"query": "label_values(process_tickets_by_process, process)", "refId": "A"},
         "refresh": 2, "regex": "", "sort": 1, "type": "query", "options": []},
    ]},
    "time": {"from": "now-24h", "to": "now"}, "timepicker": {}, "timezone": "browser",
    "title": "AlphaRequest – Betrieb & Prozesse", "uid": "alpharequest-overview",
    "version": 4, "weekStart": "", "panels": L.panels,
}

text = json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n"
for path in sys.argv[1:]:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
print(f"panels: {len([p for p in L.panels if p['type'] != 'row'])}, rows: "
      f"{len([p for p in L.panels if p['type'] == 'row'])}, bytes: {len(text)}")
