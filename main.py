import sys
import asyncio
import uvicorn
from server import app
from alpharequestmanager.config import config


def configure_event_loop():
    """Set Windows-specific asyncio event loop policy if needed."""
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_server(https: bool = False):
    """Run the Uvicorn server with or without HTTPS."""
    ssl_args = {}
    if https:
        ssl_args = {
            "ssl_keyfile": "data/cert/key.pem",
            "ssl_certfile": "data/cert/cert.pem",
        }

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.PORT,
        reload=False,
        **ssl_args,
    )


def main():
    configure_event_loop()
    run_server(https=config.HTTPS)


if __name__ == "__main__":

    print("starting application...")
    main()
