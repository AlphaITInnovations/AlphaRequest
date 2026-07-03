# File: backend/logger.py

import logging
import os
from logging.handlers import RotatingFileHandler

from backend.utils.log_redaction import redact_secrets

# (Optional) Für Windows-Konsolenfarbe
try:
    import colorama
    colorama.init(autoreset=True)
except ImportError:
    pass

# ANSI-Farb-Codes
_COLOR_RESET = "\x1b[0m"
_COLOR_MAP = {
    logging.DEBUG: "\x1b[34m",    # Blau
    logging.INFO: "\x1b[32m",     # Grün
    logging.WARNING: "\x1b[33m",  # Gelb
    logging.ERROR: "\x1b[31m",    # Rot
    logging.CRITICAL: "\x1b[35m", # Magenta
}

class ColoredFormatter(logging.Formatter):
    """
    Wrapper, der basierend auf record.levelno den ANSI-Farbcode um die Log-Zeile legt.
    """
    def format(self, record):
        # Basis-Format
        fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        color = _COLOR_MAP.get(record.levelno, _COLOR_RESET)
        # Baue einen temporären Formatter, der Farbe einschließt
        formatter = logging.Formatter(color + fmt + _COLOR_RESET)
        return formatter.format(record)

# Logs-Verzeichnis anlegen
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Redaction-Filter: entfernt Secrets (OAuth-Code, Tokens, Passwörter) aus jeder
# Logzeile – auch aus fremden Loggern (uvicorn-Access), an die er gehängt wird.
class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        args = record.args
        if isinstance(args, dict):
            record.args = {k: (redact_secrets(v) if isinstance(v, str) else v) for k, v in args.items()}
        elif isinstance(args, tuple):
            record.args = tuple(redact_secrets(a) if isinstance(a, str) else a for a in args)
        return True


# Log-Level per Env (LOG_LEVEL=DEBUG|INFO|WARNING|ERROR), Default INFO.
_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Logger-Instanz
logger = logging.getLogger("backend")
logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
logger.addFilter(RedactionFilter())

# 1) Console-Handler mit Farb-Formatter
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(ColoredFormatter())
logger.addHandler(console_handler)

# 2) File-Handler (rotierend, ohne Farben)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
file_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)


def install_access_log_redaction() -> None:
    """Hängt den Redaction-Filter an die uvicorn-Logger. Nach dem uvicorn-Setup
    aufrufen (z.B. im Lifespan-Start), damit der OAuth-Code in der Callback-URL
    nicht im Access-Log landet."""
    f = RedactionFilter()
    for name in ("uvicorn.access", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addFilter(f)
