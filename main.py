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
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        reload=False,
    )

