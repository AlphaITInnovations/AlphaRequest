"""Ebene-1: Ereignis-Kennzahlen des Workflow-Motors (best-effort, kein DB/Prometheus-Setup)."""
from prometheus_client import REGISTRY, generate_latest

from backend.metrics import engine_metrics as em


def _val(name, labels=None):
    return REGISTRY.get_sample_value(name, labels)


def test_automation_counter_zaehlt_je_process_trigger_action():
    before = _val("process_automation_fired_total",
                  {"process": "demo", "trigger": "timer", "action": "escalate"}) or 0
    em.record_automation_fired("demo", "timer", "escalate")
    em.record_automation_fired("demo", "timer", "escalate")
    after = _val("process_automation_fired_total",
                 {"process": "demo", "trigger": "timer", "action": "escalate"})
    assert after == before + 2


def test_automation_failed_counter():
    before = _val("process_automation_failed_total",
                  {"process": "demo", "action": "directus_write"}) or 0
    em.record_automation_failed("demo", "directus_write")
    after = _val("process_automation_failed_total",
                 {"process": "demo", "action": "directus_write"})
    assert after == before + 1


def test_phase_duration_ist_ein_histogram():
    em.record_phase_duration("demo", "freigabe", 3600)
    # Histogram legt _count/_sum/_bucket an; negative/None-Werte werden ignoriert.
    em.record_phase_duration("demo", "freigabe", -5)      # ignoriert
    cnt = _val("process_phase_duration_seconds_count", {"process": "demo", "phase": "freigabe"})
    assert cnt == 1
    text = generate_latest(REGISTRY).decode()
    assert "# TYPE process_phase_duration_seconds histogram" in text


def test_scheduler_und_directus_counter():
    sweeps_before = _val("process_scheduler_sweeps_total") or 0
    em.record_scheduler_sweep(0.2)
    assert _val("process_scheduler_sweeps_total") == sweeps_before + 1

    fail_before = _val("process_scheduler_ticket_failures_total") or 0
    em.record_scheduler_ticket_failure()
    assert _val("process_scheduler_ticket_failures_total") == fail_before + 1

    ok_before = _val("process_directus_write_total", {"operation": "create", "outcome": "ok"}) or 0
    em.record_directus_write("create", "ok")
    assert _val("process_directus_write_total", {"operation": "create", "outcome": "ok"}) == ok_before + 1


def test_record_funktionen_werfen_nie():
    # Unsinnige Eingaben dürfen den Aufrufer (Motor) nie mitreißen.
    em.record_phase_duration(None, None, None)
    em.record_automation_fired(None, None, None)
    em.record_directus_write(None, "error")
    em.record_scheduler_sweep(None)
