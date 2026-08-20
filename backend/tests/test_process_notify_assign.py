"""
Automatische Phasen-Benachrichtigung + Laufzeit-Zuweisung (kind=assignable).

Beides schließt echte Lücken gegenüber dem Alt-System:
 - dort wurde an sechs Stellen automatisch gemailt,
 - und die zuständige Person wurde bei der Erstellung ausgewählt.
"""
import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_access as acc
from backend.services import process_actions as pactions
from backend.services import process_runtime as pr

GROUPS = [{"id": "g_it", "distributions": ["it@example.org"]},
          {"id": "g_fp", "distributions": ["fuhrpark@example.org"]}]

DEFN = ProcessDefinition.model_validate({
    "key": "demo", "name": "Demo",
    "fields": [
        {"key": "a", "widget": "text"},
        {"key": "verantwortlich", "widget": "user"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "a"}, {"ref": "verantwortlich", "required": True}]},
        # Zuständig ist, wer im Personen-Feld steht
        {"key": "bearbeitung", "kind": "task",
         "responsibility": {"kind": "assignable", "fromField": "verantwortlich"},
         "fields": [{"ref": "a", "mode": "editable"}]},
        {"key": "pruefung", "kind": "review",
         "responsibility": {"kind": "departments",
                            "rule": [{"group": "g_it"}, {"group": "g_fp"}]},
         "fields": [{"ref": "a", "mode": "readonly"}]},
        {"key": "still", "kind": "task",
         "responsibility": {"kind": "group", "group": "g_it", "notifyOnEnter": False},
         "fields": [{"ref": "a", "mode": "readonly"}]},
    ],
})


def ticket(values, phase_index=0):
    rt = pr.initial_runtime(DEFN, "t0", values)
    for _ in range(phase_index):
        rt, _s = pr.advance(DEFN, rt, "t1", values)
    return {"id": 7, "title": "Testauftrag", "owner_id": "u_owner",
            "status": "in_progress", "values": values, "runtime": rt}


# ── Laufzeit-Zuweisung ────────────────────────────────────────────────────────

def test_assignable_loest_person_aus_dem_feld_auf():
    t = ticket({"verantwortlich": "u_chef"}, phase_index=1)
    resp = pr.resolve_responsibility(DEFN.phases[1], t["values"])
    assert resp["kind"] == "user" and resp["user"] == "u_chef"
    assert resp["assignable"] is True and resp["from_field"] == "verantwortlich"


def test_assignable_macht_die_person_zustaendig():
    t = ticket({"verantwortlich": "u_chef"}, phase_index=1)
    chef = {"id": "u_chef", "permissions": []}
    fremd = {"id": "u_x", "permissions": []}
    assert acc.may_view(DEFN, t, chef, []) is True
    assert acc.may_edit(DEFN, t, chef, []) is True
    assert acc.may_view(DEFN, t, fremd, []) is False


def test_assignable_ohne_wert_hat_niemanden():
    """Leeres Feld → keine zuständige Person (muss sichtbar sein, nicht stillschweigend)."""
    t = ticket({}, phase_index=1)
    resp = pr.resolve_responsibility(DEFN.phases[1], t["values"])
    assert resp["user"] is None
    assert acc.may_edit(DEFN, t, {"id": "u_chef", "permissions": []}, []) is False


def test_assignable_verlangt_ein_personenfeld():
    base = {"key": "d", "name": "D",
            "fields": [{"key": "t", "widget": "text"}],
            "phases": [{"key": "s", "kind": "start", "responsibility": {"kind": "owner"},
                        "fields": [{"ref": "t"}]},
                       {"key": "b", "kind": "task",
                        "responsibility": {"kind": "assignable", "fromField": "t"},
                        "fields": [{"ref": "t"}]}]}
    with pytest.raises(ValidationError):        # 't' ist widget=text, nicht user
        ProcessDefinition.model_validate(base)

    base["phases"][1]["responsibility"] = {"kind": "assignable", "fromField": "gibtsnicht"}
    with pytest.raises(ValidationError):        # Feld existiert nicht
        ProcessDefinition.model_validate(base)

    base["phases"][1]["responsibility"] = {"kind": "assignable"}
    with pytest.raises(ValidationError):        # fromField fehlt
        ProcessDefinition.model_validate(base)


