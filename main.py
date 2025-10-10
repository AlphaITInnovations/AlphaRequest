# File: main.py
import sys
import uvicorn
import asyncio
from server import app
from alpharequestmanager.config import config
from dotenv import load_dotenv
import alpharequestmanager.database as db


if __name__ == "__main__":

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(config.as_dict())

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        reload=False,
        ssl_keyfile="cert/key.pem",
        ssl_certfile="cert/cert.pem"
    )

