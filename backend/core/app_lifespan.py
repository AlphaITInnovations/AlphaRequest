import asyncio
import time
from contextlib import asynccontextmanager
from backend.utils.config import config
from backend.services.microsoft_graph import list_all_users_with_e3_license, list_all_groups
from backend.services.microsoft_auth import acquire_app_token
from backend.utils.logger import logger
from backend.database.ticket_group_permissions import ensure_table as ensure_group_perms_table
from backend.database.ticket_locks import ensure_table as ensure_ticket_locks_table
from backend.database.sessions import (
    ensure_table as ensure_sessions_table, clear_all_sessions, prune_stale,
)


EXCLUDED_USERS = {"Administrator AlphaConsult", "CodeTwo Admin"}

async def sync_users_into_cache(app):
    logger.info("🔄 Syncing AD user list…")

    token = acquire_app_token()
    access = token["access_token"]

    users = await list_all_users_with_e3_license(access)

    users = [u for u in users if u.get("displayName") not in EXCLUDED_USERS]

    app.state.user_cache = users
    app.state.user_cache_timestamp = time.time()

    logger.info("✅ Loaded %s users into cache", len(users))


async def sync_groups_into_cache(app):
    logger.info("🔄 Syncing AD group list…")

    token = acquire_app_token()
    access = token["access_token"]

    groups = await list_all_groups(access)

    app.state.group_cache = groups
    app.state.group_cache_timestamp = time.time()

    logger.info("✅ Loaded %s AD groups into cache", len(groups))


@asynccontextmanager
async def lifespan(app):

    # Secrets (OAuth-Code, Tokens) aus den uvicorn-Access-Logs redigieren.
    from backend.utils.logger import install_access_log_redaction
    install_access_log_redaction()

    app.state.user_cache = []
    app.state.user_cache_timestamp = 0
    app.state.group_cache = []
    app.state.group_cache_timestamp = 0

    # DB-Tabellen anlegen
    ensure_group_perms_table()
    ensure_ticket_locks_table()
    ensure_sessions_table()
    # Neustart invalidiert via SERVER_BOOT_ID ohnehin alle Cookies → Tabelle leeren,
    # damit die Live-Liste nicht mit toten Sessions startet.
    clear_all_sessions()

    await sync_users_into_cache(app)
    await sync_groups_into_cache(app)

    interval = int(config.USER_SYNC_INTERVAL) * 60

    async def user_sync_background():
        while True:
            try:
                await sync_users_into_cache(app)
            except Exception:
                logger.exception("User cache sync failed")
            try:
                await sync_groups_into_cache(app)
            except Exception:
                logger.exception("Group cache sync failed")
            # Abgelaufene Session-Rows aufräumen (Präsenz-Fenster = SESSION_TIMEOUT).
            try:
                prune_stale(int(config.SESSION_TIMEOUT))
            except Exception:
                logger.exception("Session prune failed")
            await asyncio.sleep(interval)

    asyncio.create_task(user_sync_background())

    yield