# ── Benachrichtigung ──────────────────────────────────────────────────────────

def _capture():
    sent = []
    def sender(recips, subject, body, kind=None):
        sent.append({"to": recips, "subject": subject, "kind": kind})
    return sent, sender


def test_start_phase_benachrichtigt_nicht(monkeypatch):
    """Die Start-Phase gehört dem Ersteller – keine Mail über die eigene Eingabe."""
    sent, sender = _capture()
    t = ticket({"verantwortlich": "u_chef"})
    out = pactions.notify_phase_entry(t, DEFN, DEFN.phases[0], sender=sender, groups=GROUPS)
    assert out == [] and sent == []


def test_spaetere_owner_phase_benachrichtigt_den_ersteller(monkeypatch):
    """Kommt der Auftrag SPÄTER (nicht die Start-Phase) über responsibility.kind=
    owner zur erstellenden Person zurück, ist das eine echte neue Aufgabe – die
    muss eine Mail auslösen (früher fälschlich mit der Start-Phase unterdrückt)."""
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "owner@example.org" if uid == "u_owner" else None)
    defn = ProcessDefinition.model_validate({
        "key": "d2", "name": "D2",
        "fields": [{"key": "a", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "a"}]},
            {"key": "zurueck", "kind": "task", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "a", "mode": "editable"}]},
        ],
    })
    t = {"id": 9, "title": "Zurück-Auftrag", "owner_id": "u_owner", "status": "in_progress",
         "values": {}, "runtime": pr.initial_runtime(defn, "t0", {})}
    sent, sender = _capture()
    out = pactions.notify_phase_entry(t, defn, defn.phases[1], sender=sender, groups=GROUPS)
    assert out == ["owner@example.org"]
    assert sent and sent[0]["kind"] == "phase_entry"


def test_abteilungsphase_benachrichtigt_alle_offenen(monkeypatch):
    sent, sender = _capture()
    t = ticket({"verantwortlich": "u_chef"}, phase_index=2)
    out = pactions.notify_phase_entry(t, DEFN, DEFN.phases[2], sender=sender, groups=GROUPS)
    assert set(out) == {"it@example.org", "fuhrpark@example.org"}
    assert sent[0]["kind"] == "phase_entry"
    assert "Testauftrag" in sent[0]["subject"]


def test_erledigte_abteilung_wird_nicht_mehr_angeschrieben():
    sent, sender = _capture()
    t = ticket({"verantwortlich": "u_chef"}, phase_index=2)
    pr.set_department_status(t["runtime"], "g_it", "done", by="u", by_name="X", at="t2")
    out = pactions.notify_phase_entry(t, DEFN, DEFN.phases[2], sender=sender, groups=GROUPS)
    assert out == ["fuhrpark@example.org"]


def test_notify_kann_je_phase_abgeschaltet_werden():
    sent, sender = _capture()
    t = ticket({"verantwortlich": "u_chef"}, phase_index=3)
    out = pactions.notify_phase_entry(t, DEFN, DEFN.phases[3], sender=sender, groups=GROUPS)
    assert out == [] and sent == []


def test_assignable_benachrichtigt_die_person(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "chef@example.org" if uid == "u_chef" else None)
    sent, sender = _capture()
    t = ticket({"verantwortlich": "u_chef"}, phase_index=1)
    out = pactions.notify_phase_entry(t, DEFN, DEFN.phases[1], sender=sender, groups=GROUPS)
    assert out == ["chef@example.org"]


def test_mailfehler_bricht_nichts_ab():
    def boom(*a, **k):
        raise RuntimeError("Graph down")
    t = ticket({"verantwortlich": "u_chef"}, phase_index=2)
    # darf NICHT werfen – der Phasenwechsel selbst muss durchgehen
    assert pactions.notify_phase_entry(t, DEFN, DEFN.phases[2], sender=boom, groups=GROUPS) == []


# ── Freigabe-Mail mit Datei-Anhängen ──────────────────────────────────────────

_APPROVAL_DEFN = ProcessDefinition.model_validate({
    "key": "f", "name": "F", "fields": [{"key": "a", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "a"}]},
        {"key": "frei", "kind": "approval", "view": "approval",
         "responsibility": {"kind": "group", "group": "g_it"},
         "approval": {"question": "Freigeben?", "externalLink": True, "emailBody": "Info"},
         "fields": [{"ref": "a", "mode": "readonly"}]},
    ],
})


