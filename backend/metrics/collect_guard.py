"""
Absicherung des Metrik-Sammellaufs.

Der Sammel-Thread bedient mehrere Quellen (Sessions, Prozess-Aufträge, System).
Ohne Absicherung nimmt EIN Fehler – etwa eine Tabelle, die kurz nach einer
Migration noch fehlt – alle übrigen Reihen mit: die Ausnahme bricht den Durchlauf
ab, die restlichen Gauges behalten stillschweigend ihren letzten Wert und
niemand sieht, dass sie eingefroren sind.

Deshalb läuft jeder Teil einzeln, und ein Fehlschlag wird als eigene Reihe
sichtbar (`metrics_collect_failures_total`) statt nur im Log zu landen – eine
eingefrorene Kennzahl ist sonst nicht von einer ruhigen Anlage zu unterscheiden.
"""
from prometheus_client import Counter

from backend.utils.logger import logger

metrics_collect_failures_total = Counter(
    "metrics_collect_failures_total",
    "Fehlgeschlagene Teil-Durchläufe der Metrik-Erhebung",
    ["part"],
)


def run_part(part: str, fn, *args, **kwargs) -> bool:
    """`fn` ausführen; ein Fehler wird gezählt und geloggt, nie geworfen.

    Gibt zurück, ob der Teil durchgelaufen ist (für Tests und für Aufrufer, die
    Folge-Schritte überspringen wollen).
    """
    try:
        fn(*args, **kwargs)
        return True
    except Exception:
        logger.exception("Metrik-Teillauf „%s“ fehlgeschlagen", part)
        try:
            metrics_collect_failures_total.labels(part=part).inc()
        except Exception:
            # Selbst der Fehlerzähler darf den Sammellauf nicht kippen.
            pass
        return False
