#!/usr/bin/env python3
"""Standalone server launcher.

Inserts pip global packages into sys.path before anything else imports,
then starts the FastAPI app via uvicorn.
"""
import sys
import os

# This MUST be the first thing that runs - before any app imports
_PIP_PACKAGES = "/tmp/.pip-global/lib/python3.12/site-packages"
if _PIP_PACKAGES not in sys.path:
    sys.path.insert(0, _PIP_PACKAGES)

# Change to this script's directory (project root)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import asyncio
from app.core.database import init_db


async def main():
    # Create database tables first
    await init_db()
    print("Database initialized successfully", flush=True)

    # Start the web server
    import uvicorn
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
