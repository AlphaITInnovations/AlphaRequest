# config.py
import os
from dotenv import load_dotenv
import alpharequestmanager.database.database as db
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

    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", 900))
    NINJA_POLL_INTERVAL = int(os.getenv("NINJA_POLL_INTERVAL", 300))

    NINJA_CLIENT_ID = os.getenv("NINJA_CLIENT_ID", "")
    NINJA_CLIENT_SECRET = os.getenv("NINJA_CLIENT_SECRET", "")
    NINJA_REDIRECT_URI = os.getenv("NINJA_REDIRECT_URI", "")

    PORT = int(os.getenv("PORT", 6969))
    HTTPS = str_to_bool(os.getenv("HTTPS", False).lower())
    DEVPOPUP = str_to_bool(os.getenv("DEVPOPUP", False).lower())
    USER_SYNC_INTERVAL = int(os.getenv("USER_SYNC_INTERVAL", "30"))

    #Persistente Werte
    @property
    def COMPANIES(self):
        return db.get_companies()

    @property
    def NINJA_TOKEN(self):
        return db.get_ninja_token()

    @classmethod
    def as_dict(cls):
        return {k: v for k, v in cls.__dict__.items() if not k.startswith("__") and not callable(v)}

config = Config()

