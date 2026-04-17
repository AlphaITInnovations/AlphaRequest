import asyncio
import sys
import uvicorn
from pathlib import Path
from typing import cast
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import State
from backend.api.v1 import tickets as tickets_v1
from backend.api.v1 import auth as auth_v1
from backend.core.app_lifespan import lifespan
from backend.core.session import setup_session
from backend.database import init_db
from backend.models.models import TicketType
from backend.metrics.metrics import init_metrics
from backend.services.personalnummer_generator import init_personalnummer
from backend.services.ticket_service import TicketService
from backend.utils.config import config
from backend.api.v1 import dashboard as dashboard_v1
from backend.api.v1 import users as users_v1
from backend.api.v1 import companies as companies_v1
from backend.api.v1 import personalnummer as personalnummer_v1
from backend.api.v1 import ticket_view as ticket_view_v1
from backend.api.v1 import settings as settings_v1
from backend.api.v1 import ticket_overview as ticket_overview_v1


def get_ticket_type_dict():
    return {t.name: t.value for t in TicketType}


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state = cast(State, app.state)
    app.state.manager = TicketService()

    BASE_DIR = Path(__file__).resolve().parent

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    app.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.templates.env.globals["SESSION_TIMEOUT"] = config.SESSION_TIMEOUT
    app.templates.env.globals["TicketTypes"] = get_ticket_type_dict()

    setup_session(app)
    init_metrics(app, config.SESSION_TIMEOUT, app.state.manager)

    app.include_router(auth_v1.router)
    app.include_router(auth_v1.router, prefix="/api/v1")
    app.include_router(tickets_v1.router, prefix="/api/v1")
    app.include_router(dashboard_v1.router, prefix="/api/v1")
    app.include_router(users_v1.router, prefix="/api/v1")
    app.include_router(companies_v1.router, prefix="/api/v1")
    app.include_router(personalnummer_v1.router, prefix="/api/v1")
    app.include_router(ticket_view_v1.router, prefix="/api/v1")
    app.include_router(settings_v1.router, prefix="/api/v1")
    app.include_router(ticket_overview_v1.router, prefix="/api/v1")

    return app


app = create_app()


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


def configure_event_loop():
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_server(https: bool = False):
    ssl_args = {}
    if https:
        ssl_args = {
            "ssl_keyfile": "../data/cert/key.pem",
            "ssl_certfile": "../data/cert/cert.pem",
        }
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, reload=False, **ssl_args)


def main():
    init_db()
    configure_event_loop()
    init_personalnummer()
    run_server(https=config.HTTPS)


if __name__ == "__main__":

    main()
