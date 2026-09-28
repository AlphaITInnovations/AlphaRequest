"""route-Label der HTTP-Metriken: kardinalitätssicher (gematchtes Muster, nicht Rohpfad)."""
from backend.metrics import http_metrics as hm


class _Url:
    def __init__(self, path):
        self.path = path


class _Req:
    def __init__(self, scope):
        self.scope = scope
        self.url = _Url(scope.get("path", "/"))


def test_bevorzugt_das_route_muster():
    class R:
        path = "/process-tickets/{ticket_id}"
    assert hm.route_label(_Req({"route": R(), "path": "/process-tickets/123"})) \
        == "/process-tickets/{ticket_id}"


def test_rekonstruiert_aus_path_params():
    req = _Req({"path": "/process-tickets/123/anhaenge", "endpoint": object(),
                "path_params": {"ticket_id": "123"}})
    assert hm.route_label(req) == "/process-tickets/:ticket_id/anhaenge"


def test_parameterloser_treffer_wird_id_normalisiert():
    req = _Req({"path": "/health", "endpoint": object()})
    assert hm.route_label(req) == "/health"


def test_unbekannte_pfade_kollabieren_auf_ein_label():
    # Ein Scanner, der beliebige Pfade abklappert, erzeugt KEINE neuen Zeitreihen.
    a = hm.route_label(_Req({"path": "/gibt-es-nicht-aaa"}))
    b = hm.route_label(_Req({"path": "/gibt-es-nicht-bbb"}))
    assert a == b == "__unmatched__"
