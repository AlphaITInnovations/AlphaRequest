"""
Bestätigte Löschung eines ganzen Prozesses (Definition + zugehörige Aufträge).

Warum zweistufig: das Löschen ist nicht umkehrbar und nimmt mehr mit, als man auf
einem Knopf ablesen kann – alle Versionen der Definition UND jeden Auftrag, der
sie gepinnt hat, samt Verlauf, Beobachter:innen und Anhängen. Deshalb:
anfordern → Bestätigungs-Mail an `ADMIN_MAIL` → dort bestätigen.

Drei bewusste Entscheidungen:

1. **Der Bestätigungs-Link verlangt eine Anmeldung als Admin.** Anders als die
   Freigabe per Mail-Link (dort hat die entscheidende Person absichtlich keinen
   Zugang) ist hier jede:r Anfordernde ohnehin Admin. Ein offener Endpunkt, der
   auf Vorzeigen eines Tokens einen Prozess mit allen Aufträgen löscht, wäre eine
   viel zu große Angriffsfläche für eine weitergeleitete Mail. Die Mail ist der
   ZWEITE Kanal, nicht die Berechtigung.

2. **Fingerabdruck im Token.** Er beschreibt den Prozess zum Zeitpunkt der
   Anforderung (Versionen, Status, rev, Anzahl Aufträge). Ändert sich danach
   etwas, ist der Link ungültig – sonst könnte man etwas bestätigen, das man so
   nie zu sehen bekam (z. B. inzwischen 30 statt 2 betroffene Aufträge).

3. **Ohne `ADMIN_MAIL` ist das Löschen gesperrt.** Der Bestätigungsweg ist die
   Sicherung; ein stiller Ersatz-Empfänger würde sie aushebeln.

Reine Logik, kein DB-Zugriff – damit ohne Datenbank testbar.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.utils.config import config

SALT = "process-delete-v1"

#: Verlaufs-/Audit-Aktionen dieses Wegs.
AUDIT_REQUESTED = "process_delete_requested"
AUDIT_CONFIRMED = "process_delete_confirmed"


class DeleteError(Exception):
    """Fachlicher Abbruch mit einem Code, den die Oberfläche versteht.

    Codes: invalid · expired · superseded · not_found · no_recipient · needs_tickets
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt=SALT)


def fingerprint(overview: dict) -> str:
    """Kurzer, stabiler Abdruck des Prozess-Zustands.

    Gehasht, damit das Token nicht mit der Zahl der Versionen wächst – der Inhalt
    muss nicht lesbar sein, nur vergleichbar.
    """
    roh = str(overview.get("fingerprint") or "")
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]


def recipient() -> str:
    """Bestätigungs-Adresse. Fehlt sie, ist Löschen gesperrt (fail-closed)."""
    adresse = (getattr(config, "ADMIN_MAIL", "") or "").strip()
    if not adresse:
        raise DeleteError("no_recipient",
                          "Es ist keine Bestätigungs-Adresse hinterlegt (ADMIN_MAIL). "
                          "Ohne sie kann ein Prozess nicht gelöscht werden.")
    return adresse


def max_age_seconds() -> int:
    wert = int(getattr(config, "PROCESS_DELETE_LINK_MAX_AGE", 0) or 0)
    return wert if wert > 0 else 24 * 3600


def make_token(key: str, overview: dict, *, requested_by: Optional[str],
               include_tickets: bool) -> str:
    """Signiertes Token für GENAU diesen Prozess in GENAU diesem Zustand."""
    return _serializer().dumps({
        "key": str(key),
        "fp": fingerprint(overview),
        "tickets": int(overview.get("tickets") or 0),
        "with_tickets": bool(include_tickets),
        "by": requested_by or None,
    })


def _shape_ok(data) -> bool:
    return (isinstance(data, dict)
            and isinstance(data.get("key"), str) and data["key"]
            and isinstance(data.get("fp"), str) and data["fp"]
            and isinstance(data.get("tickets"), int)
            and isinstance(data.get("with_tickets"), bool))


def load_token(token: str) -> dict:
    """Signatur, Alter und Form prüfen. Wirft DeleteError mit sprechendem Code."""
    if not token or not str(token).strip():
        raise DeleteError("invalid", "Es fehlt ein Bestätigungs-Merkmal.")
    try:
        data = _serializer().loads(str(token).strip(), max_age=max_age_seconds())
    except SignatureExpired:
        raise DeleteError("expired",
                          "Der Bestätigungs-Link ist abgelaufen. Bitte die Löschung "
                          "erneut anfordern.")
    except BadSignature:
        raise DeleteError("invalid", "Der Bestätigungs-Link ist ungültig.")
    if not _shape_ok(data):
        raise DeleteError("invalid", "Der Bestätigungs-Link ist unvollständig.")
    return data


def assert_matches(data: dict, overview: Optional[dict]) -> None:
    """Passt das Token noch zum aktuellen Prozess-Zustand?"""
    if overview is None:
        raise DeleteError("not_found",
                          "Diesen Prozess gibt es nicht mehr – vielleicht wurde er "
                          "bereits gelöscht.")
    if data.get("key") != overview.get("key"):
        raise DeleteError("invalid", "Der Bestätigungs-Link gehört zu einem anderen Prozess.")
    if data.get("fp") != fingerprint(overview):
        raise DeleteError(
            "superseded",
            "Der Prozess hat sich seit der Anforderung geändert (Versionen, "
            "Veröffentlichung oder Anzahl der Aufträge). Bitte erneut anfordern, "
            "damit die Bestätigung den aktuellen Stand zeigt.")


def assert_tickets_acknowledged(overview: dict, include_tickets: bool) -> None:
    """Aufträge werden nur mitgelöscht, wenn das ausdrücklich angefordert wurde."""
    n = int(overview.get("tickets") or 0)
    if n and not include_tickets:
        raise DeleteError(
            "needs_tickets",
            f"Zu diesem Prozess gehören noch {n} Auftrag/Aufträge. Sie werden beim "
            f"Löschen mit entfernt – das muss ausdrücklich angefordert werden.")


def expires_at(issued: Optional[datetime] = None) -> str:
    """Ablaufzeitpunkt des Links als ISO-String (für die Anzeige)."""
    start = issued or datetime.now(timezone.utc)
    from datetime import timedelta
    return (start + timedelta(seconds=max_age_seconds())).isoformat()
