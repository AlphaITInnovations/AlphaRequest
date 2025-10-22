# File: main.py
import sys
import uvicorn
import asyncio
from server import app
from alpharequestmanager.config import config
from alpharequestmanager.ninja_api import get_alpha_request_sendeverfolgung, get_ticket

def main():
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if config.HTTPS:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=config.PORT,
            reload=False,
            ssl_keyfile="data/cert/key.pem",
            ssl_certfile="data/cert/cert.pem"
        )
    else:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=config.PORT,
            reload=False
        )


if __name__ == "__main__":

    main()
