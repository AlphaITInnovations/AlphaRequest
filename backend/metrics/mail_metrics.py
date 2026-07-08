"""Mailversand-Metriken (Microsoft Graph)."""

from prometheus_client import Counter


mail_sent_total = Counter(
    "mail_sent_total",
    "E-Mails sent via Microsoft Graph, by type and outcome",
    ["type", "status"],  # status: sent | error
)


def record_mail(kind: str, status: str) -> None:
    """Best-effort – Metrik darf den Mailversand nie beeinflussen."""
    try:
        mail_sent_total.labels(type=(kind or "other"), status=status).inc()
    except Exception:
        pass
