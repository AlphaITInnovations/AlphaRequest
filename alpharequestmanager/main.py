import asyncio
import sys
from pathlib import Path
from typing import cast, List

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import State

from alpharequestmanager.api import (
    admin,
    analytics,
    auth,
    dashboard,
    groups,
    ninja_oauth,
    personalnummer,
    ticket_overview,
    tickets,
    users, ticket_overview_groups, mail,
)
from alpharequestmanager.core.app_lifespan import lifespan
from alpharequestmanager.core.session import setup_session
from alpharequestmanager.database import database as db
from alpharequestmanager.models.models import TicketType
from alpharequestmanager.services import ticket_overview_service
from alpharequestmanager.services.metrics import init_metrics
from alpharequestmanager.services.personalnummer_generator import init_personalnummer
from alpharequestmanager.services.ticket_overview_service import get_overview_groups, save_overview_groups, \
    add_overview_groups_member
from alpharequestmanager.services.ticket_permissions import init_ticket_permissions
from alpharequestmanager.services.ticket_service import TicketService
from alpharequestmanager.utils.config import config



def get_ticket_type_dict():
    return {t.name: t.value for t in TicketType}



def create_app() -> FastAPI:

    app = FastAPI(lifespan=lifespan)

    app.state = cast(State, app.state)
    app.state.manager = TicketService()

    BASE_DIR = Path(__file__).resolve().parent

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )

    app.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.templates.env.globals["SESSION_TIMEOUT"] = config.SESSION_TIMEOUT
    app.templates.env.globals["TicketTypes"] = get_ticket_type_dict()

    setup_session(app)

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(tickets.router)
    app.include_router(admin.router)
    app.include_router(analytics.router)
    app.include_router(ninja_oauth.router)
    app.include_router(users.router)
    app.include_router(groups.router)
    app.include_router(ticket_overview.router)
    app.include_router(personalnummer.router)
    app.include_router(ticket_overview_groups.router)
    app.include_router(mail.router)

    init_metrics(app, config.SESSION_TIMEOUT, app.state.manager)

    return app


app = create_app()

def configure_event_loop():
    """Set Windows-specific asyncio event loop policy if needed."""
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_server(https: bool = False):
    """Run the Uvicorn server with or without HTTPS."""
    ssl_args = {}
    if https:
        ssl_args = {
            "ssl_keyfile": "../data/cert/key.pem",
            "ssl_certfile": "../data/cert/cert.pem",
        }

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.PORT,
        reload=False,
        **ssl_args,
    )




def main():

    db.init_db()
    init_ticket_permissions()
    configure_event_loop()
    init_personalnummer()
    run_server(https=config.HTTPS)


if __name__ == "__main__":
    main()

