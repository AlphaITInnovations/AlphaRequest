import os
from dotenv import load_dotenv
import backend.database.settings as db
from pathlib import Path

def str_to_bool(s):
    return s.lower() in ("true", "1", "yes", "on")

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR.parent / ".env"

load_dotenv(ENV_PATH)

class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-min-16-chars")

    CLIENT_ID = os.getenv("CLIENT_ID", "")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
    TENANT_ID = os.getenv("TENANT_ID", "")
    REDIRECT_URI = os.getenv("REDIRECT_URI", "")
    SCOPE = [s.strip() for s in os.getenv("SCOPE", "User.Read,Mail.Send").split(",") if s.strip()]
    ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "")
    TICKET_MAIL = os.getenv("TICKET_MAIL", "")
    # Empfänger für Fehlerberichte / Feedback aus der UI
    BUG_REPORT_MAIL = os.getenv("BUG_REPORT_MAIL", "")
    # Bestätigungs-Adresse für nicht umkehrbare Eingriffe – heute: das Löschen
    # eines ganzen Prozesses samt seiner Aufträge. OHNE diese Adresse ist das
    # Löschen gesperrt (fail-closed): der Bestätigungsweg IST die Sicherung, und
    # ein stiller Ersatz-Empfänger würde sie aushebeln.
    ADMIN_MAIL = os.getenv("ADMIN_MAIL", "")
    # Gültigkeit des Bestätigungs-Links (Sekunden, Standard 24 h). Läuft er ab,
    # muss die Löschung neu angefordert werden.
    PROCESS_DELETE_LINK_MAX_AGE = int(os.getenv("PROCESS_DELETE_LINK_MAX_AGE", 24 * 3600))

    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", 900))

    PORT = int(os.getenv("PORT", 5000))
    HTTPS = str_to_bool(os.getenv("HTTPS", "false"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    DEVPOPUP = str_to_bool(os.getenv("DEVPOPUP", "false"))
    USER_SYNC_INTERVAL = int(os.getenv("USER_SYNC_INTERVAL", "30"))

    # Personalnummern werden pro Firma vergeben (Bereich in den Settings/Firmen).
    # Sind für eine Firma nur noch <= so viele Nummern frei, geht eine Warn-Mail an TICKET_MAIL.
    PERSONALNUMMER_WARN_REMAINING = int(os.getenv("PERSONALNUMMER_WARN_REMAINING", 10))

    # URLs – in .env setzen, Defaults für Dev
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://ai-ms-01.dom.local:5173")
    BACKEND_URL:  str = os.getenv("BACKEND_URL",  "https://ai-ms-01.dom.local:5000")

    # Datei-Anhänge: Blobs liegen auf dem Dateisystem (Metadaten in der DB).
    ATTACHMENTS_DIR: str = os.getenv("ATTACHMENTS_DIR", str(BASE_DIR.parent / "data" / "attachments"))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))

    # Prozess-Automations-Scheduler (Timer/Eskalation). RUN_SCHEDULER sollte NUR auf
    # EINER Instanz true sein; die Korrektheit gegen Doppel-Feuern garantiert aber der
    # Idempotenz-Ledger (process_timer_fires), nicht dieses Flag.
    RUN_SCHEDULER: bool = str_to_bool(os.getenv("RUN_SCHEDULER", "true"))
    SCHEDULER_INTERVAL: int = int(os.getenv("SCHEDULER_INTERVAL", "900"))

    # Directus (internes Stammdaten-System) – Quelle für Auswahl-Felder wie
    # Kostenstelle/Niederlassung. Ohne URL+Token ist die Anbindung inaktiv
    # (fail-soft: Directus-Felder zeigen dann eine leere Auswahl, kein Absturz).
    # Der Token ist ein statischer Directus-Service-Token mit LESE-Rechten.
    DIRECTUS_URL: str = os.getenv("DIRECTUS_URL", "").rstrip("/")
    DIRECTUS_TOKEN: str = os.getenv("DIRECTUS_TOKEN", "")
    DIRECTUS_TIMEOUT: int = int(os.getenv("DIRECTUS_TIMEOUT", "15"))
    # TLS-Prüfung gegen Directus. Bei selbst-signiertem Zertifikat entweder
    # DIRECTUS_CA_BUNDLE auf die CA-Datei zeigen lassen (empfohlen, prüft weiter)
    # ODER DIRECTUS_VERIFY_SSL=false setzen (Prüfung AUS – nur im vertrauenswürdigen
    # internen Netz vertretbar).
    DIRECTUS_VERIFY_SSL: bool = str_to_bool(os.getenv("DIRECTUS_VERIFY_SSL", "true"))
    DIRECTUS_CA_BUNDLE: str = os.getenv("DIRECTUS_CA_BUNDLE", "")
    # Schreib-Token für Automations-Aktionen (Anlegen/Ändern/Löschen in Directus).
    # Leer = derselbe Token wie zum Lesen (der braucht dann Schreibrechte auf die
    # Ziel-Collection). Getrennt haltbar, um Lese- und Schreibrechte zu trennen.
    DIRECTUS_WRITE_TOKEN: str = os.getenv("DIRECTUS_WRITE_TOKEN", "")

    # ── Mitarbeiter-Zuordnung: Azure-Login ↔ Directus-Stammdaten ─────────────
    # Grundprinzip: die IDENTITÄT bleibt Azure (oid, Gruppen, Benachrichtigung);
    # die INFOS (Name, Position, Vorgesetzter …) kommen aus Directus, verknüpft
    # über die E-Mail. Bewusst per ENV (Kern-Infrastruktur, tiefer als ein
    # Formular-Dropdown) und NICHT über die admin-editierbaren Directus-Quellen –
    # damit sich niemand über das Admin-UI selbst aussperren kann.
    DIRECTUS_EMPLOYEE_COLLECTION: str = os.getenv("DIRECTUS_EMPLOYEE_COLLECTION", "mitarbeitende")
    DIRECTUS_EMPLOYEE_EMAIL_FIELD: str = os.getenv("DIRECTUS_EMPLOYEE_EMAIL_FIELD", "email")
    # Directus-Feldliste des Datensatzes (dot-Pfade erlaubt, z. B. für den
    # Vorgesetzten: "*,vorgesetzter.*"). Default: alle Top-Level-Felder.
    DIRECTUS_EMPLOYEE_FIELDS = [s.strip() for s in
                               os.getenv("DIRECTUS_EMPLOYEE_FIELDS", "*").split(",") if s.strip()]
    DIRECTUS_EMPLOYEE_CACHE_TTL: int = int(os.getenv("DIRECTUS_EMPLOYEE_CACHE_TTL", "300"))
    # Hard Gate: ohne Directus-Datensatz kein Arbeiten. Abschaltbar für Dev/Rollout
    # (dann wird der Datensatz nur best-effort angehängt, aber nie blockiert).
    AUTH_REQUIRE_DIRECTUS_EMPLOYEE: bool = str_to_bool(
        os.getenv("AUTH_REQUIRE_DIRECTUS_EMPLOYEE", "true"))
    # Break-Glass: diese E-Mails passieren das Gate IMMER – auch wenn Directus down
    # ist ODER kein Datensatz existiert. Mindestens eine Admin-Mail hier eintragen,
    # damit ein Directus-Ausfall nicht alle (inkl. Admins) aussperrt.
    AUTH_BOOTSTRAP_EMAILS = {s.strip().lower() for s in
                            os.getenv("AUTH_BOOTSTRAP_EMAILS", "").split(",") if s.strip()}

    # Nutzerliste (Dropdowns/Beobachter/Zuständige/Mitglieder) kommt aus derselben
    # Directus-Collection wie die Zuordnung. Der gespeicherte Personenschlüssel ist
    # die E-Mail (siehe DIRECTUS_EMPLOYEE_EMAIL_FIELD). Der Anzeigename wird aus
    # diesen Feldern zusammengesetzt (mit Leerzeichen verbunden, leere übersprungen).
    DIRECTUS_EMPLOYEE_NAME_FIELDS = [s.strip() for s in
                                    os.getenv("DIRECTUS_EMPLOYEE_NAME_FIELDS",
                                              "first_name,last_name").split(",") if s.strip()]
    DIRECTUS_EMPLOYEE_LIST_LIMIT: int = int(os.getenv("DIRECTUS_EMPLOYEE_LIST_LIMIT", "2000"))

    @property
    def COMPANIES(self):
        return db.get_companies()

    @classmethod
    def as_dict(cls):
        return {k: v for k, v in cls.__dict__.items() if not k.startswith("__") and not callable(v)}

config = Config()