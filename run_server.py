#!/usr/bin/env python3
"""Standalone server runner - avoids uvicorn bin path issues."""
import sys
import os

# Ensure pip packages are on path
sys.path.insert(0, "/tmp/.pip-global/lib/python3.12/site-packages")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