def _approval_ticket():
    return {"id": 5, "title": "Freigabe-Auftrag", "owner_id": "o", "status": "in_progress",
            "values": {}, "runtime": pr.initial_runtime(_APPROVAL_DEFN, "t0", {})}


def test_freigabe_mail_haengt_hochgeladene_dateien_an(monkeypatch):
    """Sind Dateien am Auftrag, reisen sie in der Freigabe-Mail mit – plus Hinweis."""
    monkeypatch.setattr(pactions, "approval_links", lambda row, phase: ("http://ja", "http://nein"))
    monkeypatch.setattr(pactions, "_ticket_attachments", lambda row: ["ANHANG1", "ANHANG2"])
    cap: dict = {}

    def sender(recips, subject, body, kind=None, attachments=None):
        cap.update(to=recips, kind=kind, body=body, attachments=attachments)

    out = pactions.notify_phase_entry(_approval_ticket(), _APPROVAL_DEFN,
                                      _APPROVAL_DEFN.phases[1], sender=sender, groups=GROUPS)
    assert out == ["it@example.org"]
    assert cap["kind"] == "approval_link"
    assert cap["attachments"] == ["ANHANG1", "ANHANG2"]
    assert "beigefügt" in cap["body"]           # der kleine Hinweis im Mailtext


def test_freigabe_mail_ohne_anhaenge_uebergibt_kein_kwarg(monkeypatch):
    """Ohne Dateien wird `attachments` NICHT übergeben – alte Sender-Signaturen
    (ohne den Parameter) müssen weiter funktionieren."""
    monkeypatch.setattr(pactions, "approval_links", lambda row, phase: ("http://ja", "http://nein"))
    monkeypatch.setattr(pactions, "_ticket_attachments", lambda row: [])
    cap: dict = {}

    def sender(recips, subject, body, kind=None):   # KEIN attachments-Parameter
        cap.update(kind=kind, body=body)

    out = pactions.notify_phase_entry(_approval_ticket(), _APPROVAL_DEFN,
                                      _APPROVAL_DEFN.phases[1], sender=sender, groups=GROUPS)
    assert out == ["it@example.org"] and cap["kind"] == "approval_link"
    assert "beigefügt" not in cap["body"]           # ohne Dateien kein Hinweis


def test_attachment_note_text():
    assert pactions._attachment_note_html(0) == ""
    assert "1 Datei ist" in pactions._attachment_note_html(1)
    assert "3 Dateien sind" in pactions._attachment_note_html(3)


def test_ticket_attachments_deckelt_gesamtgroesse(monkeypatch):
    """Große Dateien werden ausgelassen, damit die Graph-Grenze nicht den ganzen
    Versand kippt – kleinere danach kommen trotzdem noch mit. Gemessen wird die
    base64-KODIERTE Länge (das, was Graph überträgt)."""
    from types import SimpleNamespace
    from backend.database import attachments as att_db
    from backend.services import attachment_storage as storage
    from backend.services import microsoft_mail as mm
    rows = [
        {"original_filename": "cv.pdf", "stored_path": "cv.pdf"},
        {"original_filename": "riesig.zip", "stored_path": "riesig.zip"},
        {"original_filename": "foto.png", "stored_path": "foto.png"},
    ]
    # kodierte Länge je Datei: cv passt, riesig.zip füllt allein das Limit, foto passt noch.
    enc_len = {"cv.pdf": 1000, "riesig.zip": pactions._MAIL_ATTACH_TOTAL_LIMIT, "foto.png": 2000}
    monkeypatch.setattr(att_db, "list_for_ticket",
                        lambda tid, entity_type=None: [dict(r) for r in rows])
    monkeypatch.setattr(storage, "full_path", lambda sp: sp)
    monkeypatch.setattr(mm, "attachment_from_path",
                        lambda path, filename=None: SimpleNamespace(
                            file=filename, content_bytes_b64="x" * enc_len[filename]))
    out = pactions._ticket_attachments({"id": 5})
    assert [a.file for a in out] == ["cv.pdf", "foto.png"]   # riesig.zip übersprungen


def test_ticket_attachments_ohne_id_leer():
    assert pactions._ticket_attachments({}) == []
