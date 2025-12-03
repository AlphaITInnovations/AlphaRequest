import asyncio
import threading
import time
from contextlib import asynccontextmanager
from alpharequestmanager.utils.config import config
from alpharequestmanager.services.microsoft_graph import list_all_users_appcontext, list_all_users_with_e3_license
from alpharequestmanager.services.microsoft_auth import acquire_app_token
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.services import ninja_sync


async def sync_users_into_cache(app):
    logger.info("🔄 Syncing AD user list…")

    token = acquire_app_token()
    access = token["access_token"]

    #users = await list_all_users_appcontext(access)
    users = await list_all_users_with_e3_license(access)

    app.state.user_cache = users
    app.state.user_cache_timestamp = time.time()

    logger.info("✅ Loaded %s users into cache", len(users))


@asynccontextmanager
async def lifespan(app):

    thread = threading.Thread(target=ninja_sync.start_polling, daemon=True)
    thread.start()

    app.state.user_cache = []
    app.state.user_cache_timestamp = 0

    await sync_users_into_cache(app)

    interval = int(config.USER_SYNC_INTERVAL) * 60

    async def user_sync_background():
        while True:
            try:
                await sync_users_into_cache(app)
            except Exception:
                logger.exception("User cache sync failed")
            await asyncio.sleep(interval)

    asyncio.create_task(user_sync_background())

    yield
